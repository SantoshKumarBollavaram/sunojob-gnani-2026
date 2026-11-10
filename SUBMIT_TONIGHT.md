# Submit SunoJob tonight

Deadline: **10 November 2026, 11:59 PM IST**. Aim to submit with a buffer.
Locate the final submission link in your registered email now. The public
registration page is not the final submission form. GitHub is not listed as
mandatory in the public checklist; the public demo post is required. Follow
additional required fields in the actual form. Do not add features tonight.

The supplied final form asks for:

| Field | Submit |
| --- | --- |
| 5. Project URL | GitHub repository containing `PITCH.pdf` (verified one page), source and README; or an accessible Drive/live project link with the pitch |
| 6. Demo video | An accessible 2-3 minute working-demo video link |
| 7. Bonus awards social post | Your public LinkedIn/X post tagging Gnani and detailing the solution |

The registration email also requests a public demo post and both hashtags.
Post publicly and include the post link even though field 7 mentions bonus awards.
Use `VIDEO_SCRIPT.md` for the required 2-3 minute video. A 60-second awards edit
does not replace the required submission video.

## 1. Verify the installed app

```bash
cd "$HOME/sunojob"
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m sunojob.checkpoint
```

Pending drafts/corrections are not automatically corruption. Your demo must
show the version actually approved by both roles. A historical receipt does
not approve a pending correction. Stop if the tests fail and inspect the error.

Optional consistent backup, including when SQLite is open:

```bash
cd "$HOME/sunojob"
.venv/bin/python - <<'PY'
from datetime import datetime
from pathlib import Path
import sqlite3
source = Path('.local/reviews.sqlite3').resolve()
if not source.is_file():
    raise SystemExit('No saved review database; no backup created.')
folder = Path('.local/backups')
folder.mkdir(parents=True, exist_ok=True)
target = folder / ('reviews-before-submission-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3')
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
    with sqlite3.connect(target) as dst:
        src.backup(dst)
print('Saved local backup:', target)
PY
```

## 2. Record and post

Follow `DEMO_GUIDE.md` and use the original app at `$HOME/sunojob`. This clean
submission folder has no saved requests. Use your own voice, synthetic work
details and no real customer identifiers. Show a fresh request, readback,
correction, renewed readback, customer confirmation, separate owner acceptance
and the final receipt. If you show email, hide personal addresses and inbox
contents. Do not present SMTP acceptance as confirmed inbox arrival.

Attach the video to a **public** LinkedIn or X post using `SOCIAL_POST.md`.
Tag the genuine Gnani AI account and include both hashtags:

```text
#GnaniAI #GreatIndianAIInternshipChallenge
```

Copy that specific post's permalink and check that the public video plays.
If the form separately asks for a video, upload it or provide an accessible
video link in the format the form accepts. Localhost is not a public demo URL.
Posting does not complete final submission. Do not delay posting for GitHub.

## 3. Optional clean GitHub repository

Use this clean source folder, not your installed working app folder. The
commands create a **new public repository** and never force-push. If time is
tight, finish the portal first unless source is a required field.

Install GitHub CLI only if it is missing:

```bash
sudo apt-get update
sudo apt-get install -y git gh
```

Check authentication. Run login only if not authenticated:

```bash
gh auth status
# Only if needed:
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
```

Publish the clean source:

```bash
bash <<'BASH'
set -euo pipefail
cd "$HOME/sunojob-submission-20261110"
python3 check_submission.py
if [ -e .git ]; then
    echo 'Git already initialized here. Inspect git status and git remote -v before continuing.'
    exit 1
fi
gh auth status
sunojob_login="$(gh api user --jq .login)"
git init -b main
git config user.name 'Santosh Kumar Bollavaram'
git config user.email "${sunojob_login}@users.noreply.github.com"
git add .
git diff --cached --check
git diff --cached --name-only
git commit -m 'Submit SunoJob voice review and shared receipt prototype'
gh repo create "${sunojob_login}/sunojob-gnani-2026" \
  --public --source=. --remote=origin --push \
  --description 'English and Telugu voice instructions with readback, corrections, versioned approvals and shared receipts using Gnani Prisma and Timbre'
gh repo view --json url --jq .url
git archive --format=zip --output="$HOME/Downloads/SunoJob_Source_Submission.zip" HEAD
BASH
```

Use the printed repository URL in the form. The ZIP in Downloads is the exact
committed source for a source-upload field. GitHub does not host the Python
application. Use your normal verified Git email instead of the no-reply email
if you prefer. If the repo name already exists or the network fails, stop and
inspect `git status`, `git remote -v` and `gh repo view` before retrying. Do not
delete history, remove the guard or force-push just to rerun the whole block.

## 4. Submit the final form

Use `SUBMISSION_TEXT.md` for matching fields. Enter accurate registered details:
Santosh Kumar Bollavaram; PES University; B.Tech Computer Science; graduation
2028; solo. Match the specific degree title used in your registration. Enter
your actual registered email and phone privately.

Required by the public checklist: working demo video; written explanation;
Gnani models/APIs used; nominated social-post link per platform used. Include
the problem, users and actual contribution. Add GitHub/source if the form asks.
Do not enter `127.0.0.1` as a publicly accessible deployed app.

Review required fields, submit, and wait for the success page. Save the
confirmation/entry ID or confirmation email. Do not stop at saving a draft.

## Claims to avoid

No claims of 100% speech accuracy, real customer validation, production security,
verified identity, independent owners in a staged demo, public hosting, Evon
integration or guaranteed inbox delivery. The 236 tests are offline software
tests. Independent natural-speech evaluation remains unfinished.

## Official references checked on 10 November 2026

- https://www.gnani.ai/internship
- https://www.gnani.ai/great-indian-ai-internship-registration-form
- https://www.gnani.ai/resources/blogs/great-indian-ai-internship-challenge-2026
