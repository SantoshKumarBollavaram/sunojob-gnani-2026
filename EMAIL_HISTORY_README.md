# Email history remains visible during corrections

Previously, the email results were inside the current-version shared-record
panel. A proposed or failed correction hides that panel because the current
request is no longer approved. This also hid the earlier delivery history,
which made already-sent copies appear to have disappeared.

The new **Email delivery history** section is independent of current approval.
It shows saved submission results, the sender, both recipient addresses, card
version and IST time. Earlier submissions remain visible while a correction is
pending. Current sending stays disabled until the current version is approved.

Submitted jobs appear first. Unsent previews are grouped in a collapsed section
and labelled not sent. The view displays the recent jobs returned by the existing
API (up to 20 per request), rather than discarding everything after the fifth
entry. Empty history and load failures receive explicit messages.

These are local records of SMTP attempts, not copies of a Gmail inbox. Open the
recipient's email service for the actual email message. SMTP acceptance alone
does not verify inbox delivery. The app does not access or delete inbox messages.
The shared receipt attachments remain under **Saved approval snapshots**.

Install the updated SunoJob_Completion_Checkpoint.zip with the existing backup
and extraction procedure, restart the server, and press Ctrl+Shift+R. Select the
English request beginning ace1905e and scroll to **Email delivery history** to
inspect its saved earlier submission. No additional email send is needed.

225 Python regression tests pass. The JavaScript checks now also cover history
visibility during a pending correction and separation of unsent previews.
A browser check against the real local app with offline service doubles verified
that a prior accepted submission remains visible despite six newer previews and
a failed correction; sender and both recipients are shown; refresh makes no POST
or send calls; current sending remains disabled; the phone layout has no
horizontal overflow. No real provider or SMTP request was made in this update.

This patch changes the presentation and error messages for viewing saved jobs.
It does not reinstate approvals, resend old copies or alter stored delivery data.
