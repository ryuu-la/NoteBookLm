"""Inspect tracked source without printing matched values. Run before publishing."""
import argparse
import os
import re
import subprocess
from pathlib import Path

PATTERNS = [
    re.compile(rb"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]
BLOCKED_PARTS = {".data", ".venv", "test-results", "__pycache__", ".publish"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.repo.resolve()
    names = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"]).decode().split("\0")
    known = [os.environ[name].encode() for name in ("GEMINI_API_KEY", "NOTEBOOK_API_KEY") if os.environ.get(name)]
    try:
        import keyring
        for provider in ("Gemini", "Local / compatible"):
            value = keyring.get_password("local-notebook", provider)
            if value:
                known.append(value.encode())
    except Exception:
        pass
    failures, count = [], 0
    for name in filter(None, names):
        path = root / name
        count += 1
        if BLOCKED_PARTS.intersection(path.relative_to(root).parts) or path.name.startswith(".env") or path.suffix.lower() in {".db", ".sqlite", ".pem", ".key", ".p12", ".pfx", ".log"}:
            failures.append(name + ": runtime or secret file")
        data = subprocess.check_output(["git", "-C", str(root), "show", ":" + name])
        if any(pattern.search(data) for pattern in PATTERNS) or any(value in data for value in known):
            failures.append(name + ": credential pattern or known key found")
    if failures:
        print("Publish check FAILED (values redacted):\n" + "\n".join(failures))
        raise SystemExit(1)
    print(f"PASS: {count} tracked files; no blocked runtime paths, credential patterns, or configured key values found.")


if __name__ == "__main__":
    main()
