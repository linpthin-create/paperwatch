from __future__ import annotations

import os
import platform
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any

from paperwatch.models import Settings


LABEL = "com.paperwatch.daily"


def install_schedule(config_path: str | Path, settings: Settings) -> Path:
    if platform.system() != "Darwin":
        raise RuntimeError("schedule install currently supports macOS launchd only")
    if not settings.schedule.enabled:
        raise RuntimeError("schedule.enabled is false; enable it in Config before installing")

    path = launchd_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plist = build_launchd_plist(config_path, settings)
    path.write_bytes(plistlib.dumps(plist, sort_keys=False))
    _launchctl(["bootout", _gui_domain(), str(path)], check=False)
    _launchctl(["bootstrap", _gui_domain(), str(path)], check=True)
    _launchctl(["enable", f"{_gui_domain()}/{LABEL}"], check=True)
    return path


def uninstall_schedule() -> Path:
    path = launchd_plist_path()
    if platform.system() == "Darwin" and path.exists():
        _launchctl(["bootout", _gui_domain(), str(path)], check=False)
    if path.exists():
        path.unlink()
    return path


def schedule_status(config_path: str | Path, settings: Settings) -> dict[str, Any]:
    path = launchd_plist_path()
    return {
        "platform": platform.system(),
        "config": str(Path(config_path).expanduser().resolve()),
        "enabled_in_config": settings.schedule.enabled,
        "time": f"{settings.schedule.hour:02d}:{settings.schedule.minute:02d}",
        "days": settings.schedule.days,
        "send_feishu": settings.feishu.enabled and settings.feishu.send_on_schedule and bool(settings.feishu.webhook_url),
        "launchd_plist": str(path),
        "installed": path.exists(),
    }


def build_launchd_plist(config_path: str | Path, settings: Settings) -> dict[str, Any]:
    config = Path(config_path).expanduser().resolve()
    workdir = config.parent
    logs_dir = workdir / "data" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    environment = _launch_environment()
    return {
        "Label": LABEL,
        "ProgramArguments": [
            sys.executable,
            "-m",
            "paperwatch",
            "run",
            "--config",
            str(config),
            "--days",
            str(settings.schedule.days),
        ],
        "EnvironmentVariables": environment,
        "WorkingDirectory": str(workdir),
        "StartCalendarInterval": {
            "Hour": settings.schedule.hour,
            "Minute": settings.schedule.minute,
        },
        "StandardOutPath": str(logs_dir / "paperwatch.out.log"),
        "StandardErrorPath": str(logs_dir / "paperwatch.err.log"),
        "RunAtLoad": False,
    }


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _launch_environment() -> dict[str, str]:
    env: dict[str, str] = {}
    source_root = Path(__file__).resolve().parents[1]
    if (source_root / "paperwatch" / "__init__.py").exists():
        env["PYTHONPATH"] = str(source_root)
    path = os.environ.get("PATH")
    if path:
        env["PATH"] = path
    return env


def _gui_domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(args: list[str], check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *args],
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
