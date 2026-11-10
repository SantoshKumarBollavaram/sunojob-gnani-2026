# SunoJob — Speak. Review. Confirm.

**Submission pitch: [PITCH.pdf](PITCH.pdf) (one page).**
Plain-text version: [PITCH.md](PITCH.md). Recording narration:
[VIDEO_SCRIPT.md](VIDEO_SCRIPT.md) (2-3 minute submission video).

SunoJob turns spoken work instructions into a reviewable job card, reads it
back, accepts corrections, and saves a shared record after customer confirmation
and separate owner acceptance. The current local prototype supports English and
Telugu + English. Catering is the demonstration scenario, rather than a claim of
validated use across industries.

## Why this exists

Spoken requests can contain changing quantities, restrictions and conditions.
A transcript alone does not establish what both parties accepted. SunoJob makes
the current interpretation visible and requires fresh approvals when it changes.
For example: “Prepare fifty, actually forty lunch boxes. Do not add onion. Ask
before changing the menu.” The expected draft has quantity 40, an onion exclusion
and a permission requirement. A later correction to 45 must preserve both
restrictions and require a new readback and approvals.

## Implemented workflow

1. Record or upload a short request, or use the explicitly labelled text input.
2. Transcribe speech with Gnani Prisma and extract a structured draft with Gemini.
3. Validate its structure and source references; display unresolved questions.
4. Generate spoken readback with Gnani Timbre and listen before responding.
5. Apply a correction or confirm the current version through the voice loop.
6. Open a separate, expiring local owner-review link and accept that version.
7. Download matching HTML/JSON records, or preview and explicitly email copies.
8. Reopen saved requests, earlier approval snapshots and email submission history.

Source quotes and validation improve traceability; they do not guarantee that
the model interpreted the request correctly. Human review remains necessary.

## Technology actually used

| Component | Implementation |
| --- | --- |
| Speech recognition | Gnani Prisma, request model `prisma-v3.0`, `https://api.vachana.ai/stt/v3` |
| Spoken readback | Gnani Timbre, request model `timbre-v2.5`, `https://api.vachana.ai/api/v1/tts/inference` |
| Structured extraction | Google Gemini, configured model `gemini-3.5-flash-lite` |
| Application | Python, FastAPI, Uvicorn, Pydantic, SQLite, HTML/CSS/JavaScript |
| Audio conversion | FFmpeg |
| Optional delivery | TLS SMTP with per-recipient results and duplicate-send protection |

These are the identifiers in this checkpoint, not inferred marketing versions.
Evon is not integrated. API availability depends on the provider and account.
Credentials are read from hidden terminal prompts or environment variables.

## Setup on Ubuntu

Use Python 3.12 (the development environment). Install system tools if absent:

```bash
sudo apt-get update
sudo apt-get install -y python3.12-venv ffmpeg
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-voice.txt
.venv/bin/python -m unittest discover -s tests -q
```

Start the live app:

```bash
.venv/bin/python -m sunojob.serve --model gemini-3.5-flash-lite
```

Enter your own Gnani and Gemini keys at the hidden prompts. Open
http://127.0.0.1:8765 and allow microphone access when recording.
The live flow uses provider credits. The test suite uses offline doubles.

For optional live email:

```bash
.venv/bin/python -m sunojob.serve --model gemini-3.5-flash-lite --email
```

For Gmail, use host `smtp.gmail.com`, port `587`, TLS `starttls`, your full sender
address as the username, and an app password for that same account. Never commit
credentials. Startup does not send mail. Sending requires a reviewed preview
and an explicit click. Both recipients must be intended test recipients.

## Tests and scope of evidence

The submission source passed **236 offline Python tests** again on 10 November
2026. Tests cover application state, source-reference validation, corrections,
approval invalidation, saved receipts, email failure handling and persistence.
They are not a natural-speech accuracy benchmark. See `VERIFICATION.md`.

The builder has reported successful English/Telugu examples and email arrival
in both controlled inboxes. A representative, independently labelled speech
evaluation and uncoached customer trial have not been completed. No measured
real-world accuracy, latency or business impact is claimed.

## Important operating limits

- Local prototype bound to `127.0.0.1`; no hosted public application is included.
- Owner review runs on the same laptop. Names and links do not verify identity.
- Spoken request clips must be between 0.1 and 25 seconds.
- A later correction invalidates current approvals. Historical receipts remain
  historical; opening one does not approve the current state.
- SMTP acceptance is not proof of inbox delivery. Inspect the actual inboxes.
- Transcripts, audio and review records are persisted locally under `.local/`.
  Speech and transcript content are sent to the configured external providers.
- This is not a digital-signature or legally verified contracting system.

## Code map

| File | Purpose |
| --- | --- |
| `sunojob/speech.py` | Gnani speech adapters and live extraction integration |
| `sunojob/providers.py` | Gemini schema, prompt and request handling |
| `sunojob/validation.py` | Card validation and source references |
| `sunojob/workflow.py` | Versions, readback, confirmations and SQLite state |
| `sunojob/webapp.py` | Local HTTP application and workflow endpoints |
| `sunojob/delivery.py` | Preview/send lifecycle and stored recipient outcomes |
| `sunojob/receipt.py` | Shared HTML/JSON records |
| `sunojob/checkpoint.py` | Read-only saved-evidence inspection |
| `sunojob/recording_eval.py` | Labelled recording evaluation runner |
| `sunojob/static/` | Customer and owner interfaces |
| `tests/` | Offline regression tests |

## Submission materials

`SUBMISSION_TEXT.md` contains portal answers, `DEMO_GUIDE.md` contains the
recording sequence, and `SOCIAL_POST.md` contains a public-post draft.
`SUBMIT_TONIGHT.md` contains the deadline checklist and GitHub commands.
Earlier checkpoint guides remain available for detailed troubleshooting.

## Contribution

Santosh Kumar Bollavaram — solo project contributor responsible for the product
idea, application integration, local testing and submission. AI coding tools
assisted implementation, debugging, tests and documentation. The project uses
the external models listed above; it does not claim to train those models.

## Successive corrections

See `CORRECTION_FIX_README.md`. Inconsistent correction output can trigger one
additional model generation, which must pass the same strict validation.
Both rejected and recovered candidates are retained in local attempt reports.
Live recovery on the builder's laptop still needs verification.
