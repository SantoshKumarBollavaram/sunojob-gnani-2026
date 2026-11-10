"""Persistent, version-specific customer review. Identity verification comes later."""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import unicodedata
import uuid

from .models import Extraction, SourceTurn
from .validation import validate_card


class WorkflowError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()


def reply_kind(text):
    # Whole utterance only. 'Yes, but change ...' must never approve a card.
    value = unicodedata.normalize("NFKC", text).strip().casefold().strip(" .!?।")
    yes = {"yes", "correct", "i confirm", "i agree", "confirmed", "అవును", "సరే", "అంగీకరిస్తున్నాను", "నేను అంగీకరిస్తున్నాను"}
    no = {"no", "incorrect", "not correct", "కాదు", "లేదు"}
    return "confirm" if value in yes else "reject" if value in no else "change"


class ReviewStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS review_sessions(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS review_versions(session_id TEXT, version INTEGER,
                card TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(session_id,version));
            CREATE TABLE IF NOT EXISTS review_events(id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT, kind TEXT, body TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS review_receipts(session_id TEXT, version INTEGER,
                body TEXT NOT NULL, PRIMARY KEY(session_id,version));
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def event(self, db, session_id, kind, body):
        db.execute("INSERT INTO review_events(session_id,kind,body,created_at) VALUES(?,?,?,?)",
                   (session_id, kind, json.dumps(body, ensure_ascii=False), now()))

    def _read(self, db, session_id):
        row = db.execute("SELECT body FROM review_sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise WorkflowError("Session not found")
        body = json.loads(row[0])
        body.setdefault("owner_review", None)
        body.setdefault("owner_change_request", None)
        stored = db.execute("SELECT sha256 FROM review_versions WHERE session_id=? AND version=?",
                            (session_id, body["version"])).fetchone()
        if not stored or stored[0] != digest(body["card"]):
            raise WorkflowError("Stored card failed its integrity check")
        return body

    def _mutate(self, session_id, action):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            body = self._read(db, session_id)
            action(db, body)
            body["updated_at"] = now()
            db.execute("UPDATE review_sessions SET body=? WHERE id=?",
                       (json.dumps(body, ensure_ascii=False), session_id))
            return body

    @staticmethod
    def expected(body, version):
        if type(version) is not int or body["version"] != version:
            raise WorkflowError("The card changed. Review and listen to the current version.")

    def create(self, sources, extraction, language="en-IN", provenance=None):
        if language not in {"en-IN", "te-IN"}:
            raise WorkflowError("Choose English or Telugu")
        card = validate_card(extraction, sources)
        session_id = uuid.uuid4().hex
        body = {"id": session_id, "version": 1, "language": language,
                "state": "draft", "card": card, "readback": None,
                "operation": None, "pending_text": None, "customer_confirmation": None,
                "owner_confirmation": None, "created_at": now(), "updated_at": now()}
        with self.connect() as db:
            db.execute("INSERT INTO review_sessions VALUES(?,?)", (session_id, json.dumps(body, ensure_ascii=False)))
            db.execute("INSERT INTO review_versions VALUES(?,?,?,?,?)",
                       (session_id, 1, json.dumps(card, ensure_ascii=False), digest(card), now()))
            self.event(db, session_id, "created", provenance or {})
        return body

    def get(self, session_id, include_activity=False):
        with self.connect() as db:
            if include_activity:
                db.execute("BEGIN")
            body = self._read(db, session_id)
            if include_activity:
                row = db.execute("SELECT kind,created_at FROM review_events WHERE session_id=? ORDER BY id DESC LIMIT 1",
                                 (session_id,)).fetchone()
                body["last_activity"] = {"kind": row[0], "at": row[1]} if row else None
            return body

    def recent(self):
        with self.connect() as db:
            rows = db.execute("SELECT body FROM review_sessions ORDER BY rowid DESC LIMIT 20").fetchall()
            return [{k: b[k] for k in ("id", "version", "state", "language", "updated_at")}
                    for b in (json.loads(r[0]) for r in rows)]

    def receipt_history(self, session_id):
        with self.connect() as db:
            body = self._read(db, session_id)
            rows = db.execute("SELECT version,body FROM review_receipts WHERE session_id=? ORDER BY version DESC",
                              (session_id,)).fetchall()
            from .receipt import verify_receipt
            snapshots = []
            for version, raw in rows:
                receipt = json.loads(raw)
                verify_receipt(receipt)
                stored = db.execute("SELECT sha256 FROM review_versions WHERE session_id=? AND version=?",
                                    (session_id, version)).fetchone()
                if (receipt["session_id"] != session_id or receipt["version"] != version
                        or not stored or stored[0] != receipt["card_sha256"]):
                    raise WorkflowError("Saved approval snapshot does not match its recorded version")
                current = (body["state"] == "both_confirmed" and not body.get("pending_text")
                           and version == body["version"] and receipt["card_sha256"] == digest(body["card"])
                           and all(receipt[role] == body.get(role) for role in
                                   ("customer_confirmation", "owner_confirmation")))
                snapshots.append({"version": version, "receipt_id": receipt["receipt_id"],
                                  "issued_at": receipt["issued_at"], "is_current_approval": current})
            return snapshots

    def recover_interrupted(self):
        with self.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM review_sessions")]
        for session_id in ids:
            body = self.get(session_id)
            if body["state"] == "updating":
                self.fail_change(body["id"], body["operation"])

    def prepare_readback(self, session_id, version, text):
        def action(db, body):
            self.expected(body, version)
            if body.get("delivery_in_progress"):
                raise WorkflowError("Email submission is still running. Wait for its result before changing the card.")
            if body["state"] == "updating":
                raise WorkflowError("A correction is still processing")
            if body["pending_text"]:
                raise WorkflowError("Your correction has not been applied. Retry it before listening or confirming.")
            if body.get("owner_change_request"):
                raise WorkflowError("The owner requested a change. Resolve it in a new draft first.")
            if body["state"] in {"customer_confirmed", "both_confirmed"}:
                raise WorkflowError("This version is confirmed. Propose a correction to revise it.")
            body["readback"] = {"id": secrets.token_urlsafe(24), "version": version,
                                 "sha256": digest(body["card"]), "text": text,
                                 "audio_ready": False, "completed": False, "consumed": False}
            body["state"] = "awaiting_readback"
            self.event(db, session_id, "readback_prepared", {"version": version})
        return self._mutate(session_id, action)

    def _readback(self, body, version, token, completed=False):
        self.expected(body, version)
        rb = body["readback"]
        if not rb or rb["id"] != token or rb["version"] != version or rb["sha256"] != digest(body["card"]):
            raise WorkflowError("Readback is stale. Play the current version again.")
        if rb["consumed"] or body["state"] == "updating":
            raise WorkflowError("That readback has already received a reply")
        if completed and not rb["completed"]:
            raise WorkflowError("Finish listening to the readback before confirming")
        return rb

    def ready_readback(self, session_id, version, token, audio_sha256):
        def action(db, body):
            rb = self._readback(body, version, token)
            rb.update(audio_ready=True, audio_sha256=audio_sha256)
            self.event(db, session_id, "readback_audio_generated", {"version": version, "audio_sha256": audio_sha256})
        return self._mutate(session_id, action)

    def can_reply(self, session_id, version, token):
        body = self.get(session_id)
        self._readback(body, version, token, completed=True)
        return body

    def complete_readback(self, session_id, version, token):
        def action(db, body):
            rb = self._readback(body, version, token)
            if not rb["audio_ready"]:
                raise WorkflowError("Readback audio has not been generated successfully")
            rb["completed"] = True
            body["state"] = "awaiting_reply"
            self.event(db, session_id, "browser_reported_playback_complete", {"version": version, "readback_id": token})
        return self._mutate(session_id, action)

    def reply(self, session_id, version, token, text, provenance=None):
        kind = reply_kind(text)
        if kind == "change":
            # Final version/readback checks happen again inside start_change.
            return self.start_change(session_id, version, text, token=token, provenance=provenance)
        def action(db, body):
            rb = self._readback(body, version, token, completed=True)
            if kind == "confirm" and body["card"]["extraction"]["questions"]:
                raise WorkflowError("Answer the clarification questions before confirming")
            rb["consumed"] = True
            if kind == "confirm":
                body["state"] = "customer_confirmed"
                body["customer_confirmation"] = {"version": version, "sha256": digest(body["card"]),
                    "readback_id": token, "reply": text, "at": now(), "identity_verified": False}
            else:
                body["state"] = "needs_correction"
            self.event(db, session_id, "customer_" + kind, {"version": version, "text": text,
                                                           "provenance": provenance or {}})
        return self._mutate(session_id, action)

    def start_change(self, session_id, version, text, token=None, provenance=None):
        if not isinstance(text, str) or not text.strip():
            raise WorkflowError("Provide the correction or missing information")
        def action(db, body):
            self.expected(body, version)
            if body.get("delivery_in_progress"):
                raise WorkflowError("Email submission is still running. Wait for its result before changing the card.")
            if body["state"] == "updating":
                raise WorkflowError("A correction is already processing")
            if token is not None:
                self._readback(body, version, token, completed=True)
            body["state"] = "updating"
            body["operation"] = secrets.token_urlsafe(24)
            body["pending_text"] = text
            body["readback"] = None
            # Prior confirmation remains in the audit log, never on the new draft.
            body["customer_confirmation"] = None
            body["owner_confirmation"] = None
            body["owner_review"] = None
            body["owner_change_request"] = None
            self.event(db, session_id, "correction_proposed", {"version": version, "text": text,
                                                              "provenance": provenance or {}})
        return self._mutate(session_id, action)

    def finish_change(self, session_id, version, operation, sources, extraction):
        card = validate_card(extraction, sources)
        def action(db, body):
            self.expected(body, version)
            if body["state"] != "updating" or body["operation"] != operation:
                raise WorkflowError("This correction result is stale")
            old_sources = body["card"]["sources"]
            if card["sources"][:-1] != old_sources or card["sources"][-1]["text"] != body["pending_text"]:
                raise WorkflowError("Correction must preserve source history and the new reply")
            body.update(version=version + 1, state="draft", card=card, readback=None,
                        operation=None, pending_text=None)
            db.execute("INSERT INTO review_versions VALUES(?,?,?,?,?)",
                       (session_id, body["version"], json.dumps(card, ensure_ascii=False), digest(card), now()))
            self.event(db, session_id, "new_version", {"version": body["version"], "sha256": digest(card)})
        return self._mutate(session_id, action)

    def fail_change(self, session_id, operation):
        def action(db, body):
            if body["operation"] == operation:
                body.update(state="needs_correction", operation=None)
                self.event(db, session_id, "correction_failed", {"version": body["version"]})
        return self._mutate(session_id, action)

    @staticmethod
    def _customer_approved(body):
        approval = body.get("customer_confirmation")
        if (not approval or approval["version"] != body["version"]
                or approval["sha256"] != digest(body["card"]) or body["pending_text"]
                or body["card"]["extraction"]["questions"]):
            raise WorkflowError("The customer must confirm the current complete version first")

    def issue_owner_review(self, session_id, version):
        token = secrets.token_urlsafe(32)
        def action(db, body):
            self.expected(body, version)
            self._customer_approved(body)
            if body["state"] != "customer_confirmed":
                raise WorkflowError("Owner review is unavailable in this state")
            body["owner_review"] = {
                "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                "version": version, "sha256": digest(body["card"]),
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()}
            self.event(db, session_id, "owner_review_issued", {"version": version})
        body = self._mutate(session_id, action)
        return {"version": version, "token": token,
                "expires_at": body["owner_review"]["expires_at"]}

    def _owner(self, body, token, version=None):
        if version is not None:
            self.expected(body, version)
        review = body.get("owner_review")
        if (not isinstance(token, str) or len(token) > 256 or not review
                or not secrets.compare_digest(review["token_sha256"], hashlib.sha256(token.encode()).hexdigest())):
            raise WorkflowError("Owner link is invalid or was replaced")
        if now() > review["expires_at"]:
            raise WorkflowError("Owner link expired. Ask for a new review link")
        if review["version"] != body["version"] or review["sha256"] != digest(body["card"]):
            raise WorkflowError("Owner link belongs to an older card")
        self._customer_approved(body)

    def owner_view(self, session_id, token):
        with self.connect() as db:
            body = self._read(db, session_id)
            self._owner(body, token)
            return {key: body[key] for key in ("id", "version", "language", "state", "card",
                    "customer_confirmation", "owner_confirmation", "owner_change_request")}

    def owner_accept(self, session_id, token, version, name, reviewed):
        if reviewed is not True:
            raise WorkflowError("Explicit review of this version is required")
        name = name.strip()
        if not 1 <= len(name) <= 120 or any(ord(c) < 32 for c in name):
            raise WorkflowError("Provide a display name without control characters")
        def action(db, body):
            self._owner(body, token, version)
            if body["state"] != "customer_confirmed":
                raise WorkflowError("This owner review was already answered")
            body["owner_confirmation"] = {"version": version, "sha256": digest(body["card"]),
                "name": name, "at": now(), "method": "explicit_review_checkbox",
                "identity_verified": False}
            body["state"] = "both_confirmed"
            from .receipt import build_receipt
            receipt = build_receipt(body)
            db.execute("INSERT INTO review_receipts VALUES(?,?,?)",
                       (session_id, version, json.dumps(receipt, ensure_ascii=False)))
            self.event(db, session_id, "owner_accepted", {"version": version,
                       "receipt_id": receipt["receipt_id"], "name": name})
        return self._mutate(session_id, action)

    def owner_request_change(self, session_id, token, version, note):
        note = note.strip()
        if not 1 <= len(note) <= 2000:
            raise WorkflowError("Explain the requested change in 1–2000 characters")
        def action(db, body):
            self._owner(body, token, version)
            if body["state"] != "customer_confirmed":
                raise WorkflowError("This owner review was already answered")
            body["state"] = "owner_changes_requested"
            body["owner_change_request"] = {"version": version, "text": note, "at": now()}
            self.event(db, session_id, "owner_requested_change", body["owner_change_request"])
        return self._mutate(session_id, action)

    def receipt(self, session_id, version=None, expected_version=None):
        with self.connect() as db:
            body = self._read(db, session_id)
            if expected_version is not None:
                self.expected(body, expected_version)
            if version is None:
                if body["state"] != "both_confirmed":
                    raise WorkflowError("Both parties must approve the current version before export")
                version = body["version"]
            row = db.execute("SELECT body FROM review_receipts WHERE session_id=? AND version=?",
                             (session_id, version)).fetchone()
            if row is None:
                raise WorkflowError("No shared receipt exists for this version")
            receipt = json.loads(row[0])
            from .receipt import verify_receipt
            verify_receipt(receipt)
            return receipt
