#!/usr/bin/env python3
"""Check the toolchain and say exactly what to run for anything missing.

Standard library only, and no imports from wavsim: this has to work on a machine
where nothing is installed yet, which is the case where it is most useful.

    python3 scripts/doctor.py        or        make doctor
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

OK = "ok"
MISSING = "MISSING"
OLD = "TOO OLD"


def _system() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        # WSL reports Linux, which is what we want: the apt instructions apply.
        return "linux"
    if sys.platform.startswith("win"):
        return "windows"
    return "other"


SYSTEM = _system()

# Inside the container the dependencies are system packages and a venv would be
# wrong, so several messages change.
IN_CONTAINER = Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()

INSTALL_HINTS = {
    "verilator": {
        "macos": "brew install verilator",
        "linux": "sudo apt-get install -y verilator",
        "windows": "no native Windows build; use the container (see docs/getting_started.md)",
    },
    "iverilog": {
        "macos": "brew install icarus-verilog",
        "linux": "sudo apt-get install -y iverilog",
        "windows": "https://bleyer.org/icarus/ , or use the container",
    },
    "c++": {
        "macos": "xcode-select --install",
        "linux": "sudo apt-get install -y build-essential",
        "windows": "use the container",
    },
    "make": {
        "macos": "xcode-select --install",
        "linux": "sudo apt-get install -y build-essential",
        "windows": "use the container, or run the wavsim CLI directly",
    },
}


def _version(cmd, pattern=r"(\d+)\.(\d+)"):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (proc.stdout or "") + (proc.stderr or "")
    match = re.search(pattern, text)
    if not match:
        return None
    return tuple(int(g) for g in match.groups())


class Check:
    def __init__(self, name, status, detail="", hint="", required=True):
        self.name = name
        self.status = status
        self.detail = detail
        self.hint = hint
        self.required = required

    @property
    def good(self) -> bool:
        return self.status == OK


def check_tool(name, binary, min_version=None, version_cmd=None, required=True) -> Check:
    path = shutil.which(binary)
    hint = INSTALL_HINTS.get(name, {}).get(SYSTEM, "")
    if path is None:
        return Check(name, MISSING, f"{binary} not on PATH", hint, required)

    version = _version(version_cmd or [binary, "--version"]) if version_cmd or min_version else None
    if min_version and version and version < min_version:
        shown = ".".join(str(v) for v in version)
        want = ".".join(str(v) for v in min_version)
        return Check(name, OLD, f"{shown}, need {want}+", hint, required)

    detail = ".".join(str(v) for v in version) if version else path
    return Check(name, OK, detail, "", required)


def check_python() -> Check:
    v = sys.version_info
    if (v.major, v.minor) < (3, 9):
        return Check("python", OLD, f"{v.major}.{v.minor}, need 3.9+", "install a newer Python")
    return Check("python", OK, f"{v.major}.{v.minor}.{v.micro}")


def check_module(name, package=None, required=True) -> Check:
    try:
        module = __import__(name)
    except ImportError:
        return Check(
            name,
            MISSING,
            "not importable",
            f'pip install -e ".[dev]"  (or: pip install {package or name})',
            required,
        )
    return Check(name, OK, getattr(module, "__version__", "installed"), required=required)


def check_venv() -> Check:
    """Present is not the same as usable.

    The repository is bind-mounted into the container, so a macOS or Windows
    .venv shows up under Linux with an interpreter that cannot run. Reporting it
    as fine would be actively misleading, so the interpreter is executed.
    """
    if IN_CONTAINER:
        return Check(".venv", OK, "not used in the container; deps are system packages",
                     required=False)

    python = REPO_ROOT / ".venv" / ("Scripts/python.exe" if SYSTEM == "windows" else "bin/python")
    if not python.exists():
        return Check(
            ".venv", MISSING, "not created",
            "make setup   (or: python3 -m venv .venv && .venv/bin/pip install -e \".[dev]\")",
            required=False,
        )
    try:
        proc = subprocess.run([str(python), "-c", ""], capture_output=True, timeout=30)
        runs = proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        runs = False
    if not runs:
        return Check(
            ".venv", MISSING, "present but its interpreter does not run here",
            "ignore it (this is normal in the container), or rebuild it with `make setup`",
            required=False,
        )
    return Check(".venv", OK, str(python.parent.parent), required=False)


def main() -> int:
    print(f"wavsim doctor — {platform.platform()}")
    print(f"repository: {REPO_ROOT}\n")

    checks = [
        check_python(),
        check_venv(),
        check_module("numpy"),
        check_module("scipy"),
        check_module("matplotlib", required=False),
        check_module("pytest", required=False),
        check_tool("verilator", "verilator", min_version=(5, 0)),
        check_tool("iverilog", "iverilog", min_version=(11, 0),
                   version_cmd=["iverilog", "-V"], required=False),
        check_tool("c++", "c++", version_cmd=["c++", "--version"]),
        check_tool("make", "make", required=False),
    ]

    width = max(len(c.name) for c in checks)
    for c in checks:
        mark = "+" if c.good else ("!" if not c.required else "x")
        tag = "" if c.required else " (optional)"
        print(f"  [{mark}] {c.name:<{width}}  {c.status:<8} {c.detail}{tag}")
        if not c.good and c.hint:
            print(f"      {'':<{width}}  -> {c.hint}")

    required_bad = [c for c in checks if c.required and not c.good]
    optional_bad = [c for c in checks if not c.required and not c.good]

    print()
    if required_bad:
        print("Missing required tools: " + ", ".join(c.name for c in required_bad))
        if SYSTEM == "windows":
            print(
                "\nOn Windows the supported route is the container:\n"
                "  open this folder in VS Code and choose 'Reopen in Container',\n"
                "  or run:  .\\wavsim.ps1 setup"
            )
        return 1

    if optional_bad:
        names = ", ".join(c.name for c in optional_bad)
        print(f"Ready. Optional pieces not installed: {names}")
    else:
        print("Ready. Everything is installed.")

    if any(c.name == "iverilog" and not c.good for c in checks):
        print("Without iverilog, `wavsim crosscheck` cannot compare the two simulators.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
