# Receipt presentation and refresh update

The user reports that both email copies arrived, approvals survive refresh, and
initial/corrected Telugu requests work. This update improves receipt readability
and fixes blank recipient fields after a page refresh.

## What changed

- Visible receipt dates are converted to India Standard Time (IST, +05:30), with
  readable dates and 12-hour clock times. They are not just relabelled. Original
  machine timestamps remain in the companion JSON evidence.
- Full-width instruction cards replace the narrow table on phones. Tasks,
  quantities, restrictions and permission requirements use clearer headings.
- Each instruction retains its exact supporting source wording and turn ID.
- Net corrections identify their subject and earlier/current values. The full
  transcript timeline retains intermediate changes.
- Separate customer and owner approval cards show the approved version and time.
  Names remain explicitly unverified; no missing personal details are invented.
- Record IDs and hashes move into an expandable integrity section.
- Both customer and owner downloads still use byte-identical HTML and JSON.
- The browser restores the most recent saved email-preview recipients for that
  request version. It does not overwrite edits you make during refresh and does
  not restore addresses across different requests or versions.
- Email status text is shorter and browser review/email timestamps use IST.
- Pending previews created with an older layout require a fresh preview. The
  application checks actual attachment bytes against the reviewed hashes before
  any new submission.

## Install

Stop the server with Ctrl+C. Download the updated SunoJob_Completion_Checkpoint.zip
and replace the older copy in Downloads, then run:

```bash
bash <<'BASH'
set -eu
cd "$HOME/sunojob"
mkdir -p .local/backups
sunojob_backup="$(mktemp -d .local/backups/receipt-polish-XXXXXX)"
for path in sunojob scripts tests fixtures examples README.md COMPLETION_README.md
do
    if [ -e "$path" ]; then
        cp -a "$path" "$sunojob_backup/"
    fi
done
.venv/bin/python -m zipfile -e \
  "$HOME/Downloads/SunoJob_Completion_Checkpoint.zip" .
.venv/bin/python -m unittest discover -s tests -q
BASH
```

Restart as usual:

```bash
cd "$HOME/sunojob"
.venv/bin/python -m sunojob.serve --model gemini-3.5-flash-lite --email
```

Enter credentials at the terminal prompts, then press Ctrl+Shift+R in the browser.
Open the same approved request. Its recipient fields should restore from its
saved email job. Select **Download shared record** to view the redesigned HTML.
This download makes no model or SMTP request and needs no new approval.

## Already-received emails

An update cannot change HTML files already attached to received email. Those
original files remain the record of their original submission. Newly downloaded
HTML uses the new presentation, while its saved approval evidence remains the
same. Previously accepted copies are not automatically resent. A new preview
does not override duplicate-send protection for the same receipt and recipients.
Future newly approved requests use the polished HTML in outgoing email.

The attachment hashes in a new preview describe its proposed new submissions.
Already-accepted earlier copies can have a different HTML layout; their original
email job retains its original attachment hashes. Check that original job when
comparing hashes for an earlier submission.

## Preview and checks

`examples/receipt-preview.html` is a self-contained fictional sample marked SAMPLE.
Open it in a browser to inspect the design. It is not a real customer record.

225 offline Python tests pass, including IST date rollover, evidence preservation,
unchanged receipt JSON, byte-identical party downloads, rejected stale previews,
attachment-hash checks and duplicate-send protection. The additional JavaScript
controller checks can be run with `node tests/check_recipient_restore.cjs` if Node
is installed; Node is not required to run SunoJob.

The HTML was rendered and checked at 1100, 390 and 320 pixel widths. Browser checks
also verified that refresh restores saved recipients, user edits survive a status
refresh, consent remains unchecked, and refresh makes no POST/send requests.
No real API or SMTP request was made while preparing this update.
