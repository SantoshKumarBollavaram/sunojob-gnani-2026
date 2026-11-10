"""Start the local voice-workflow development server."""

import argparse
import getpass
import os
from pathlib import Path

import uvicorn

from .providers import DEFAULT_GEMINI_MODEL
from .speech import LiveServices
from .webapp import create_app
from .workflow import ReviewStore
from .mailer import MailConfig, SMTPMailer


def credential(name, label):
    value = os.environ.get(name, "").strip() or getpass.getpass(label).strip()
    if not value or any(not 33 <= ord(c) <= 126 for c in value):
        raise ValueError("Keys must be printable ASCII without whitespace")
    return value


def configure_mail():
    def setting(name, label, default=""):
        value = os.environ.get(name, "").strip()
        return value or input(label + (f" [{default}]" if default else "") + ": ").strip() or default
    host = setting("SUNOJOB_SMTP_HOST", "SMTP host", "smtp.gmail.com")
    try:
        port = int(setting("SUNOJOB_SMTP_PORT", "SMTP port", "587"))
    except ValueError:
        raise ValueError("SMTP port must be a number") from None
    mode = setting("SUNOJOB_SMTP_MODE", "TLS mode: starttls or ssl", "starttls" if port == 587 else "ssl")
    sender = setting("SUNOJOB_SMTP_FROM", "Sender email")
    username = setting("SUNOJOB_SMTP_USERNAME", "SMTP username", sender)
    password = os.environ.get("SUNOJOB_SMTP_PASSWORD", "") or getpass.getpass("SMTP app password (hidden): ")
    if host.casefold() == "smtp.gmail.com":
        password = password.replace(" ", "")
    return SMTPMailer(MailConfig(host, port, mode, sender, username, password))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model", default=os.environ.get("SUNOJOB_GEMINI_MODEL", DEFAULT_GEMINI_MODEL))
    parser.add_argument("--email", action="store_true", help="Configure TLS SMTP sending; startup sends nothing")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port from 1024 to 65535")
    gnani = credential("GNANI_API_KEY", "Gnani API key (hidden): ")
    gemini = credential("GEMINI_API_KEY", "Gemini API key (hidden): ")
    mailer = configure_mail() if args.email else None
    root = Path(__file__).resolve().parents[1] / ".local"
    store = ReviewStore(root / "reviews.sqlite3")
    store.recover_interrupted()
    services = LiveServices(gnani, gemini, args.model, root / "voice-audio")
    print(f"Open http://127.0.0.1:{args.port}", flush=True)
    app = create_app(store, services, mailer)
    app.state.delivery.recover_interrupted()
    if mailer:
        print("SMTP configured. No connection has been tested and no messages have been sent.", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        print(f"Configuration error: {exc}")
    except KeyboardInterrupt:
        print("Stopped. Verify key format and restart if needed.")
