"""Effect manifests: the one file a team member edits to describe their knobs.

A manifest maps human names onto slots of the 128-bit ``params`` bus so nobody
has to remember that feedback lives in bits [31:16]:

    --param mix=0.5 --param delay_samples=24000

Value syntax, deliberately unambiguous rather than clever:

    0.5    contains a '.'  -> normalised, scaled by the param's ``scale``
    50%    ends with '%'   -> normalised, same thing
    32768  a plain integer -> written to the bus verbatim

So ``mix=0.5`` and ``mix=32767`` mean the same thing and neither is a guess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

from . import N_PARAMS, PARAM_MAX
from .paths import EFFECT_CONFIGS, REPO_ROOT


class ManifestError(Exception):
    pass


@dataclass
class Param:
    name: str
    index: int
    default: Union[int, float] = 0
    scale: str = "raw"          # "raw" | "q16"
    min: Optional[int] = None
    max: Optional[int] = None
    unit: str = ""
    doc: str = ""
    # Natural units = bits * factor + offset (after the q16 divide, if any). This
    # is how a 16-bit slot carries a real quantity: an LFO rate in centi-hertz
    # stores 100 for 1.00 Hz with factor 0.01, so the RTL keeps integers and the
    # reference model still gets hertz.
    factor: float = 1.0
    offset: float = 0.0

    def to_bits(self, value: Union[int, float, str]) -> int:
        """Convert a user-supplied value into the 16-bit field written to the bus."""
        raw = self._normalise(value)
        lo = 0 if self.min is None else int(self.min)
        hi = PARAM_MAX if self.max is None else int(self.max)
        if raw < lo or raw > hi:
            raise ManifestError(
                f"{self.name}={value} resolves to {raw}, outside [{lo}, {hi}]"
            )
        return raw

    def _normalise(self, value) -> int:
        if isinstance(value, str):
            text = value.strip()
            if text.endswith("%"):
                return self._scaled(float(text[:-1]) / 100.0)
            if "." in text or "e" in text.lower():
                return self._scaled(float(text))
            return int(text, 0)
        if isinstance(value, float):
            return self._scaled(value)
        return int(value)

    def _scaled(self, value: float) -> int:
        """Natural units -> bus bits. The exact inverse of Manifest.natural()."""
        if self.factor == 0:
            raise ManifestError(f"{self.name} has factor 0, which is not invertible")
        v = (value - self.offset) / self.factor
        if self.scale == "q16":
            return int(round(v * PARAM_MAX))
        if self.scale == "raw":
            return int(round(v))
        raise ManifestError(f"{self.name} has unknown scale {self.scale!r}")

    def describe(self) -> str:
        bits = f"params[{16 * self.index + 15}:{16 * self.index}]"
        parts = [f"{self.name:<16} {bits:<18} default={self.default}"]
        if self.unit:
            parts.append(f"({self.unit})")
        if self.scale != "raw":
            parts.append(f"[{self.scale}]")
        if self.factor != 1.0 or self.offset != 0.0:
            parts.append(f"[x{self.factor:g}{self.offset:+g}]" if self.offset
                         else f"[x{self.factor:g}]")
        if self.doc:
            parts.append(f"- {self.doc}")
        return " ".join(parts)


@dataclass
class Manifest:
    name: str
    top: str
    sources: List[Path]
    params: List[Param] = field(default_factory=list)
    cycles_per_sample: int = 32
    flush_samples: int = 16
    owner: str = ""
    description: str = ""
    reference_model: str = ""
    path: Optional[Path] = None

    # -- loading ---------------------------------------------------------

    @classmethod
    def load(cls, name_or_path) -> "Manifest":
        path = Path(name_or_path)
        if not path.suffix:
            path = EFFECT_CONFIGS / f"{name_or_path}.json"
        if not path.exists():
            available = ", ".join(sorted(p.stem for p in EFFECT_CONFIGS.glob("*.json")))
            raise ManifestError(
                f"no manifest at {path}. Known effects: {available or '(none)'}"
            )
        raw = json.loads(path.read_text())
        return cls._from_dict(raw, path)

    @classmethod
    def _from_dict(cls, raw: dict, path: Path) -> "Manifest":
        for key in ("name", "top", "sources"):
            if key not in raw:
                raise ManifestError(f"{path}: missing required key {key!r}")

        params = [Param(**p) for p in raw.get("params", [])]
        seen: Dict[int, str] = {}
        for p in params:
            if not 0 <= p.index < N_PARAMS:
                raise ManifestError(
                    f"{path}: param {p.name} index {p.index} outside 0..{N_PARAMS - 1}"
                )
            if p.index in seen:
                raise ManifestError(
                    f"{path}: params {seen[p.index]} and {p.name} share index {p.index}"
                )
            seen[p.index] = p.name

        sources = [(REPO_ROOT / s).resolve() for s in raw["sources"]]
        missing = [s for s in sources if not s.exists()]
        if missing:
            raise ManifestError(
                f"{path}: source files not found: " + ", ".join(str(m) for m in missing)
            )

        return cls(
            name=raw["name"],
            top=raw["top"],
            sources=sources,
            params=params,
            cycles_per_sample=int(raw.get("cycles_per_sample", 32)),
            flush_samples=int(raw.get("flush_samples", 16)),
            owner=raw.get("owner", ""),
            description=raw.get("description", ""),
            reference_model=raw.get("reference_model", ""),
            path=path,
        )

    @staticmethod
    def list_effects() -> List[str]:
        return sorted(p.stem for p in EFFECT_CONFIGS.glob("*.json"))

    # -- parameter resolution --------------------------------------------

    def by_name(self, name: str) -> Param:
        for p in self.params:
            if p.name == name:
                return p
        known = ", ".join(p.name for p in self.params) or "(none)"
        raise ManifestError(f"{self.name} has no param {name!r}. Known: {known}")

    def resolve(self, overrides: Optional[Dict[str, Union[int, float, str]]] = None) -> List[int]:
        """Build the full 8-slot parameter bus, defaults filled in."""
        overrides = overrides or {}
        for key in overrides:
            self.by_name(key)  # raises with a helpful message if unknown

        bus = [0] * N_PARAMS
        for p in self.params:
            value = overrides.get(p.name, p.default)
            bus[p.index] = p.to_bits(value)
        return bus

    def natural(self, overrides: Optional[Dict[str, Union[int, float, str]]] = None) -> Dict[str, Union[int, float]]:
        """The same settings in natural units, which is what reference models take.

        A q16 slot comes back as a float in [0, 1] rather than its 0..65535 bit
        pattern, so a model can write ``x * (1 - mix)`` directly.
        """
        bus = self.resolve(overrides)
        out: Dict[str, Union[int, float]] = {}
        for p in self.params:
            bits = bus[p.index]
            value = bits / PARAM_MAX if p.scale == "q16" else bits
            value = value * p.factor + p.offset
            # Keep plain counts as ints so a model can index with them.
            if p.scale == "raw" and p.factor == 1.0 and p.offset == 0.0:
                value = int(value)
            out[p.name] = value
        return out

    def describe_params(self) -> str:
        if not self.params:
            return "  (no parameters)"
        return "\n".join("  " + p.describe() for p in self.params)


def parse_param_string(text: str) -> Dict[str, str]:
    """Parse ``"mix=0.5,feedback=0.4"`` into a dict, leaving values as strings."""
    result: Dict[str, str] = {}
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ManifestError(f"bad --param entry {item!r}, expected name=value")
        key, value = item.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def parse_param_items(items: Optional[Sequence[str]]) -> Dict[str, str]:
    """Accept repeated ``--param a=1 --param b=2`` and comma-joined forms alike."""
    result: Dict[str, str] = {}
    for item in items or []:
        result.update(parse_param_string(item))
    return result
