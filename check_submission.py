"""Read-only upload preflight. Reports filenames, never matching secret values."""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
SKIP_DIRS = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache', '.ruff_cache'}
PRIVATE_DIRS = {'.local', 'recordings', 'backups'}
PRIVATE_EXTENSIONS = {'.sqlite', '.sqlite3', '.db', '.pem', '.key', '.wav', '.mp3',
                      '.m4a', '.webm', '.mp4', '.zip'}
PATTERNS = [
    re.compile(rb'AIza[0-9A-Za-z_-]{35}'),
    re.compile(rb'gh[pousr]_[0-9A-Za-z]{30,}'),
    re.compile(rb'github_pat_[0-9A-Za-z_]{40,}'),
    re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(rb'(?i)(?:GNANI_API_KEY|GEMINI_API_KEY|SUNOJOB_SMTP_PASSWORD)\s*=\s*[\x22\x27]?[A-Za-z0-9_/-]{20,}'),
]


def main():
    problems = []
    checked = 0
    for path in sorted(ROOT.rglob('*')):
        relative = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.is_symlink():
            problems.append((str(relative), 'symlink requires manual review'))
            continue
        if any(part in PRIVATE_DIRS for part in relative.parts):
            problems.append((str(relative), 'private/generated path; exclude from upload'))
            continue
        if not path.is_file():
            continue
        if ((path.name.startswith('.env') and path.name != '.env.example')
                or path.suffix.lower() in PRIVATE_EXTENSIONS
                or path.name.startswith(('credentials', 'service-account'))):
            problems.append((str(relative), 'private/generated filename; exclude from upload'))
            continue
        raw = path.read_bytes()
        checked += 1
        if any(pattern.search(raw) for pattern in PATTERNS):
            problems.append((str(relative), 'possible embedded credential; review locally'))
    if problems:
        for name, reason in problems:
            print(f'REVIEW: {name}: {reason}')
        print('Preflight stopped. Do not upload until the listed files are reviewed.')
        return 1
    print(f'PASS: {checked} upload files checked; no listed private paths or common secret patterns found.')
    print('This limited scan cannot recognize every secret. Review staged filenames and never add your .local folder or credentials.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
