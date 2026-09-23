"""Repository layout. Everything uses pathlib so the Windows/Icarus path works too."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

RTL_DIR = REPO_ROOT / "rtl"
RTL_COMMON = RTL_DIR / "common"
EFFECTS_RTL = RTL_DIR / "effects"

SIM_DIR = REPO_ROOT / "sim"
VERILATOR_DIR = SIM_DIR / "verilator"
ICARUS_DIR = SIM_DIR / "icarus"

CONFIG_DIR = REPO_ROOT / "configs"
EFFECT_CONFIGS = CONFIG_DIR / "effects"
CHAIN_CONFIGS = CONFIG_DIR / "chains"

AUDIO_IN = REPO_ROOT / "audio" / "input"
AUDIO_OUT = REPO_ROOT / "audio" / "output"

BUILD_DIR = REPO_ROOT / "build"
TESTS_DIR = REPO_ROOT / "tests"
GOLD_DIR = TESTS_DIR / "gold"

TOOLS_DIR = REPO_ROOT / "tools"


def build_dir(effect: str, backend: str) -> Path:
    """Per-effect, per-backend build directory (created on demand)."""
    d = BUILD_DIR / backend / effect
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_output_dir() -> Path:
    AUDIO_OUT.mkdir(parents=True, exist_ok=True)
    return AUDIO_OUT
