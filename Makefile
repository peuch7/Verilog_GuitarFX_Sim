# VerilogSim — wav in, SystemVerilog effect in the middle, wav out.
#
# Every target uses .venv automatically when it exists, so there is nothing to
# activate. Run `make setup` once, then `make help` to see what is here.

SHELL := /bin/bash

# Prefer the project venv, but only if its interpreter actually runs here. The
# repository is bind-mounted into the container, so a macOS or Windows .venv can
# be visible from Linux while being completely unusable; the same applies to a
# venv left behind after the repo was moved. Falling back to python3 is right in
# both cases, and inside the container the dependencies are system packages
# anyway.
VENV_PY := $(wildcard .venv/bin/python)
PY      := $(if $(VENV_PY),$(shell $(VENV_PY) -c '' >/dev/null 2>&1 && echo $(VENV_PY) || echo python3),python3)
export PYTHONPATH := tools$(if $(PYTHONPATH),:$(PYTHONPATH),)
WAVSIM  := $(PY) -m wavsim
COMPOSE := docker compose -f docker/compose.yml

# Overridable on the command line: make run effect=delay wav=path params="mix=0.5"
effect  ?= delay
signal  ?=
wav     ?=
out     ?=
params  ?=
config  ?= example_mesh
name    ?=

# Only pass a flag when the variable was actually set, so the CLI defaults apply.
EFFECT_ARG := --effect $(effect)
WAV_ARG    := $(if $(wav),--wav $(wav),)
OUT_ARG    := $(if $(out),--out $(out),)
PARAM_ARG  := $(if $(params),--param "$(params)",)
SIGNAL_ARG := $(if $(signal),--signal $(signal),)

.DEFAULT_GOAL := help
.PHONY: help setup doctor audio run compare crosscheck lint lint-strict chain \
        test test-icarus trace new-effect list info clean clean-audio \
        docker-build docker-run docker-test docker-shell

help:
	@echo "VerilogSim — simulate a guitar effect on real audio"
	@echo
	@echo "  make setup                    install the toolchain and .venv (macOS/Linux/WSL)"
	@echo "  make doctor                   check what is installed and what is missing"
	@echo "  make audio                    generate the test wavs into audio/input"
	@echo
	@echo "  make run effect=delay         wav -> effect -> wav"
	@echo "  make compare effect=delay     RTL vs the float reference model"
	@echo "  make crosscheck effect=delay  prove Verilator and Icarus agree exactly"
	@echo "  make chain config=example_mesh   several effects in series"
	@echo "  make trace effect=delay       write a VCD to open in gtkwave"
	@echo
	@echo "  make lint                     verilator --lint-only over every effect"
	@echo "  make test                     the pytest suite"
	@echo "  make new-effect name=tremolo  scaffold an effect that runs immediately"
	@echo "  make list / make info effect=delay"
	@echo
	@echo "  make docker-build / docker-run / docker-test / docker-shell"
	@echo
	@echo "  Variables: effect= wav= out= params=\"mix=0.5,feedback=0.4\" signal= config= name="

# ------------------------------------------------------------------ setup

setup:
	@bash scripts/bootstrap.sh

doctor:
	@$(PY) scripts/doctor.py

audio:
	@$(WAVSIM) gen-audio

# ------------------------------------------------------------------ running

run:
	@$(WAVSIM) run $(EFFECT_ARG) $(WAV_ARG) $(OUT_ARG) $(PARAM_ARG) $(SIGNAL_ARG)

compare:
	@$(WAVSIM) compare $(EFFECT_ARG) $(WAV_ARG) $(PARAM_ARG) $(SIGNAL_ARG)

crosscheck:
	@$(WAVSIM) crosscheck $(EFFECT_ARG) $(PARAM_ARG) $(SIGNAL_ARG)

chain:
	@$(WAVSIM) chain --config $(config) $(WAV_ARG) $(OUT_ARG)

# Capped at a short burst: a VCD of a full clip is hundreds of MB and unusable
# in a waveform viewer. Override with samples=<n> when you need more.
samples ?= 2000
trace:
	@mkdir -p build/trace
	@$(WAVSIM) run $(EFFECT_ARG) $(PARAM_ARG) --signal impulse \
	    --max-samples $(samples) --trace build/trace/$(effect).vcd
	@echo "open with: gtkwave build/trace/$(effect).vcd"

# ------------------------------------------------------------------ checking

# lint covers every effect unless one is named on the command line. `effect` has
# a default for run/compare, so testing $(origin) is what distinguishes "the user
# asked for delay" from "nobody said anything".
LINT_EFFECT := $(if $(filter command line,$(origin effect)),--effect $(effect),)

lint:
	@$(WAVSIM) lint $(LINT_EFFECT)

lint-strict:
	@$(WAVSIM) lint --strict $(LINT_EFFECT)

test:
	@$(PY) -m pytest

test-icarus:
	@$(PY) -m pytest --backend icarus

# ------------------------------------------------------------------ authoring

new-effect:
	@test -n "$(name)" || { echo "usage: make new-effect name=<effect>"; exit 2; }
	@$(WAVSIM) new-effect $(name)

list:
	@$(WAVSIM) list

info:
	@$(WAVSIM) info $(effect)

# ------------------------------------------------------------------ container

docker-build:
	@$(COMPOSE) build

docker-run:
	@$(COMPOSE) run --rm sim wavsim run $(EFFECT_ARG) $(WAV_ARG) $(OUT_ARG) $(PARAM_ARG) $(SIGNAL_ARG)

docker-test:
	@$(COMPOSE) run --rm sim python3 -m pytest

docker-shell:
	@$(COMPOSE) run --rm sim bash

# ------------------------------------------------------------------ cleaning

clean:
	@rm -rf build
	@find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	@echo "removed build artifacts"

clean-audio:
	@rm -rf audio/output
	@echo "removed generated audio"
