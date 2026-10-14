export PATH := $(HOME)/opt/iverilog-12/bin:$(PATH)

TT_TOOLS = tt
TT_TOOL = $(TT_TOOLS)/tt_tool.py
PDK_ROOT ?= $(HOME)/.volare
PDK ?= sky130A


all:
	@test -f $(TT_TOOL) || { \
		echo "ERROR: no se encuentra $(TT_TOOL)"; \
		echo "Clona tt-support-tools en ./tt"; \
		exit 1; \
	}
	PDK_ROOT="$(PDK_ROOT)" PDK="$(PDK)" python3 $(TT_TOOL) --create-user-config
	PDK_ROOT="$(PDK_ROOT)" PDK="$(PDK)" python3 $(TT_TOOL) --harden
	PDK_ROOT="$(PDK_ROOT)" PDK="$(PDK)" python3 $(TT_TOOL) --create-tt-submission
	cp ./tt-submission/tt_um_femto.v .

clean:
	rm -rf ./runs ./tt-submission

.PHONY: all clean test

test:
	$(MAKE) -f test/Makefile.test

version:
	which iverilog
	iverilog -V | head -n 1
	which vvp
	vvp -V | head -n 1
