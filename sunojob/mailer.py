"""TLS-only SMTP submission. Acceptance is not proof of inbox delivery."""

from dataclasses import dataclass, field
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr
import re
import smtplib
import ssl

from .receipt import LIMITATION, email_address, receipt_html, receipt_json


@dataclass(frozen=True)
class MailConfig:
    host: str
    port: int
    mode: str
    sender: str
    username: str
    password: str = field(repr=False)

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", self.host):
            raise ValueError("SMTP host must be a hostname, without a URL or path")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("Invalid SMTP port")
        if self.mode not in {"ssl", "starttls"}:
            raise ValueError("Choose ssl or starttls; plaintext email is not supported")
        if email_address(self.sender) != self.sender:
            raise ValueError("Invalid sender email")
        if not self.username or any(ord(c) < 32 for c in self.username):
            raise ValueError("Invalid SMTP username")
        if not self.password or any(c in self.password for c in "\r\n\x00"):
            raise ValueError("Invalid SMTP password")


def message_subject(receipt):
    return f"SunoJob shared record — version {receipt['version']} — {receipt['receipt_id'][:8]}"


def submission_message(receipt, sender, target, created_at):
    from datetime import datetime
    from email.utils import format_datetime
    message = EmailMessage(policy=SMTP)
    message["From"] = formataddr(("SunoJob", email_address(sender)))
    message["To"] = email_address(target["address"])
    message["Subject"] = message_subject(receipt)
    message["Date"] = format_datetime(datetime.fromisoformat(created_at))
    message["Message-ID"] = target["message_id"]
    message.set_content(
        f"Both parties recorded approval of SunoJob version {receipt['version']}.\n"
        f"Record ID: {receipt['receipt_id']}\nCard SHA-256: {receipt['card_sha256']}\n\n"
        "The attached HTML and JSON record is identical in the customer and owner copies.\n"
        "It records the terms at the approval timestamps; later revisions may exist.\n\n" + LIMITATION + "\n")
    message.add_attachment(receipt_html(receipt), maintype="text", subtype="html", filename="shared-record.html")
    message.add_attachment(receipt_json(receipt), maintype="application", subtype="json", filename="shared-record.json")
    if len(message.as_bytes()) > 10_000_000:
        raise ValueError("Email exceeds the prototype's 10 MB message limit; download the record instead")
    return message


class SMTPMailer:
    def __init__(self, config):
        self.config = config
        self.sender = config.sender

    def submit(self, message, recipient):
        """Exactly one network submission attempt; never automatically retry."""
        connection = None
        submission_started = False
        result = None
        try:
            context = ssl.create_default_context()
            if self.config.mode == "ssl":
                connection = smtplib.SMTP_SSL(self.config.host, self.config.port,
                    timeout=20, context=context, local_hostname="localhost")
            else:
                connection = smtplib.SMTP(self.config.host, self.config.port,
                    timeout=20, local_hostname="localhost")
                connection.ehlo()
                connection.starttls(context=context)
            connection.ehlo()
            connection.login(self.config.username, self.config.password)
            submission_started = True
            refused = connection.send_message(message, from_addr=self.sender, to_addrs=[recipient])
            result = {"status": "rejected", "detail": "SMTP server refused the recipient"} if refused else {
                "status": "accepted_by_smtp", "detail": "Accepted by SMTP; inbox delivery is not verified"}
        except smtplib.SMTPAuthenticationError:
            result = {"status": "failed_before_submission", "detail": "SMTP authentication failed; check sender credentials"}
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError):
            result = {"status": "rejected", "detail": "SMTP server explicitly rejected this submission"}
        except (smtplib.SMTPResponseException, smtplib.SMTPNotSupportedError):
            result = {"status": "rejected" if submission_started else "failed_before_submission",
                      "detail": "SMTP command was refused; check server configuration"}
        except (OSError, smtplib.SMTPException):
            result = {"status": "unknown" if submission_started else "failed_before_submission",
                      "detail": "Connection interrupted; submission outcome is uncertain" if submission_started else
                                "Could not establish an authenticated TLS SMTP connection"}
        finally:
            # A QUIT/disconnect error after send_message succeeded must never
            # turn a known accepted message into a failed/retryable submission.
            if connection is not None:
                try:
                    connection.quit()
                except (OSError, smtplib.SMTPException):
                    try:
                        connection.close()
                    except (OSError, smtplib.SMTPException):
                        pass
        return result
