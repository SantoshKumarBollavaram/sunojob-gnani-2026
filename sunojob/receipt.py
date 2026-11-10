"""Saved agreement snapshots and portable email drafts; no messages are sent."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import SMTP
from html import escape
import io
import json
from pathlib import Path
import re
import uuid
import zipfile

from .workflow import WorkflowError, digest


LIMITATION = ("Local prototype record. Display names and identities are not verified. "
              "Approval records refer only to the stated card version. This is not a digital "
              "signature or a guarantee of legal enforceability. Later changes require fresh approval.")

HTML_PRESENTATION_VERSION = 2
INDIA_TIME = timezone(timedelta(hours=5, minutes=30), name="IST")


def display_time(value):
    """Format an existing aware instant; never relabel a clock time as local."""
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            return "Time unavailable"
        return parsed.astimezone(INDIA_TIME).strftime("%d %b %Y · %I:%M:%S %p IST")
    except (ValueError, TypeError):
        return "Time unavailable"


def subject_label(value):
    return {"lunch_boxes": "Lunch boxes", "menu_change": "Menu changes", "onion": "Onion"}.get(
        value, value.replace("_", " ").capitalize())


def instruction_text(item):
    known = {("task", "lunch_boxes", "prepare"): "Prepare lunch boxes",
             ("prohibition", "onion", "exclude"): "Do not add onion",
             ("permission_required", "menu_change", "ask_first"): "Ask before changing the menu"}
    key = (item["kind"], item["subject"], item["value"])
    if key in known:
        return known[key]
    if item["kind"] == "quantity" and item["subject"] == "lunch_boxes":
        return item["value"] + " lunch boxes"
    # Unknown domains retain their exact value and supporting wording.
    return subject_label(item["subject"]) + ": " + item["value"]


def build_receipt(body):
    receipt = {"schema_version": 1, "receipt_id": uuid.uuid4().hex,
               "session_id": body["id"], "version": body["version"],
               "status": "both_confirmed", "card_sha256": digest(body["card"]),
               "card": deepcopy(body["card"]),
               "customer_readback": deepcopy(body["readback"]),
               "customer_confirmation": deepcopy(body["customer_confirmation"]),
               "owner_confirmation": deepcopy(body["owner_confirmation"]),
               "issued_at": body["owner_confirmation"]["at"], "limitations": LIMITATION}
    receipt["receipt_sha256"] = digest(receipt)
    verify_receipt(receipt)
    return receipt


def verify_receipt(receipt):
    unsigned = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    if receipt.get("receipt_sha256") != digest(unsigned) or digest(receipt["card"]) != receipt["card_sha256"]:
        raise WorkflowError("Receipt failed its integrity check")
    for role in ("customer_confirmation", "owner_confirmation"):
        approval = receipt[role]
        if not approval or approval["version"] != receipt["version"] or approval["sha256"] != receipt["card_sha256"]:
            raise WorkflowError("Receipt approvals do not match the card version")


def receipt_json(receipt):
    verify_receipt(receipt)
    return (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def receipt_html(receipt, archived=False):
    verify_receipt(receipt)
    e = lambda value: escape(str(value), quote=True)
    extraction = receipt["card"]["extraction"]
    instructions = extraction["instructions"]
    labels = {"task": "Task", "quantity": "Quantity", "prohibition": "Do not",
              "permission_required": "Ask first", "deadline": "Time requirement",
              "budget": "Budget", "constraint": "Condition"}
    order = {kind: index for index, kind in enumerate(labels)}

    def instruction_card(item):
        quotes = "".join(f'<div class="source"><span>Source · {e(ref["turn_id"])}</span>'
                         f'<blockquote dir="auto">“{e(ref["quote"])}”</blockquote></div>'
                         for ref in item["evidence"])
        return (f'<article class="instruction {e(item["kind"])}"><span class="kind">{labels[item["kind"]]}</span>'
                f'<h3>{e(instruction_text(item))}</h3>{quotes}</article>')

    ordered = sorted(instructions, key=lambda item: order[item["kind"]])
    work = "".join(instruction_card(item) for item in ordered if item["kind"] in {"task", "quantity", "deadline"})
    rules = "".join(instruction_card(item) for item in ordered if item["kind"] not in {"task", "quantity", "deadline"})
    instruction_by_id = {item["id"]: item for item in instructions}
    changes = []
    for correction in extraction["corrections"]:
        item = instruction_by_id[correction["instruction_id"]]
        quotes = "".join(f'<blockquote dir="auto">“{e(ref["quote"])}”</blockquote>' for ref in correction["evidence"])
        changes.append(f'<article class="change"><h3>{e(subject_label(item["subject"]))}</h3>'
                       f'<p class="change-values"><span>{e(correction["before"])}</span><b aria-label="changed to">→</b>'
                       f'<strong>{e(correction["after"])}</strong></p>{quotes}</article>')
    corrections = "".join(changes) or '<p class="muted">No explicit corrections were recorded in this version.</p>'
    sources = "".join(f'<li><div class="turn-heading"><span class="turn-number">{index:02d}</span>'
                      f'<strong>{e(source["speaker"].capitalize())}</strong><span>{e(source["id"])}</span></div>'
                      f'<p dir="auto">{e(source["text"])}</p></li>'
                      for index, source in enumerate(receipt["card"]["sources"], 1))
    customer, owner = receipt["customer_confirmation"], receipt["owner_confirmation"]
    css = Path(__file__).with_name("receipt.css").read_text(encoding="utf-8")
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>SunoJob · Shared record · Version {e(receipt["version"])}</title>
<style>{css}</style></head><body><main class="document">
<header><div class="brand">Suno<span>Job</span></div><span class="document-label">SHARED INSTRUCTION RECORD</span>
<h1>Your instructions,<br>recorded together.</h1>
<p class="intro">The instructions and source wording approved by the customer and owner for this version.</p>
<div class="approved"><span class="status-dot" aria-hidden="true"></span><div><strong>Both parties approved version {e(receipt["version"])}</strong>
<p>Customer confirmation and separate owner acceptance are recorded below.</p></div></div>
<dl class="record-meta"><div><dt>Record reference</dt><dd>{e(receipt["receipt_id"][:8])} · Version {e(receipt["version"])}</dd></div>
<div><dt>Record issued</dt><dd>{e(display_time(receipt["issued_at"]))}</dd></div></dl>
<p class="timezone-note">All displayed times are India Standard Time (IST, +05:30).</p></header>
<section><div class="section-heading"><span>01</span><h2>Approved instructions</h2></div>
<p class="section-description">Read the source wording with each instruction; it may include an exception or condition.</p>
{('<h3 class="group-label">Work to carry out</h3><div class="instruction-list">' + work + '</div>') if work else ''}
{('<h3 class="group-label">Rules and boundaries</h3><div class="instruction-list">' + rules + '</div>') if rules else ''}
{('<p class="muted">No active instructions were recorded.</p>') if not instructions else ''}</section>
<section><div class="section-heading"><span>02</span><h2>Recorded corrections</h2></div>
<p class="section-description">Net changes from the earlier stated value to the approved value. Intermediate changes remain in the conversation history.</p>
<div class="changes">{corrections}</div></section>
<section><div class="section-heading"><span>03</span><h2>Approval records</h2></div>
<div class="approval-grid"><article class="approval"><span class="kind">Customer confirmation</span>
<h3>“{e(customer["reply"])}”</h3><p>{e(display_time(customer["at"]))}</p>
<span class="approval-version">Approved version {e(customer["version"])}</span><p class="small muted">Customer identity is not verified.</p></article>
<article class="approval"><span class="kind">Owner acceptance</span><h3>{e(owner["name"])}</h3>
<p>{e(display_time(owner["at"]))}</p><span class="approval-version">Accepted version {e(owner["version"])}</span>
<p class="small muted">Owner display name is unverified.</p></article></div></section>
<section><div class="section-heading"><span>04</span><h2>Conversation history</h2></div>
<p class="section-description">Original transcript turns in order, including earlier requests and later corrections.</p>
<ol class="timeline">{sources}</ol></section>
<details class="record-details"><summary>Record details and integrity references</summary>
<dl><dt>Full record ID</dt><dd><code>{e(receipt["receipt_id"])}</code></dd>
<dt>Request ID</dt><dd><code>{e(receipt["session_id"])}</code></dd>
<dt>Card SHA-256</dt><dd><code>{e(receipt["card_sha256"])}</code></dd>
<dt>Receipt SHA-256</dt><dd><code>{e(receipt["receipt_sha256"])}</code></dd></dl>
<p class="small muted">The companion JSON contains the original timestamps and evidence. Both parties receive the same record contents.</p></details>
<footer><strong>About this record</strong><p>{e(LIMITATION)}</p>
<p>This snapshot refers to the version above. A later change requires fresh approval. Source wording is retained for review.</p>
<span class="footer-brand">SunoJob · Speak. Review. Confirm.</span></footer></main></body></html>'''
    if archived:
        banner = ('<aside class="approved"><div><strong>Archived approval snapshot</strong>'
                  '<p>This records approval at the stated time. It does not approve a current '
                  'pending correction or later version. Check the current request before starting work.</p></div></aside>')
        html = html.replace('<main class="document">', '<main class="document">' + banner, 1)
    return html.encode()


def email_address(value):
    value = value.strip()
    if (len(value) > 254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}", value)
            or ".." in value or value.startswith(".") or ".@" in value):
        raise ValueError("Use a plain email address, without a display name or newline")
    return value


def email_drafts(receipt, customer_email, owner_email):
    """Two addressed .eml drafts with byte-identical HTML and JSON attachments."""
    addresses = [email_address(customer_email), email_address(owner_email)]
    html, data = receipt_html(receipt), receipt_json(receipt)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("shared-record.html", html)
        archive.writestr("shared-record.json", data)
        for role, address in zip(("customer", "owner"), addresses):
            message = EmailMessage(policy=SMTP)
            message["To"] = address
            message["Subject"] = f"SunoJob shared record — version {receipt['version']} — {receipt['receipt_id'][:8]}"
            message["X-Unsent"] = "1"
            message.set_content(f"Both parties approved version {receipt['version']} at the recorded timestamps.\n"
                                f"Record ID: {receipt['receipt_id']}\nCard SHA-256: {receipt['card_sha256']}\n\n"
                                "The attached shared record is identical in the customer and owner drafts.\n\n"
                                + LIMITATION + "\n\nThis is an unsent draft. Choose your sender account, review the recipient and send it manually.\n")
            message.add_attachment(html, maintype="text", subtype="html", filename="shared-record.html")
            message.add_attachment(data, maintype="application", subtype="json", filename="shared-record.json")
            archive.writestr(role + "-draft.eml", message.as_bytes())
        archive.writestr("READ-ME.txt", "No messages have been sent.\nOpen each .eml in a mail client that supports editing drafts, select a sender account and review before sending.\nAlternatively attach shared-record.html and shared-record.json in your normal email app.\nRecipient addresses are not verified by SunoJob.\n")
    return output.getvalue()
