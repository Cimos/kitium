# Kitium dev loop. Requires Docker (Engine in WSL) — see DESIGN.md §9.
#
#   make fixtures   # download KiCad's Altium test fixtures into ./fixtures
#   make image      # build the Kitium container locally
#   make spike      # Phase 0: convert the eDP fixture + run pre-flight guards
#   make gate       # run the full entrypoint (convert -> kibot -> report) on fixtures
#   make test       # static checks (shellcheck + py_compile + BOM smoke test)
#   make act        # middle loop: run the PR workflow locally via nektos/act

IMAGE ?= kitium:dev
BASE  ?= kicad/kicad:10.0   # pcb import is KiCad 10-only; official image + pip KiBot
BOARD ?= fixtures/eDP_adapter_dvt1_source/eDP_adapter_dvt1.PcbDoc
DRUN  := docker run --rm -v $(PWD):/work -w /work --entrypoint bash $(IMAGE)

.PHONY: fixtures image spike gate test act shellcheck

fixtures:
	bash scripts/fetch_fixtures.sh

image:
	docker build --build-arg KICAD_IMAGE=$(BASE) -t $(IMAGE) .

# Phase 0 de-risk: does kicad-cli pcb import produce a loadable, non-empty board?
spike: fixtures image
	mkdir -p fixtures/out
	$(DRUN) -c '\
	  kicad-cli pcb import --format altium \
	    --output /work/fixtures/out/spike.kicad_pcb \
	    --report-format json --report-file /work/fixtures/out/spike-import.json \
	    /work/$(BOARD) && \
	  python3 scripts/pcb_inspect.py /work/fixtures/out/spike.kicad_pcb --assert'

# Full gate over the fixtures, exercising the real entrypoint.
gate: fixtures image
	docker run --rm -v $(PWD):/work -w /work \
	  -e INPUT_BOARDS_GLOB='fixtures/**/*.PcbDoc' \
	  -e INPUT_DRC=report \
	  -e INPUT_OUTPUT_DIR=fixtures/kitium-out \
	  $(IMAGE)

test: shellcheck
	python3 -m py_compile scripts/*.py
	@echo "OK: python compiles"

shellcheck:
	shellcheck scripts/*.sh

act:
	act pull_request
