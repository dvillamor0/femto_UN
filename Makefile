export PATH := $(HOME)/opt/iverilog-12/bin:$(PATH)

TT_TOOLS = tt
TT_TOOL = $(TT_TOOLS)/tt_tool.py
PDK_ROOT ?= $(HOME)/.volare
PDK ?= sky130A
IMAGE = localhost/femto-librelane:2.4.2
PROJECT_ROOT = $(CURDIR)

.PHONY: all user-config harden submission clean test version

all: user-config harden submission

user-config:
	podman run --rm \
		-v "$(PROJECT_ROOT):/work:Z" \
		-v "$(PDK_ROOT):/pdk:ro" \
		-e PDK_ROOT=/pdk -e PDK="$(PDK)" \
		-e HOME=/tmp/container-home \
		-w /work "$(IMAGE)" \
		python3 $(TT_TOOL) --create-user-config --no-docker

harden:
	podman run --rm \
		-v "$(PROJECT_ROOT):/work:Z" \
		-v "$(PDK_ROOT):/pdk:ro" \
		-e PDK_ROOT=/pdk -e PDK="$(PDK)" \
		-e HOME=/tmp/container-home \
		-w /work "$(IMAGE)" \
		python3 $(TT_TOOL) --harden --no-docker

submission:
	podman run --rm \
		-v "$(PROJECT_ROOT):/work:Z" \
		-v "$(PDK_ROOT):/pdk:ro" \
		-e PDK_ROOT=/pdk -e PDK="$(PDK)" \
		-e HOME=/tmp/container-home \
		-w /work "$(IMAGE)" \
		python3 $(TT_TOOL) --create-tt-submission --no-docker
	cp ./tt_submission/tt_um_femto.v .

clean:
	rm -rf ./runs ./tt-submission

.PHONY: test

test:
	$(MAKE) -C test $(filter-out test,$(MAKECMDGOALS))

%:
	@:

version:
	which iverilog
	iverilog -V | head -n 1
	which vvp
	vvp -V | head -n 1