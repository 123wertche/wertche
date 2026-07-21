"""Non-destructive, secret-safe readiness check for local crawler workflows."""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TARGET_VIDEO_TABLE_ID = "tblakZnkghpokyGT"


def project_env(root=ROOT):
    env = os.environ.copy()
    dirs = (root / ".venv" / "Scripts", root / "tools" / "node", root / "tools" / "lark" / "node_modules" / ".bin", root / ".venv" / "lark" / "node_modules" / ".bin")
    env["PATH"] = os.pathsep.join(str(path) for path in dirs if path.exists()) + os.pathsep + env.get("PATH", "")
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def available(path_or_command, *, root=ROOT):
    path = Path(path_or_command)
    return str(path) if path.exists() else shutil.which(str(path_or_command), path=project_env(root).get("PATH"))


def run_utf8_command(args, *, timeout, root=ROOT):
    return subprocess.run(args, env=project_env(root), text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def _item(value, hint, status="ok"):
    return {"status": status, "path_or_version": value if status == "ok" else None, "hint": hint}


def _chrome(root):
    candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe", Path("C:/Program Files/Google/Chrome/Application/chrome.exe"), Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe")]
    return next((str(path) for path in candidates if path.is_file()), None)


def _reachable(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def build_result(*, root=ROOT, command_runner=run_utf8_command):
    root = Path(root)
    python = root / ".venv" / "Scripts" / "python.exe"
    lark = root / "tools" / "lark" / "node_modules" / ".bin" / "lark-cli.cmd"
    if not lark.is_file():
        lark = root / ".venv" / "lark" / "node_modules" / ".bin" / "lark-cli.cmd"
    config_path = root / "feishu-base-config.json"
    commands = {"node": ("node", "--version", "Install with 初始化项目.cmd."), "ffmpeg": ("ffmpeg", "-version", "Install ffmpeg on this computer, then rerun preflight."), "yt_dlp": ("yt-dlp", "--version", "Run 初始化项目.cmd to install project Python dependencies."), "whisper": ("whisper", "--help", "Run 初始化项目.cmd to install project Python dependencies.")}
    checks = {"project_python": _item(str(python), "Run 初始化项目.cmd.") if python.is_file() else _item(None, "Install Python 3, then run 初始化项目.cmd.", "missing"), "lark_cli": _item(str(lark), "Run 初始化项目.cmd while online.") if lark.is_file() else _item(None, "Run 初始化项目.cmd while online.", "missing")}
    for name, (command, flag, hint) in commands.items():
        found = available(command, root=root)
        if not found:
            checks[name] = _item(None, hint, "missing")
            continue
        try:
            completed = command_runner([found, flag], timeout=8, root=root)
            checks[name] = _item((completed.stdout or completed.stderr or found).splitlines()[0][:200], hint) if completed.returncode == 0 else _item(None, hint, "missing")
        except Exception:
            checks[name] = _item(None, hint, "missing")
    chrome = _chrome(root)
    checks["chrome"] = _item(chrome, "Install Google Chrome on this computer.") if chrome else _item(None, "Install Google Chrome on this computer.", "missing")
    checks["feishu_config"] = _item("configured", "Copy feishu-base-config.json through a secure channel.") if config_path.is_file() else _item(None, "Copy feishu-base-config.json through a secure channel.", "missing")
    table = "not_checked"
    auth = "not_checked"
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            table = "ok" if ((config.get("tables") or {}).get("videos") or {}).get("table_id") == TARGET_VIDEO_TABLE_ID else "invalid"
            if lark.is_file() and config.get("profile"):
                completed = command_runner([str(lark), "--profile", str(config["profile"]), "auth", "status", "--verify"], timeout=45, root=root)
                auth = "ok" if completed.returncode == 0 else "not_authorized"
        except Exception:
            table = "invalid"
    checks["cdp"] = _item("127.0.0.1:9333", "Start project Chrome from the workbench.") if _reachable(9333) else _item(None, "Start project Chrome from the workbench.", "unreachable")
    checks["cdp_bridge"] = _item("127.0.0.1:3457", "Start CDP bridge from the workbench.") if _reachable(3457) else _item(None, "Start CDP bridge from the workbench.", "unreachable")
    ok = all(item["status"] == "ok" for name, item in checks.items() if name not in {"cdp", "cdp_bridge"}) and table == "ok" and auth == "ok"
    return {"checks": checks, "auth": auth, "table": table, "ok": ok}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.parse_args()
    result = build_result()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
