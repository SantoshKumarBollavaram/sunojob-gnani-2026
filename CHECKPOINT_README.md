# SunoJob

Start with **EMAIL_HISTORY_README.md** for email results that remain visible
during corrections, and **AUDIT_README.md** for invalidation/recovery checks. **225 automated offline tests pass**, with JavaScript checks and a browser
flow through pending correction, archived receipt download, revision, readback,
customer confirmation, separate owner approval, explicit email and refresh.

This checkpoint fixes a false corruption report for valid pending corrections
and an email-construction failure that could leave a sending lock active.
Earlier receipts now remain accessible in **Saved approval snapshots**, with
clear historical labels. The selected request and pending-state reason remain
visible after refresh. Refresh does not change approvals.

The package includes polished IST receipts, recipient restoration and the
recording-evaluation tools. See RECEIPT_UPDATE_README.md and COMPLETION_README.md.
The user reports receipt delivery to both inboxes and working Telugu examples.
No real speech/model/SMTP requests were made during the audit.

This is a local prototype. Independent natural-speech evaluation, hosting and
identity verification remain outside these completed integration checks.
