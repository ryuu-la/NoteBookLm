"""Start the local application without a console window."""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--replace-pid", type=int)
args = parser.parse_args()
if args.replace_pid:
    import psutil
    previous = psutil.Process(args.replace_pid)
    if previous.cmdline()[-2:] != ["-m", "local_notebook.main"] or Path(previous.cwd()).resolve() != root:
        raise SystemExit("Refusing to replace a process that is not this project's notebook server")
    children = previous.children(recursive=True)
    for process in children:
        process.terminate()
    previous.terminate()
    psutil.wait_procs([previous, *children], timeout=10)
logs = root / ".data" / "logs"
logs.mkdir(parents=True, exist_ok=True)
with (logs / "app.log").open("a", encoding="utf-8") as log:
    process = subprocess.Popen([sys.executable, "-m", "local_notebook.main"], cwd=root,
                               stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
(root / ".data" / "app.pid").write_text(str(process.pid))
url = "http://127.0.0.1:" + os.environ.get("NOTEBOOK_PORT", "8080")
for _ in range(80):
    try:
        if httpx.get(url + "/health", timeout=2).status_code == 200:
            print(f"Folio is healthy (launcher PID {process.pid}). Open {url}")
            break
    except httpx.HTTPError:
        pass
    time.sleep(.25)
else:
    raise SystemExit("Startup did not become healthy. See .data/logs/app.log")
