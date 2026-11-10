> Historical checkpoint. For the current email-enabled build, follow EMAIL_DELIVERY_README.md.

# SunoJob: owner review and shared-record checkpoint

This is the current checkpoint. `VOICE_WORKFLOW_README.md` and earlier fix
readmes describe previous checkpoints; follow the upgrade and acceptance
instructions here for this version.

## What is ready

- Existing customer recording, Gnani Prisma transcription, Gemini extraction,
  deterministic Timbre readback and spoken confirmation remain available.
- A customer-confirmed version can be opened on a separate owner review page.
- The owner reviews the exact card, supplies an unverified display name and
  explicitly accepts it, or requests a change instead.
- Both approvals must reference the same version and card SHA-256 before a
  shared record is issued.
- Customer and owner can download byte-identical HTML and JSON records.
- A ZIP of two addressed, unsent `.eml` drafts contains identical record
  attachments for each party. No SMTP connection or email sending occurs.
- Later corrections clear current approvals and revoke the owner link. Saved
  older receipts remain historical snapshots; they are not current approvals.
- The lingering “Recording…” label is fixed, and the favicon route is handled.

English customer recording, corrections, readback and confirmation were checked
by the user before this upgrade. Telugu remains deferred. The user's later
Telugu attempt displayed Gemini HTTP 503 and did not complete extraction;
that attempt is not a successful Telugu browser result.

## Install safely

Stop the running development server using `Ctrl+C` in its terminal first.
Download `SunoJob_Owner_Receipt_Checkpoint.zip` into `~/Downloads`, then run:

```bash
bash <<'BASH'
set -eu
cd "$HOME/sunojob"
test -f "$HOME/Downloads/SunoJob_Owner_Receipt_Checkpoint.zip"
mkdir -p .local/backups
sunojob_owner_backup="$(mktemp -d .local/backups/owner-receipt-XXXXXX)"
for path in sunojob scripts tests fixtures requirements-core.txt requirements-voice.txt README.md
do
  if [ -e "$path" ]; then
    cp -a "$path" "$sunojob_owner_backup/"
  fi
done
if [ -f .local/reviews.sqlite3 ]; then
  .venv/bin/python - "$sunojob_owner_backup/reviews.sqlite3" <<'PY'
from pathlib import Path
import sqlite3
import sys
with sqlite3.connect(Path('.local/reviews.sqlite3')) as source:
    with sqlite3.connect(sys.argv[1]) as destination:
        source.backup(destination)
PY
fi
.venv/bin/python -m zipfile -e \
  "$HOME/Downloads/SunoJob_Owner_Receipt_Checkpoint.zip" .
.venv/bin/python -m pip install -r requirements-voice.txt
.venv/bin/python -m unittest discover -s tests -q
printf '\nBackup: %s\n' "$sunojob_owner_backup"
BASH
```

Expected: **155 tests, OK**. No new dependencies are required beyond the previous
voice checkpoint. The existing Starlette/httpx deprecation warning can appear.
The new database table is additive; existing sessions and card versions are
retained. The saved database backup allows recovery if needed.

Start in your normal terminal:

```bash
cd "$HOME/sunojob"
.venv/bin/python -m sunojob.serve --model gemini-3.5-flash-lite
```

Enter API keys at hidden prompts, keep the terminal running, and open
**http://127.0.0.1:8765**. Refresh an already open page after restarting.

## Acceptance check: owner approval

You can reuse the English version 3 that you already confirmed. Do not spend
credits repeating the earlier API diagnostics or recording the request again.

1. Open the confirmed request from **Saved requests** if it is not already
   visible. It should still show **Customer confirmed this version**.
2. Under **Owner review**, click **Create owner review link** and then
   **Open owner review**. This opens a separate page on the same laptop.
3. Check the version and all active instructions. Use a clearly fictional
   owner name such as **Demo Owner** during testing.
4. Select **I reviewed every instruction and restriction and accept this exact
   version**, then click **Accept this version**.
5. Expected: **Both parties approved version 3** on the owner page. Download
   its shared record. It should contain 46 lunch boxes, no onion, permission
   required before a menu change, both approval timestamps and version 3.
6. Return to the customer tab. It refreshes when focused; use **Refresh owner
   status** if needed. Expected: **Both parties approved this version · Shared
   record ready**. Download the HTML or JSON here too. The two downloads for
   a given format must match byte for byte.
7. Refresh both pages. The approvals and record should persist. A repeated
   acceptance cannot create a second, different receipt for the same version.

Owner review and downloads use no AI requests. The link is bound to the card
version and expires 24 hours after creation. Creating another link replaces the
previous one. If a link expires before acceptance, generate a fresh link from
the customer tab. Download a receipt while a valid owner link is available.
The local customer tab can still download the current record after link expiry.

## Acceptance check: changes after approval

After downloading the version 3 record, propose a customer correction such as
**Make it 47 lunch boxes**. Expected:

- A new version appears as a draft after successful extraction.
- Current customer and owner approvals are empty.
- The old owner link cannot accept or export the current card.
- Customer readback and spoken confirmation are required again.
- A new owner link and owner acceptance are then required for a new receipt.

The old downloaded record remains a historical record of the old terms. Files
and sent emails cannot be remotely recalled by this local application. Each
record explicitly states that later revisions may exist.

## Acceptance check: an owner requests a change

Use a customer-confirmed version that has not yet been owner-accepted:

1. Open its owner link and use **Request a change instead**.
2. Explain the requested change, then click **Request customer review**.
3. The customer tab shows the owner's note after refresh. The note is not
   silently inserted into the customer's instruction transcript.
4. The customer explains the intended final instructions by voice or text.
   Extraction creates a new version. Readback, customer confirmation and a
   fresh owner acceptance are required again.

The owner cannot accept a version after requesting changes to it. No shared
record is issued for an incomplete pair of approvals.

## Give both parties a copy

After both approve, expand **Prepare a copy for each party** in the customer
tab. Enter the intended recipient addresses and download the two email drafts.
Use `customer@example.com` and `owner@example.com` for an offline test.

The ZIP contains:

| File | Purpose |
| --- | --- |
| `shared-record.html` | Readable record, opens without a server |
| `shared-record.json` | Structured card, readback and approval evidence |
| `customer-draft.eml` | Addressed customer draft with both attachments |
| `owner-draft.eml` | Addressed owner draft with identical attachments |
| `READ-ME.txt` | Manual delivery instructions |

Open a draft in a mail client that supports editing `.eml` drafts, choose a
sender account, review it and send it yourself. If your email client cannot edit
the draft, attach the HTML and JSON files in a normal email to each recipient.
**Downloading drafts sends nothing.** Recipient addresses are checked for basic
format, not ownership or deliverability. They are used to generate the ZIP and
are not stored in the review database.

Direct sending from SunoJob still requires an email transport, verified sender
configuration and delivery/failure tracking. Do not describe this checkpoint as
automatically emailing either party.

## What this record establishes

This prototype records two separate approval actions for an exact card version.
It does not verify who physically performed those actions. Customer identity,
owner display name, voice identity, recipient ownership and actual listening
are not verified. Playback completion is a browser-reported event.

The owner link is a bearer link: anyone holding it can act as that owner in this
local prototype. Its token is stored hashed, carried in the URL fragment rather
than a server query, removed from the visible owner URL after loading and kept
in that tab's session storage for refresh. Token headers and fragments are not
part of the default access log. Do not post review links publicly.

The server still listens only on `127.0.0.1`. It has no user authentication and
must not be exposed as a public service in this form. Owner links work on this
laptop; sending a `127.0.0.1` link to another device will not reach your server.
A remote two-party workflow needs deployment and authentication design.

Receipt SHA-256 is computed over canonical UTF-8 JSON of every receipt field
except `receipt_sha256`, using sorted keys, compact separators and unescaped
Unicode. Card SHA-256 covers the full saved draft snapshot. Approval records
are separate from its original extraction flags. These digests detect ordinary
inconsistency; they are not digital signatures, trusted timestamps or protection
against a privileged person rewriting the database and recalculating hashes.
No legal enforceability is guaranteed.

All runtime data remains under `.local`, including private transcripts,
recordings, the database and extraction reports. Keep `.local/` and `.venv/`
out of source control and public uploads. Receipts include original transcript
turns: review that content before sharing them.

## Verification and next gates

**155 automated tests passed** before delivery: the previous 130 plus 25 owner,
receipt, migration and email-draft checks. The new checks include stale/rotated/
expired tokens, separate acceptance, changed-version invalidation, exact matching
downloads, HTML escaping, receipt integrity, email-header injection rejection,
identical draft attachments and old-session upgrade compatibility. JavaScript
syntax and referenced DOM IDs were checked. HTTP tests use labelled offline
service doubles; no actual owner, email delivery or new live API run was tested
here. The new UI still needs the local browser acceptance check above.

Next: complete this local check; configure and test actual delivery; collect a
small independently labelled set of natural English recordings; run clean and
degraded audio evaluation; return to Telugu; prepare the public demo and
submission material. Use measured results and visible limitations in the demo.
