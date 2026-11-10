#!/usr/bin/env bash
# Publish this reviewed source tree; never operates on the installed app folder.
set -euo pipefail
cd "$(dirname "$0")"

test -f PITCH.pdf || { echo 'PITCH.pdf is missing. Use the refreshed submission kit.'; exit 1; }
python3 check_submission.py
gh auth status
gh auth setup-git
sunojob_login="$(gh api user --jq .login)"
sunojob_repo="${sunojob_login}/sunojob-gnani-2026"

if [ ! -d .git ]; then
    git init -b main
fi
if [ "$(git branch --show-current)" != main ]; then
    echo 'Expected main branch. Inspect this source folder before publishing.'
    exit 1
fi
git config user.name 'Santosh Kumar Bollavaram'
git config user.email "${sunojob_login}@users.noreply.github.com"

if git remote get-url origin >/dev/null 2>&1; then
    sunojob_remote="$(git remote get-url origin)"
    case "$sunojob_remote" in
        "https://github.com/${sunojob_repo}"|"https://github.com/${sunojob_repo}.git"|"git@github.com:${sunojob_repo}.git") ;;
        *) echo 'Existing origin points elsewhere. Stop and inspect git remote -v.'; exit 1 ;;
    esac
    sunojob_visibility="$(gh repo view "$sunojob_repo" --json visibility --jq .visibility)"
    if [ "$sunojob_visibility" != PUBLIC ]; then
        echo 'Existing repository is not public. Decide sharing explicitly before using it as the public project link.'
        exit 1
    fi
fi

git add .
git diff --cached --check
git diff --cached --name-only
if ! git diff --cached --quiet; then
    git commit -m 'Prepare SunoJob submission with one-page pitch and demo guide'
fi

if git remote get-url origin >/dev/null 2>&1; then
    git push -u origin main
else
    # An existing repository is reused only if it is already public. An API
    # failure is never treated as permission to change repository visibility.
    if sunojob_visibility="$(gh repo view "$sunojob_repo" --json visibility --jq .visibility 2>/dev/null)"; then
        if [ "$sunojob_visibility" != PUBLIC ]; then
            echo 'The named repository exists and is not public. Choose the intended sharing explicitly.'
            exit 1
        fi
        git remote add origin "https://github.com/${sunojob_repo}.git"
        git push -u origin main
    else
        gh repo create "$sunojob_repo" --public --source=. --remote=origin --push \
            --description 'Voice instructions with Gnani Prisma and Timbre, reviewed corrections, separate approvals and shared receipts'
    fi
fi

mkdir -p "$HOME/Downloads"
git archive --format=zip --output="$HOME/Downloads/SunoJob_Source_Submission.zip" HEAD
echo 'PROJECT URL FOR FIELD 5:'
gh repo view "$sunojob_repo" --json url --jq .url
echo 'The repository contains PITCH.pdf (one page), source code and setup instructions.'
