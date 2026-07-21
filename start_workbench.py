"""Start the loopback workbench once, wait until ready, and open it."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8765/"
READY = URL + "api/ready"


def ready() -> bool:
    try:
        with urllib.request.urlopen(READY, timeout=1.5) as response:
            return response.status == 200 and json.loads(response.read().decode("utf-8")).get("ready") is True
    except (OSError, ValueError, urllib.error.URLError):
        return False


def main() -> int:
    runtime = ROOT / "runtime" / "workbench"
    runtime.mkdir(parents=True, exist_ok=True)
    if not ready():
        log = (runtime / "server.log").open("a", encoding="utf-8")
        pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
        interpreter = pythonw if pythonw.is_file() else ROOT / ".venv" / "Scripts" / "python.exe"
        base_flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        command = [str(interpreter), str(ROOT / "local_workbench.py")]
        try:
            process = subprocess.Popen(
                command, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                creationflags=base_flags | breakaway, close_fds=True,
            )
        except OSError:
            if not breakaway:
                log.close()
                raise
            process = subprocess.Popen(
                command, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                creationflags=base_flags, close_fds=True,
            )
        finally:
            log.close()
        (runtime / "server.json").write_text(json.dumps({"pid": process.pid, "url": URL}), encoding="utf-8")
        for _ in range(40):
            if ready():
                break
            if process.poll() is not None:
                print(f"工作台启动失败，日志：{runtime / 'server.log'}")
                return 1
            time.sleep(.5)
        else:
            print(f"工作台启动超时，日志：{runtime / 'server.log'}")
            return 1
    webbrowser.open(URL)
    print(f"工作台已启动：{URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
