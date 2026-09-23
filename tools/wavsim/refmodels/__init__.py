"""Floating-point reference models — the specification each effect targets.

These are not ports of the RTL. They describe what the effect is *supposed* to
do, in float, so that comparing them against a member's fixed-point design says
something useful. A large error means either a design bug or a fixed-point
effect worth understanding; either way it is a question worth asking, which is
the whole point of `wavsim compare`.

Every model has the same signature::

    process(x, params, fs=48000) -> np.ndarray

``x`` is mono float64 in [-1, 1) and ``params`` holds *natural* values, not bus
bits: ``{"delay_samples": 12000, "feedback": 0.4, "mix": 0.5}``. A manifest names
its model with ``"reference_model": "wavsim.refmodels.delay:process"``.
"""

from __future__ import annotations

import importlib
from typing import Callable, Dict

import numpy as np


class ReferenceModelError(Exception):
    pass


def load(spec: str) -> Callable[..., np.ndarray]:
    """Resolve a ``"package.module:function"`` string into a callable."""
    if not spec:
        raise ReferenceModelError("no reference_model set in the manifest")
    if ":" not in spec:
        raise ReferenceModelError(
            f"reference_model {spec!r} must look like 'module:function'"
        )
    module_name, func_name = spec.split(":", 1)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ReferenceModelError(f"cannot import {module_name}: {exc}") from exc
    try:
        return getattr(module, func_name)
    except AttributeError as exc:
        raise ReferenceModelError(
            f"{module_name} has no attribute {func_name!r}"
        ) from exc


def get(params: Dict, name: str, default=None):
    """Fetch a parameter, tolerating a missing manifest entry."""
    value = params.get(name, default)
    if value is None:
        raise ReferenceModelError(f"reference model needs a {name!r} parameter")
    return value
