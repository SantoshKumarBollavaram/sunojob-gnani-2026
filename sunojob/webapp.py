"""Local customer/owner review loop with optional, explicitly requested email."""

import base64
import hashlib
from pathlib import Path
import secrets
import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .models import SourceTurn, StrictModel
from .providers import ProviderError
from .readback import readback_text
from .receipt import receipt_json, receipt_html, email_drafts, email_address
from .delivery import DeliveryManager
from .workflow import ReviewStore, WorkflowError, reply_kind


STATIC = Path(__file__).with_name("static")


class TextInput(StrictModel):
    text: str = Field(min_length=1, max_length=20000)
    language: str = "en-IN"


class AudioInput(StrictModel):
    audio: str = Field(min_length=1, max_length=5_500_000)
    language: str = "en-IN"


class VersionInput(StrictModel):
    version: int


class CompletionInput(VersionInput):
    readback_id: str


class ReplyInput(CompletionInput):
    audio: str = Field(min_length=1, max_length=5_500_000)


class CorrectionInput(VersionInput):
    text: str = Field(min_length=1, max_length=20000)


class VoiceCorrectionInput(VersionInput):
    audio: str = Field(min_length=1, max_length=5_500_000)


class OwnerAcceptance(VersionInput):
    name: str = Field(min_length=1, max_length=120)
    reviewed: bool


class OwnerChange(VersionInput):
    note: str = Field(min_length=1, max_length=2000)


class DraftEmails(VersionInput):
    customer_email: str = Field(min_length=1, max_length=254)
    owner_email: str = Field(min_length=1, max_length=254)

    @field_validator("customer_email", "owner_email")
    @classmethod
    def validate_recipient(cls, value, info):
        label = "Customer email" if info.field_name == "customer_email" else "Owner email"
        try:
            return email_address(value)
        except ValueError:
            raise ValueError(f"{label}: enter a plain email address, such as name@example.com") from None


class SendEmails(StrictModel):
    preview_id: str = Field(min_length=32, max_length=32)
    reviewed_recipients: bool


def create_app(store, services, mailer=None):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = secrets.token_urlsafe(32)
    delivery = DeliveryManager(store, mailer)
    app.state.delivery = delivery
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        if request.method == "POST":
            supplied = request.headers.get("x-sunojob-token", "")
            if not secrets.compare_digest(supplied, app.state.token):
                return JSONResponse({"detail": "Reload the page before continuing"}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
            length = request.headers.get("content-length", "0")
            if not length.isdigit() or int(length) > 6_000_000:
                return JSONResponse({"detail": "Request is too large"}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(WorkflowError)
    async def workflow_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.exception_handler(ValueError)
    async def input_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        labels = {"customer_email": "Customer email", "owner_email": "Owner email",
                  "version": "Card version", "preview_id": "Email preview",
                  "reviewed_recipients": "Recipient review"}
        messages = []
        for error in exc.errors():
            field = error["loc"][-1] if error["loc"] else None
            label = labels.get(field, "Request field")
            if field in {"customer_email", "owner_email"}:
                message = (f"{label} is required." if error["type"] in {"missing", "string_too_short"}
                           else f"{label}: enter a plain email address, such as name@example.com.")
            elif field in labels:
                message = f"{label} is missing or invalid. Refresh the page and try again."
            else:
                message = "A request field is missing or invalid. Check your entries and try again."
            if message not in messages:
                messages.append(message)
        # Do not echo input values, transcripts, credentials or validation context.
        return JSONResponse({"detail": " ".join(messages)}, status_code=422)

    @app.get("/", response_class=HTMLResponse)
    def home():
        return STATIC.joinpath("index.html").read_text().replace("__CSRF_TOKEN__", app.state.token)

    @app.get("/favicon.ico")
    def favicon():
        return Response(status_code=204)

    @app.get("/owner/{sid}", response_class=HTMLResponse)
    def owner_page(sid: str):
        if not re.fullmatch(r"[a-f0-9]{32}", sid):
            return HTMLResponse("Invalid review URL", status_code=404)
        return STATIC.joinpath("owner.html").read_text().replace("__CSRF_TOKEN__", app.state.token).replace("__SESSION_ID__", sid)

    @app.get("/api/status")
    def status():
        return {"mode": services.mode, "model": services.model, "owner_flow": "local_review",
                "email_delivery": "smtp_configured" if mailer else "unsent_drafts_only",
                "email_sender": mailer.sender if mailer else None}

    @app.get("/api/sessions")
    def sessions():
        return store.recent()

    @app.get("/api/sessions/{sid}")
    def session(sid: str):
        return store.get(sid, include_activity=True)

    def new_session(text, language, provenance):
        if language not in {"en-IN", "te-IN"}:
            raise ValueError("Choose English or Telugu")
        sources = [SourceTurn(id="turn-1", text=text, language=language)]
        extraction, meta = services.extract(sources)
        return store.create(sources, extraction, language, {**provenance, **meta})

    @app.post("/api/sessions/text")
    def create_text(body: TextInput):
        return new_session(body.text, body.language, {"origin": "typed"})

    @app.post("/api/sessions/voice")
    def create_voice(body: AudioInput):
        if body.language not in {"en-IN", "te-IN"}:
            raise ValueError("Choose English or Telugu")
        text, provenance = services.transcribe(body.audio, body.language)
        return new_session(text, body.language, provenance)

    @app.post("/api/sessions/{sid}/readback")
    def prepare(sid: str, body: VersionInput):
        current = store.get(sid)
        store.expected(current, body.version)
        text = readback_text(current["card"], current["language"])
        prepared = store.prepare_readback(sid, body.version, text)
        audio = services.synthesize(text, current["language"])
        rb = prepared["readback"]
        result = store.ready_readback(sid, body.version, rb["id"], hashlib.sha256(audio).hexdigest())
        return {"session": result, "audio": base64.b64encode(audio).decode(), "text": text}

    @app.post("/api/sessions/{sid}/readback-complete")
    def complete(sid: str, body: CompletionInput):
        return store.complete_readback(sid, body.version, body.readback_id)

    def apply_change(sid, version, text, provenance, token=None):
        if reply_kind(text) in {"confirm", "reject"}:
            raise WorkflowError("Listen to the readback to confirm, or explain what should change")
        pending = store.start_change(sid, version, text, token=token, provenance=provenance)
        operation = pending["operation"]
        try:
            sources = [SourceTurn.model_validate(s) for s in pending["card"]["sources"]]
            sources.append(SourceTurn(id=f"turn-{len(sources) + 1}", text=text, language=pending["language"]))
            extraction, meta = services.extract(sources)
            result = store.finish_change(sid, version, operation, sources, extraction)
            return result
        except Exception:
            store.fail_change(sid, operation)
            raise

    @app.post("/api/sessions/{sid}/reply-voice")
    def reply(sid: str, body: ReplyInput):
        current = store.can_reply(sid, body.version, body.readback_id)
        text, meta = services.transcribe(body.audio, current["language"])
        if reply_kind(text) == "change":
            result = apply_change(sid, body.version, text, meta, token=body.readback_id)
        else:
            result = store.reply(sid, body.version, body.readback_id, text, meta)
        return {"session": result, "reply_transcript": text}

    @app.post("/api/sessions/{sid}/correct-text")
    def correct_text(sid: str, body: CorrectionInput):
        return apply_change(sid, body.version, body.text, {"origin": "typed"})

    @app.post("/api/sessions/{sid}/correct-voice")
    def correct_voice(sid: str, body: VoiceCorrectionInput):
        current = store.get(sid)
        store.expected(current, body.version)
        text, meta = services.transcribe(body.audio, current["language"])
        return {"session": apply_change(sid, body.version, text, meta), "reply_transcript": text}

    @app.post("/api/sessions/{sid}/owner-link")
    def owner_link(sid: str, body: VersionInput):
        invitation = store.issue_owner_review(sid, body.version)
        return {"path": f"/owner/{sid}#" + invitation["token"],
                "version": invitation["version"], "expires_at": invitation["expires_at"]}

    @app.get("/api/owner/{sid}")
    def owner_session(sid: str, request: Request):
        return store.owner_view(sid, request.headers.get("x-owner-token", ""))

    @app.post("/api/owner/{sid}/accept")
    def owner_accept(sid: str, body: OwnerAcceptance, request: Request):
        token = request.headers.get("x-owner-token", "")
        store.owner_accept(sid, token, body.version, body.name, body.reviewed)
        return store.owner_view(sid, token)

    @app.post("/api/owner/{sid}/request-change")
    def owner_change(sid: str, body: OwnerChange, request: Request):
        token = request.headers.get("x-owner-token", "")
        store.owner_request_change(sid, token, body.version, body.note)
        return store.owner_view(sid, token)

    def download(receipt, kind):
        if kind not in {"html", "json"}:
            raise ValueError("Choose html or json")
        data = receipt_html(receipt) if kind == "html" else receipt_json(receipt)
        return Response(data, media_type="text/html" if kind == "html" else "application/json",
                        headers={"Content-Disposition": f'attachment; filename="SunoJob-{receipt["receipt_id"][:8]}-v{receipt["version"]}.{kind}"'})

    @app.get("/api/sessions/{sid}/receipt")
    def customer_receipt(sid: str, version: int, kind: str = "html"):
        return download(store.receipt(sid, expected_version=version), kind)

    @app.get("/api/sessions/{sid}/receipts")
    def receipt_history(sid: str):
        return store.receipt_history(sid)

    @app.get("/api/sessions/{sid}/receipts/{version}")
    def saved_receipt(sid: str, version: int, kind: str = "html"):
        snapshots = store.receipt_history(sid)
        snapshot = next((item for item in snapshots if item["version"] == version), None)
        if snapshot is None:
            raise WorkflowError("No approved snapshot exists for that version")
        receipt = store.receipt(sid, version=version)
        response = download(receipt, kind)
        # This route is explicitly an archive. It never approves current work.
        response.headers["Content-Disposition"] = (
            f'attachment; filename="SunoJob-Archived-{receipt["receipt_id"][:8]}-v{version}.{kind}"')
        if kind == "html":
            response = Response(receipt_html(receipt, archived=True), media_type="text/html",
                                headers={"Content-Disposition": response.headers["Content-Disposition"]})
        return response

    @app.get("/api/owner/{sid}/receipt")
    def owner_receipt(sid: str, request: Request, version: int, kind: str = "html"):
        body = store.owner_view(sid, request.headers.get("x-owner-token", ""))
        store.expected(body, version)
        return download(store.receipt(sid, expected_version=version), kind)

    @app.post("/api/sessions/{sid}/email-drafts")
    def drafts(sid: str, body: DraftEmails):
        data = email_drafts(store.receipt(sid, expected_version=body.version), body.customer_email, body.owner_email)
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="SunoJob-unsent-email-drafts.zip"'})

    @app.post("/api/sessions/{sid}/email-preview")
    def email_preview(sid: str, body: DraftEmails):
        return delivery.prepare(sid, body.version, body.customer_email, body.owner_email)

    @app.post("/api/sessions/{sid}/send-emails")
    def send_emails(sid: str, body: SendEmails):
        return delivery.send(sid, body.preview_id, body.reviewed_recipients)

    @app.get("/api/sessions/{sid}/email-jobs")
    def email_jobs(sid: str):
        return delivery.recent(sid)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
