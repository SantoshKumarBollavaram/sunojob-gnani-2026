#!/usr/bin/env bash
# Stop the running app before using this script.
set -euo pipefail
cd "$(dirname "$0")"
sunojob_app_python="$HOME/sunojob/.venv/bin/python"
test -x "$sunojob_app_python" || { echo 'Existing app environment not found at ~/sunojob/.venv.'; exit 1; }
command -v ffmpeg >/dev/null || { echo 'FFmpeg is missing. Install it before the voice demo.'; exit 1; }

"$sunojob_app_python" - <<'PY'
from datetime import datetime
from pathlib import Path
import shutil

source = Path.cwd()
app = Path.home() / 'sunojob'
backup = app / '.local/backups' / ('submission-fix-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
paths = [
    'sunojob/providers.py', 'sunojob/speech.py',
    'tests/test_voice_adapters.py', 'tests/test_correction_recovery.py',
    'CORRECTION_FIX_README.md',
]
for name in paths:
    if not (source / name).is_file():
        raise SystemExit(f'Submission source is missing: {name}')
for name in paths:
    current = app / name
    if current.exists():
        saved = backup / name
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(current, saved)
    current.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / name, current)
print('Applied correction fix. Backups, where needed:', backup)
PY

cd "$HOME/sunojob"
"$sunojob_app_python" -m unittest discover -s tests -q
"$sunojob_app_python" -m sunojob.checkpoint
echo 'Offline checks completed. Next: restart the app and complete the live correction and approval flow.'
