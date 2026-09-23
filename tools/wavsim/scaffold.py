"""`wavsim new-effect` — everything a member needs to start, in one command.

Generates a passthrough RTL module, its harness wrapper, a manifest, a reference
model stub and a test stub. The passthrough matters: the effect runs end to end
through the simulator from the first minute, so the owner is editing something
that already works rather than debugging a build at the same time as a design.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .paths import EFFECT_CONFIGS, EFFECTS_RTL, TESTS_DIR, TOOLS_DIR


class ScaffoldError(Exception):
    pass


@dataclass
class ParamSpec:
    name: str
    index: int
    default: object = 0
    scale: str = "raw"
    min: Optional[int] = None
    max: Optional[int] = None
    unit: str = ""
    doc: str = ""
    factor: float = 1.0
    offset: float = 0.0
    width: int = 16

    def to_json(self) -> Dict:
        out: Dict = {"name": self.name, "index": self.index, "default": self.default,
                     "scale": self.scale}
        if self.min is not None:
            out["min"] = self.min
        if self.max is not None:
            out["max"] = self.max
        if self.unit:
            out["unit"] = self.unit
        if self.factor != 1.0:
            out["factor"] = self.factor
        if self.offset != 0.0:
            out["offset"] = self.offset
        if self.doc:
            out["doc"] = self.doc
        return out


RTL_TEMPLATE = """`timescale 1ns / 1ps
//
// {name}.sv
//
// TODO ({owner_or_you}): implement {description}
//
// Right now this is a passthrough, so `wavsim run --effect {name}` already works
// end to end. Replace the body below; keep the port list and the valid protocol.
//
// The protocol the harness relies on:
//   * sample_in_valid pulses high for one clock per input sample.
//   * Raise sample_out_valid for one clock per output sample you produce.
//   * Latency is yours to choose. If you need more than {cycles} clocks between
//     samples, raise "cycles_per_sample" in configs/effects/{name}.json.
//
module {name} (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [23:0]              sample_in,
    input  logic                            sample_in_valid,
{param_ports}
    output logic signed [23:0]              sample_out,
    output logic                            sample_out_valid
);

    // TODO: replace this passthrough with the real signal path.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            sample_out       <= '0;
            sample_out_valid <= 1'b0;
        end else begin
            sample_out       <= sample_in;
            sample_out_valid <= sample_in_valid;
        end
    end

endmodule
"""

WRAPPER_TEMPLATE = """`timescale 1ns / 1ps
`include "effect_contract.svh"

// {name}_top — harness wrapper for {name}.sv.
//
// No DSP here. It presents the standard interface from
// rtl/common/effect_contract.svh and slices the parameter bus onto the port
// names {name}.sv uses. Slot numbers match configs/effects/{name}.json.
//
{slot_comment}

module {name}_top (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [`SAMPLE_WIDTH-1:0] sample_in,
    input  logic                            sample_in_valid,
    input  logic [`PARAM_BUS_WIDTH-1:0]     params,

    output logic signed [`SAMPLE_WIDTH-1:0] sample_out,
    output logic                            sample_out_valid
);

    {name} u_{name} (
        .clk              (clk),
        .rst_n            (rst_n),
        .sample_in        (sample_in),
        .sample_in_valid  (sample_in_valid),
{param_binds}
        .sample_out       (sample_out),
        .sample_out_valid (sample_out_valid)
    );

endmodule
"""

REFMODEL_TEMPLATE = '''"""Reference model: {name}.

TODO: describe what {name} is supposed to do, then implement it in float here.
This model is the specification the RTL is measured against by
`wavsim compare --effect {name}`, so it is worth writing before the RTL.

Parameters arrive in natural units: {param_names}
"""

from __future__ import annotations

import numpy as np

from . import get


def process(x: np.ndarray, params: dict, fs: int = 48000) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64).reshape(-1)
{param_reads}
    # TODO: implement. Passthrough until then.
    return x.copy()
'''

TEST_TEMPLATE = '''"""Tests for the {name} effect.

These run the real RTL through the real harness, so they fail for design bugs and
for harness regressions alike. Start with the two below and add assertions that
describe what {name} must do.
"""

import numpy as np
import pytest

from wavsim import signals
from wavsim.manifest import Manifest
from wavsim.pipeline import process_array

EFFECT = "{name}"


@pytest.fixture(scope="module")
def manifest():
    return Manifest.load(EFFECT)


def test_silence_in_silence_out(manifest, backend):
    """Nothing in, nothing out. Catches uninitialised state and stray offsets."""
    x = signals.silence(0.05)
    y, _ = process_array(manifest, x, backend=backend)
    assert np.max(np.abs(y)) == 0.0


def test_output_count_matches_input(manifest, backend):
    """One sample_out_valid per sample_in_valid, which the harness counts."""
    x = signals.sine(1000.0, 0.05)
    y, result = process_array(manifest, x, backend=backend)
    assert result.samples_out == result.samples_in


@pytest.mark.skip(reason="TODO: implement {name}.sv, then describe its behaviour here")
def test_{name}_behaviour(manifest, backend):
    raise NotImplementedError
'''


def _param_ports(params: List[ParamSpec]) -> str:
    if not params:
        return ""
    lines = []
    for p in params:
        comment = f"  // {p.doc}" if p.doc else ""
        lines.append(f"    input  logic [{p.width - 1}:0]{'':<18}{p.name},{comment}")
    return "\n".join(lines) + "\n"


def _param_binds(params: List[ParamSpec]) -> str:
    if not params:
        return ""
    # 16 keeps the parameter binds lined up with .sample_out_valid above them.
    width = max([16] + [len(p.name) for p in params])
    lines = [
        f"        .{p.name:<{width}} (`PARAM({p.index})),"
        for p in params
    ]
    return "\n".join(lines) + "\n"


def _slot_comment(params: List[ParamSpec]) -> str:
    if not params:
        return "//   (no parameters)"
    width = max(len(p.name) for p in params)
    lines = []
    for p in params:
        detail = p.doc or (f"{p.scale} value" if p.scale != "raw" else "raw value")
        lines.append(f"//   slot {p.index}  {p.name:<{width}}  {detail}")
    return "\n".join(lines)


def create_effect(
    name: str,
    params: Optional[List[ParamSpec]] = None,
    owner: str = "",
    description: str = "",
    cycles_per_sample: int = 32,
    reference_model: Optional[str] = None,
    force: bool = False,
) -> List[Path]:
    """Write every file a new effect needs. Returns the paths created."""
    if not name.isidentifier():
        raise ScaffoldError(
            f"{name!r} is not a usable module name; use letters, digits and underscores"
        )
    params = params or []
    for i, p in enumerate(params):
        if p.index is None:
            p.index = i
    if len(params) > 8:
        raise ScaffoldError("the parameter bus has 8 slots; trim the list")

    rtl_dir = EFFECTS_RTL / name
    created: List[Path] = []

    targets = {
        rtl_dir / f"{name}.sv": RTL_TEMPLATE.format(
            name=name,
            owner_or_you=owner or "you",
            description=description or f"the {name} effect",
            cycles=cycles_per_sample,
            param_ports=_param_ports(params),
        ),
        rtl_dir / f"{name}_top.sv": WRAPPER_TEMPLATE.format(
            name=name,
            slot_comment=_slot_comment(params),
            param_binds=_param_binds(params),
        ),
        EFFECT_CONFIGS / f"{name}.json": json.dumps(
            {
                "name": name,
                "top": f"{name}_top",
                "owner": owner,
                "description": description or f"TODO: describe {name}.",
                "sources": [
                    f"rtl/effects/{name}/{name}.sv",
                    f"rtl/effects/{name}/{name}_top.sv",
                ],
                "cycles_per_sample": cycles_per_sample,
                "flush_samples": 16,
                "params": [p.to_json() for p in params],
                "reference_model": reference_model
                if reference_model is not None
                else f"wavsim.refmodels.{name}:process",
            },
            indent=2,
        )
        + "\n",
        TOOLS_DIR / "wavsim" / "refmodels" / f"{name}.py": REFMODEL_TEMPLATE.format(
            name=name,
            param_names=", ".join(p.name for p in params) or "(none yet)",
            param_reads="\n".join(
                f'    {p.name} = get(params, "{p.name}", {p.default!r})' for p in params
            )
            or "    # no parameters yet",
        ),
        TESTS_DIR / f"test_{name}.py": TEST_TEMPLATE.format(name=name),
    }

    rtl_dir.mkdir(parents=True, exist_ok=True)
    for path, content in targets.items():
        if path.exists() and not force:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        created.append(path)
    return created
