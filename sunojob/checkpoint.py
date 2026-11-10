"""Read-only local completion evidence. Makes no API or SMTP requests."""

import argparse
import json
from pathlib import Path
import sqlite3

from .receipt import display_time, verify_receipt
from .workflow import digest


ROOT = Path(__file__).resolve().parents[1]


def audit_database(path):
    path = Path(path).resolve()
    result = {"database_present": path.is_file(), "sessions": [], "issues": [],
              "manual_checks_remaining": [
                  "Listen to the English and Telugu readbacks and check their meanings.",
                  "Check both actual inboxes and compare their receipt attachments.",
                  "Evaluate independently labelled natural and degraded recordings.",
                  "Prepare the final demo and submission; remote access is not provided by this command."]}
    if not path.is_file():
        return result
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        db.execute("BEGIN")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"review_sessions", "review_versions"} <= tables:
            raise ValueError("This is not a SunoJob review database")
        for sid, raw in db.execute("SELECT id,body FROM review_sessions ORDER BY rowid DESC"):
            item = {"request": sid[:8], "language": "unknown", "version": None,
                    "both_approvals_match": False, "receipt_verified": False,
                    "saved_approval_snapshot_verified": False,
                    "both_copies_accepted_by_smtp": False, "inbox_delivery": "not_verified"}
            try:
                body = json.loads(raw)
                item.update(language=body["language"], version=body["version"], state=body["state"])
                item["pending_correction"] = bool(body.get("pending_text"))
                if "review_events" in tables:
                    event = db.execute("SELECT kind,created_at FROM review_events WHERE session_id=? ORDER BY id DESC LIMIT 1",
                                       (sid,)).fetchone()
                    if event:
                        item["last_action"], item["last_action_at"] = event
                card_hash = digest(body["card"])
                stored = db.execute("SELECT sha256 FROM review_versions WHERE session_id=? AND version=?",
                                    (sid, body["version"])).fetchone()
                if not stored or stored[0] != card_hash:
                    raise ValueError("Stored card failed its integrity check")
                approvals = [body.get(role) for role in ("customer_confirmation", "owner_confirmation")]
                item["both_approvals_match"] = body["state"] == "both_confirmed" and not body.get("pending_text") and all(
                    approval and approval["version"] == body["version"] and approval["sha256"] == card_hash
                    for approval in approvals)
                receipt = None
                if "review_receipts" in tables:
                    row = db.execute("SELECT body FROM review_receipts WHERE session_id=? AND version=?",
                                     (sid, body["version"])).fetchone()
                    if row:
                        receipt = json.loads(row[0])
                        verify_receipt(receipt)
                        if (receipt["session_id"] != sid or receipt["version"] != body["version"]
                                or receipt["card_sha256"] != card_hash):
                            raise ValueError("Saved receipt does not match the current approvals")
                        item["saved_approval_snapshot_verified"] = True
                        if item["both_approvals_match"] and any(receipt[role] != body.get(role) for role in
                                                                ("customer_confirmation", "owner_confirmation")):
                            raise ValueError("Saved receipt does not match the current approvals")
                        item["receipt_verified"] = bool(item["both_approvals_match"])
                if body["state"] == "both_confirmed" and not item["receipt_verified"]:
                    raise ValueError("Confirmed state has missing or mismatched approvals or receipt")
                if receipt and item["receipt_verified"] and "review_mail_jobs" in tables:
                    for job_raw, in db.execute("SELECT body FROM review_mail_jobs WHERE session_id=? AND version=?",
                                               (sid, body["version"])):
                        job = json.loads(job_raw)
                        accepted = {target["role"] for target in job["targets"]
                                    if target["status"] == "accepted_by_smtp"}
                        if (job["receipt_id"] == receipt["receipt_id"]
                                and job["receipt_sha256"] == receipt["receipt_sha256"]
                                and accepted == {"customer", "owner"}):
                            item["both_copies_accepted_by_smtp"] = True
            except (ValueError, KeyError, TypeError):
                item["issue"] = "Saved record is incomplete or failed an integrity check; inspect it before using it."
                item.update(both_approvals_match=False, receipt_verified=False,
                            saved_approval_snapshot_verified=False,
                            both_copies_accepted_by_smtp=False)
                result["issues"].append(item["request"])
            result["sessions"].append(item)
    result["languages_with_approved_receipts"] = sorted({item["language"] for item in result["sessions"]
                                                       if item["receipt_verified"]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / ".local/reviews.sqlite3")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = audit_database(args.database)
    if args.json:
        print(json.dumps(report, indent=2))
        return
    print("SUNOJOB CHECKPOINT — saved evidence only; no network calls or database changes")
    if not report["database_present"]:
        print("No saved review database found. Start the app and create a request first.")
    for item in report["sessions"]:
        yesno = lambda flag: "YES" if item[flag] else "PENDING"
        print(f"{item['request']} | {item['language']} | v{item['version']} | "
              f"approvals {yesno('both_approvals_match')} | receipt {yesno('receipt_verified')} | "
              f"SMTP both {yesno('both_copies_accepted_by_smtp')}")
        if item.get("pending_correction"):
            print("  Pending correction: current approvals must be renewed after it is applied.")
        if item.get("saved_approval_snapshot_verified") and not item["receipt_verified"]:
            print("  Earlier approved snapshot is intact; it does not approve the pending correction.")
        if item.get("last_action"):
            print("  Last recorded action: " + item["last_action"].replace("_", " ") + " · " + display_time(item["last_action_at"]))
        if item.get("issue"):
            print("  " + item["issue"])
    print("SMTP acceptance does not verify inbox delivery. Names do not verify identity.")
    print("Manual completion checks:")
    for check in report["manual_checks_remaining"]:
        print("- " + check)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise SystemExit(f"Checkpoint could not read the database: {type(exc).__name__}. Check its path and format.") from None
