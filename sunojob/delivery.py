"""Persisted previews, recipient outcomes and duplicate-resistant submission."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid

from .mailer import message_subject, submission_message
from .receipt import HTML_PRESENTATION_VERSION, email_address, receipt_html, receipt_json, verify_receipt
from .workflow import WorkflowError, now


STATES = {"accepted_by_smtp", "rejected", "failed_before_submission", "unknown", "not_attempted"}


def address(value):
    local, domain = email_address(value).rsplit("@", 1)
    return local + "@" + domain.lower()


class DeliveryManager:
    def __init__(self, store, mailer=None):
        self.store, self.mailer = store, mailer
        with store.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS review_mail_jobs(id TEXT PRIMARY KEY, session_id TEXT,
                version INTEGER, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS review_mail_targets(receipt_id TEXT, role TEXT,
                address TEXT, body TEXT NOT NULL, PRIMARY KEY(receipt_id,role,address));
            """)

    def _job(self, db, sid, job_id):
        row = db.execute("SELECT body FROM review_mail_jobs WHERE id=? AND session_id=?", (job_id, sid)).fetchone()
        if not row:
            raise WorkflowError("Email preview not found")
        return json.loads(row[0])

    def _save(self, db, job):
        db.execute("UPDATE review_mail_jobs SET body=? WHERE id=?", (json.dumps(job, ensure_ascii=False), job["id"]))

    def _receipt(self, db, body, version):
        self.store.expected(body, version)
        if body["state"] != "both_confirmed":
            raise WorkflowError("Both parties must approve this current version before emailing it")
        row = db.execute("SELECT body FROM review_receipts WHERE session_id=? AND version=?",
                         (body["id"], version)).fetchone()
        if not row:
            raise WorkflowError("Shared receipt is missing")
        receipt = json.loads(row[0]); verify_receipt(receipt)
        return receipt

    def prepare(self, sid, version, customer_email, owner_email):
        if self.mailer is None:
            raise WorkflowError("SMTP is not configured. Restart with --email or download the drafts")
        targets = [{"role": role, "address": address(value)} for role, value in
                   [("customer", customer_email), ("owner", owner_email)]]
        result = {}
        def action(db, body):
            if body.get("delivery_in_progress"):
                raise WorkflowError("Another email submission is still running")
            receipt = self._receipt(db, body, version)
            job_id = uuid.uuid4().hex
            for target in targets:
                target.update(status="prepared", message_id=f"<sunojob.{job_id}.{target['role']}@{self.mailer.sender.rsplit('@',1)[1]}>")
                previous = db.execute("SELECT body FROM review_mail_targets WHERE receipt_id=? AND role=? AND address=?",
                                      (receipt["receipt_id"], target["role"], target["address"])).fetchone()
                if previous:
                    status = json.loads(previous[0])["status"]
                    if status in {"accepted_by_smtp", "unknown", "reserved", "submitting"}:
                        target["detail"] = "Previous outcome: " + status + ". This copy will not be automatically resent."
            attachments = [{"filename": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                           for name, data in [("shared-record.html", receipt_html(receipt)),
                                              ("shared-record.json", receipt_json(receipt))]]
            job = {"id": job_id, "session_id": sid, "version": version, "state": "prepared",
                   "receipt_id": receipt["receipt_id"], "receipt_sha256": receipt["receipt_sha256"],
                   "html_presentation_version": HTML_PRESENTATION_VERSION,
                   "sender": self.mailer.sender, "subject": message_subject(receipt),
                   "created_at": now(), "expires_at": (datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat(),
                   "attachments": attachments, "targets": targets}
            # Validate MIME construction and total size before saving a preview.
            for target in targets:
                submission_message(receipt, job["sender"], target, job["created_at"])
            db.execute("INSERT INTO review_mail_jobs VALUES(?,?,?,?)",
                       (job_id, sid, version, json.dumps(job, ensure_ascii=False)))
            self.store.event(db, sid, "email_preview_prepared", {"job_id": job_id, "version": version})
            result.update(job)
        self.store._mutate(sid, action)
        return result

    def get(self, sid, job_id):
        with self.store.connect() as db:
            return self._job(db, sid, job_id)

    def recent(self, sid):
        self.store.get(sid)
        with self.store.connect() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT body FROM review_mail_jobs WHERE session_id=? ORDER BY rowid DESC LIMIT 20", (sid,))]

    def _target_key(self, job, target):
        return (job["receipt_id"], target["role"], target["address"])

    def _target_save(self, db, job, target):
        db.execute("INSERT OR REPLACE INTO review_mail_targets VALUES(?,?,?,?)",
                   (*self._target_key(job, target), json.dumps(target, ensure_ascii=False)))

    def send(self, sid, job_id, confirmed):
        if confirmed is not True:
            raise WorkflowError("Review both recipients and explicitly choose Send to both")
        if self.mailer is None:
            raise WorkflowError("SMTP is not configured")
        claim = {}
        def action(db, body):
            job = self._job(db, sid, job_id)
            if job["state"] != "prepared":
                claim.update(job=job, run=False)
                return
            if body.get("delivery_in_progress"):
                raise WorkflowError("Another email submission is still running")
            if now() > job["expires_at"]:
                raise WorkflowError("Email preview expired. Review a fresh preview before sending")
            if job["sender"] != self.mailer.sender:
                raise WorkflowError("Sender changed. Prepare a fresh preview")
            receipt = self._receipt(db, body, job["version"])
            if job["receipt_sha256"] != receipt["receipt_sha256"]:
                raise WorkflowError("Preview does not match the saved receipt")
            expected_attachments = [{"filename": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                                    for name, data in [("shared-record.html", receipt_html(receipt)),
                                                       ("shared-record.json", receipt_json(receipt))]]
            if (job.get("html_presentation_version") != HTML_PRESENTATION_VERSION
                    or job["attachments"] != expected_attachments):
                raise WorkflowError("Receipt layout changed. Prepare and review a fresh email preview before sending.")
            for target in job["targets"]:
                row = db.execute("SELECT body FROM review_mail_targets WHERE receipt_id=? AND role=? AND address=?",
                                 self._target_key(job, target)).fetchone()
                previous = json.loads(row[0]) if row else None
                if previous and previous["status"] in {"accepted_by_smtp", "unknown", "submitting", "reserved"}:
                    target.update(previous)
                    if target["status"] in {"submitting", "reserved"}:
                        target.update(status="unknown", detail="A prior submission has no final result; check the mailbox before any manual resend")
                else:
                    target.update(status="reserved", job_id=job_id, detail="Queued for one submission attempt")
                    self._target_save(db, job, target)
            job["state"] = "sending"
            body["delivery_in_progress"] = job_id
            self._save(db, job)
            self.store.event(db, sid, "email_send_requested", {"job_id": job_id, "version": job["version"]})
            claim.update(job=job, receipt=receipt, run=True)
        self.store._mutate(sid, action)
        if not claim["run"]:
            return claim["job"]
        job, receipt = claim["job"], claim["receipt"]
        for index, target in enumerate(job["targets"]):
            if target["status"] != "reserved":
                continue
            try:
                message = submission_message(receipt, job["sender"], target, job["created_at"])
            except Exception:
                # No SMTP call has begun for this recipient. Save a known failure
                # and continue so the request is never left locked in sending.
                target.update(status="failed_before_submission", finished_at=now(),
                              detail="Email could not be prepared; no submission was made for this recipient")
                with self.store.connect() as db:
                    self._target_save(db, job, target)
                    self._save(db, job)
                continue
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                target.update(status="submitting", attempted_at=now())
                self._target_save(db, job, target)
                self._save(db, job)
            try:
                outcome = self.mailer.submit(message, target["address"])
                if outcome.get("status") not in STATES:
                    raise ValueError("Invalid mail outcome")
            except Exception:
                # Unexpected failures cannot safely prove the SMTP server did
                # not accept the message. Raw errors/credentials are never saved.
                outcome = {"status": "unknown", "detail": "Unexpected submission failure; outcome is uncertain"}
            target.update(outcome, finished_at=now())
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self._target_save(db, job, target)
                self._save(db, job)
        def finish(db, body):
            job["state"] = "complete" if all(t["status"] == "accepted_by_smtp" for t in job["targets"]) else "complete_with_errors"
            job["finished_at"] = now()
            self._save(db, job)
            if body.get("delivery_in_progress") == job_id:
                body["delivery_in_progress"] = None
            self.store.event(db, sid, "email_submission_finished", {"job_id": job_id,
                             "outcomes": [t["status"] for t in job["targets"]]})
        self.store._mutate(sid, finish)
        return job

    def recover_interrupted(self):
        with self.store.connect() as db:
            rows = [(row[0], row[1]) for row in db.execute("SELECT id,session_id,body FROM review_mail_jobs")
                    if json.loads(row[2])["state"] == "sending"]
        for job_id, sid in rows:
            def recover(db, body):
                job = self._job(db, sid, job_id)
                for target in job["targets"]:
                    if target["status"] == "submitting":
                        target.update(status="unknown", detail="Server stopped during SMTP submission; check mailbox before any manual resend")
                    elif target["status"] == "reserved":
                        target.update(status="not_attempted", detail="Server stopped before submission began")
                    self._target_save(db, job, target)
                job.update(state="interrupted", finished_at=now())
                self._save(db, job)
                if body.get("delivery_in_progress") == job_id:
                    body["delivery_in_progress"] = None
                self.store.event(db, sid, "email_submission_interrupted", {"job_id": job_id})
            self.store._mutate(sid, recover)
