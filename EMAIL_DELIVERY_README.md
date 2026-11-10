# SunoJob: explicit email delivery checkpoint

## Current state

The user has exercised the English customer voice loop, revisions, spoken
confirmation and separate owner acceptance in the browser. Their latest
screenshots show both approvals for version 3 and the shared-record controls.
The screenshots alone do not verify downloaded file equality or inbox receipt.
Telugu browser testing remains deferred.

This update adds direct SMTP submission of the same saved receipt to the two
specified recipients. It preserves the existing download and unsent-draft paths.
Neither server startup nor an email preview sends anything. Each submission
requires a reviewed preview and the explicit **Send to both now** action.

**182 offline automated tests passed**, including the earlier 155 and 27 new
email tests. SMTP transport is mocked in tests; no real email was sent during
development. The new browser controls and actual SMTP credentials have not
been live-tested here. Complete the acceptance check on your laptop.

## Install

Stop your running server using **Ctrl+C** first. Save
`SunoJob_Email_Delivery_Checkpoint.zip` in `~/Downloads`, then run:

```bash
bash <<'BASH'
set -eu
cd "$HOME/sunojob"
test -f "$HOME/Downloads/SunoJob_Email_Delivery_Checkpoint.zip"
mkdir -p .local/backups
sunojob_mail_backup="$(mktemp -d .local/backups/email-delivery-XXXXXX)"
for path in sunojob scripts tests fixtures requirements-core.txt requirements-voice.txt README.md
do
  if [ -e "$path" ]; then
    cp -a "$path" "$sunojob_mail_backup/"
  fi
done
if [ -f .local/reviews.sqlite3 ]; then
  .venv/bin/python - "$sunojob_mail_backup/reviews.sqlite3" <<'PY'
import sqlite3
import sys
with sqlite3.connect('.local/reviews.sqlite3') as source:
    with sqlite3.connect(sys.argv[1]) as destination:
        source.backup(destination)
PY
fi
.venv/bin/python -m zipfile -e \
  "$HOME/Downloads/SunoJob_Email_Delivery_Checkpoint.zip" .
.venv/bin/python -m unittest discover -s tests -q
printf '\nBackup: %s\n' "$sunojob_mail_backup"
BASH
```

Expected: **182 tests, OK**. No new Python dependency is needed. The existing
Starlette/httpx deprecation warning is unrelated to email behavior. New database
tables are additive; existing cards, approvals and receipts are retained.

## Configure a sender

Start in your normal terminal, outside the installation heredoc:

```bash
cd "$HOME/sunojob"
.venv/bin/python -m sunojob.serve \
  --model gemini-3.5-flash-lite --email
```

The terminal first asks for the two API keys as before, then SMTP settings.
You can reuse your already approved version 3 without making any AI calls.

For a personal Gmail account that offers app passwords, use:

| Prompt | Value |
| --- | --- |
| SMTP host | `smtp.gmail.com` — press Enter for the default |
| SMTP port | `587` — press Enter |
| TLS mode | `starttls` — press Enter |
| Sender email | Your complete Gmail address |
| SMTP username | Press Enter to use the sender address |
| SMTP app password | The app password, entered only at the hidden terminal prompt |

Gmail app passwords require 2-Step Verification and may be unavailable for some
accounts, including some managed accounts or Advanced Protection configurations.
Use Google's current instructions to create a password for this local app:

https://support.google.com/accounts/answer/185833

Never enter your normal Google account password or paste an app password into
chat. This prototype does not implement Google OAuth. If app passwords are not
available, use a provider/account that supports authenticated SMTP, or keep
using the existing unsent drafts. Do not weaken account security to make this
local test work. Other SMTP providers may require a verified sender or different
credentials; use their official settings in the same prompts.

The server supports certificate-verified implicit TLS (`ssl`, usually port 465)
and mandatory STARTTLS (`starttls`, usually port 587). It does not fall back to
plaintext. No SMTP connection is made at startup: **configured** does not mean
authentication has succeeded.

Optional environment settings are `SUNOJOB_SMTP_HOST`, `SUNOJOB_SMTP_PORT`,
`SUNOJOB_SMTP_MODE`, `SUNOJOB_SMTP_FROM`, `SUNOJOB_SMTP_USERNAME` and
`SUNOJOB_SMTP_PASSWORD`. Prefer the hidden password prompt during this local
check. SMTP credentials stay in server memory and are not written to the
database, source files, receipt or browser. Raw SMTP error messages are not
stored or returned to the browser.

Starting without `--email` keeps direct submission disabled. Downloads and
unsent email drafts still work.

## First live acceptance check

Use the fictional catering request and two inboxes you control. Do not use
another person's address for this first test.

1. Open **http://127.0.0.1:8765** and refresh the existing browser tab after the
   server restart. Select the already approved version 3 if needed.
2. Under **Shared record → Email copies to both parties**, enter the customer
   and owner recipient addresses. The sender is the account configured above;
   recipients do not need to be the same account.
3. Click **Preview direct email**. Verify the sender, both recipient addresses,
   subject, version, record ID and two attachment filenames/hashes. Previewing
   creates a local record but sends no email.
4. Select the checkbox stating that you reviewed both recipients and the record.
   Click **Send to both now** once. This makes real SMTP submission attempts.
5. Expected: one result for the customer and one for the owner. A successful
   server response is labelled **Accepted by SMTP — inbox delivery not verified**.
6. Check both actual inboxes, including Spam if necessary. Open the HTML record
   and verify version 3, quantity 46, both restrictions and the approval records.
   Compare attachment SHA-256 values or file bytes across the two received
   copies. Record inbox receipt separately from the application's SMTP status.
7. Refresh the page and **Refresh email results**. The recipient outcomes should
   persist. Repeating the same send request must not create another submission.
   A fresh preview also skips copies already accepted for that receipt/role/
   address, while displaying the previous result.

Sender and recipient addresses are distinct concepts. Enter your actual sender
account at startup, and the intended recipients in the browser. Recipient
ownership and display-name identity are not verified by SunoJob.

## Results and recovery

| Result | Meaning and next action |
| --- | --- |
| Preview only | Nothing submitted; review and explicitly send if intended |
| Accepted by SMTP | SMTP accepted the copy; check the actual inbox. It may still bounce, be filtered or arrive late |
| Rejected | SMTP explicitly refused submission; inspect the recipient/provider settings before a new reviewed preview |
| Failed before submission | No message submission began, such as an authentication, TLS or connection failure |
| Unknown outcome | Submission started but its result was lost or uncertain. Automatic resend is blocked; inspect the mailbox/sender logs before any manual resend |
| Not attempted | A restart occurred before that copy's submission began; a new reviewed preview may attempt it |

There are no automatic SMTP retries. For a known rejection or a failure before
submission, correct the issue, prepare a fresh preview, review it and explicitly
send again. Already accepted or uncertain targets are not automatically resent.
The old preview ID always returns its saved outcome instead of retrying.

An interruption can leave the first recipient accepted and the second unknown
or unattempted. Restart recovery preserves known results, marks an in-flight
submission unknown and marks reserved but unstarted copies not attempted. It
does not send messages during startup. Check recorded results before deciding
what to do next. There is no in-app override for resending an uncertain copy;
the existing downloads/drafts remain available for a deliberate manual action.

Previews expire after 15 minutes. A new card version or different sender
invalidates an unsent preview. Editing recipient fields in the browser also
requires a new preview. Once submission begins, card corrections are briefly
blocked until its outcome is recorded, preventing an old-version send racing
with a revision. A later correction clears current approvals and requires fresh
customer and owner approval; already sent messages cannot be recalled.

Duplicate suppression is local and keyed by receipt ID, role and recipient
address, with domain case normalized. It is not a global exactly-once guarantee.
Using another sender tool or manually changing/deleting the database can create
duplicates. Supplying the same address for both roles intentionally creates two
role-specific copies. The envelope and To header contain only one recipient
per copy; the other party's email address is not added as CC or BCC.

## Privacy, limits and architecture

Both attachments contain original transcript turns and approval evidence.
Review them before sending. This update stores recipient addresses, preview
metadata, message IDs, timestamps and per-recipient results in `.local/reviews.sqlite3`.
Earlier checkpoint statements that recipient addresses are not stored applied
only to the unsent-draft path, not this direct delivery feature. Keep `.local/`
and `.venv/` out of Git and public uploads.

Messages are limited to 10 MB each. The SMTP transport uses per-operation
timeouts and one attempt per target; total UI wait time can vary. Passwords
are never passed as command-line arguments by the app. No debug SMTP logging
is enabled. Failure details are intentionally short and exclude raw provider
responses that might contain credentials or other sensitive values.

| Module | Responsibility |
| --- | --- |
| `sunojob/mailer.py` | Validated sender configuration, MIME attachments and TLS SMTP submission |
| `sunojob/delivery.py` | Saved previews, submission reservation, recipient deduplication and recovery |
| `sunojob/workflow.py` | Card/version state; blocks corrections during submission |
| `sunojob/webapp.py` | Explicit preview/send endpoints and recorded outcomes |
| `sunojob/serve.py` | Optional sender setup using hidden credentials |

Offline tests cover TLS-before-login, certificate validation, authentication
errors, explicit rejection, mid-submission disconnects, post-acceptance QUIT
failures, duplicate clicks, partial outcomes, stale previews, crash recovery,
recipient isolation, exact attachments and credential redaction. They do not
establish real provider compatibility or inbox delivery.

This is still a loopback-only development app without user authentication.
Owner links work locally and do not verify identity. Do not expose this server
publicly in this form. No record is a verified digital signature or guarantee
of legal enforceability. For public deployment, sender authentication, user
authentication, recipient verification and delivery/bounce handling need their
own design and checks.

## References checked for this implementation

- Python 3.12 SMTP client API and exception behavior:
  https://docs.python.org/3.12/library/smtplib.html
- Google's Gmail SMTP settings (outgoing SMTP only; no POP setup is needed here):
  https://support.google.com/mail/answer/7104828?hl=en
- Google's account-specific app-password requirements:
  https://support.google.com/accounts/answer/185833

After the live delivery check, prioritize evaluation on independently labelled
natural English recordings and degraded audio, then return to Telugu and the
public demo/submission work. Current fixture and integration successes are not
a measured real-world accuracy result.
