# Invalidation and error audit

This update follows a direct code review, regression run and offline browser
workflow check. It fixes two reproduced errors and the missing archive access
that made a pending correction appear to have erased earlier receipts.

## Findings and fixes

| Finding | Before | After |
| --- | --- | --- |
| Audit after a failed correction | An intact approved snapshot could be reported as corrupted because its historical approvals differed from the intentionally cleared current approvals. | Historical snapshot integrity and current approval status are checked separately. A valid pending correction is not marked as corruption. |
| Email message-construction failure | A MIME construction exception after reserving a send could leave the request locked in sending. | This recipient is saved as failed before submission; other recipient results are preserved, the job finishes, and the lock is released. Error inputs are not saved. |
| Finding earlier approved receipts | The receipt controls disappeared while a correction was pending, even though approved snapshots remained in the database. | Saved approval snapshots have their own visible section and read-only HTML/JSON downloads. Archived HTML explicitly says it does not approve current pending work. |
| Understanding a pending state | The page displayed a generic correction message, and the request selector reset to its placeholder. | The pending text is shown for review, the latest recorded workflow action/time is displayed, and the current request remains selected. |

## Expected invalidation rules

- GET/status refreshes do not clear approvals or alter the review database.
- Proposing a correction intentionally clears the current customer and owner
  approvals immediately. This prevents approving the old card while an update
  is pending.
- If extraction of the correction fails, the prior card can remain visible at
  the same version number. The pending correction still blocks confirmation and
  sending until it is applied and the revised version is reviewed.
- Earlier approved receipts remain historical records. Downloading them never
  reinstates current approval or bypasses a pending correction.
- Owner links, spoken replies and email previews for stale versions remain
  rejected. Unknown SMTP outcomes are not automatically resent.

## Verification performed

225 automated Python tests pass, plus the JavaScript recipient-restoration checks.
The additional audit regressions include:

- Repeated GET refreshes leave database bytes and approval/receipt data unchanged.
- Valid pending corrections are not falsely labelled as integrity failures.
- Actual altered approvals still fail the integrity audit.
- Archived HTML/JSON downloads work during a pending correction without writes.
- A revised draft does not inherit approval from an archived snapshot.
- Simultaneous owner acceptance creates exactly one receipt.
- Simultaneous repeat sends do not duplicate recipient submission.
- Message-construction failures release locks and remain known pre-submission
  failures. Retrying a failed recipient does not resend an already-accepted one.
- Restart preserves pending text and historical snapshots.

A real headless browser exercised the local FastAPI app with offline speech,
model and SMTP doubles. The checked flow was:

pending correction → refresh → archived HTML download → apply correction →
generate/play readback → voice-reply upload → fresh customer confirmation →
separate owner acceptance → email preview → explicit send → refresh.

The browser reported no page errors. Refresh/download steps made no POST requests.
The two explicitly sent copies produced exactly two calls to the offline mailer.
The pending-state view was inspected at desktop and phone widths; the phone view
had no horizontal overflow. No real provider or SMTP request was made.

These checks establish behavior for the tested paths. They are not a claim of
zero possible bugs, real-world model accuracy or access to the user's laptop.
The user's actual pending-state cause must be read from their local event record.

## Install and check your saved data

Stop the server. Download the updated SunoJob_Completion_Checkpoint.zip, replacing
the old Downloads copy. Back up the installed source, extract it and run:

```bash
cd "$HOME/sunojob"
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m sunojob.checkpoint
```

The checkpoint command opens the database read-only and makes no API/SMTP calls.
It reports current approval/receipt checks, pending-correction status, an intact
earlier snapshot at the same version where applicable, and the last recorded
workflow action with its IST time. It does not print transcripts, names, keys or
recipient addresses. Paste that output if a local state still needs diagnosis.

Restart the app as usual and press Ctrl+Shift+R. For a pending request, review its
explanation and correction box. Earlier receipts are under **Saved approval
snapshots**. Only retry or edit the correction if that is what you intend; the
application does not approve or send anything during recovery or refresh.

This update adds no dependencies and requires no database migration. All earlier
voice, receipt, email and recording-evaluation features remain included.
