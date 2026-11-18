export PATH := $(HOME)/opt/iverilog-12/bin:$(PATH)

TT_TOOLS = tt
TT_TOOL = $(TT_TOOLS)/tt_tool.py
PDK_ROOT ?= $(HOME)/.volare
PDK ?= sky130A
IMAGE = localhost/femto-librelane:2.4.2
PROJECT_ROOT = $(CURDIR)

.PHONY: all user-config harden submission clean test version fpga-synth fpga-pnr fpga-bit fpga-prog fpga-flash fpga-clean

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

clean: fpga-clean
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

# ----------------------------------------------------------------------------
# FPGA: Colorlight i9 v7.2 (Lattice ECP5 LFE5U-45F-6BG381C)
#   make fpga-bit     -> sintetiza, place&route y genera build/fpga/top_fpga.bit
#   make fpga-prog    -> carga el bitstream en la SRAM (volatil, se pierde al apagar)
#   make fpga-flash   -> lo graba en la flash SPI de la placa (persistente)
# Se sintetiza el RTL de src/ (modulo tt_um_femto, definido en src/femto.v) con el
# wrapper config/top_fpga.v. NO se usa ./tt_um_femto.v de la raiz: ese archivo es
# la netlist a nivel de compuertas de sky130 y no es sintetizable para ECP5.
# Herramientas: yosys, nextpnr-ecp5, ecppack (prjtrellis), openFPGALoader.
# ----------------------------------------------------------------------------
FPGA_DIR     = build/fpga
FPGA_TOP     = top_fpga
FPGA_SRC     = src/femto.v src/femtorv32_quark.v src/perip_uart.v src/uart.v \
               src/MappedSPIMultidrop.v config/top_fpga.v
FPGA_LPF     = config/colorlight_i9.lpf
FPGA_DEVICE  = --45k --package CABGA381 --speed 6
FPGA_FREQ    = 25
# El RTL tiene un lazo combinacional (MappedSPIMultidrop <-> CPU.writeBack/aluWr);
# sin --ignore-loops nextpnr aborta el analisis de timing.
FPGA_PNR_OPT = --ignore-loops
FPGA_BOARD   = colorlight-i9

fpga-synth: $(FPGA_DIR)/$(FPGA_TOP).json
fpga-pnr:   $(FPGA_DIR)/$(FPGA_TOP).config
fpga-bit:   $(FPGA_DIR)/$(FPGA_TOP).bit

$(FPGA_DIR)/$(FPGA_TOP).json: $(FPGA_SRC)
	@mkdir -p $(FPGA_DIR)
	yosys -q -l $(FPGA_DIR)/yosys.log \
		-p "read_verilog $(FPGA_SRC); synth_ecp5 -top $(FPGA_TOP) -json $@"

$(FPGA_DIR)/$(FPGA_TOP).config: $(FPGA_DIR)/$(FPGA_TOP).json $(FPGA_LPF)
	nextpnr-ecp5 $(FPGA_DEVICE) --freq $(FPGA_FREQ) $(FPGA_PNR_OPT) \
		--json $< --lpf $(FPGA_LPF) --textcfg $@ \
		--log $(FPGA_DIR)/nextpnr.log

$(FPGA_DIR)/$(FPGA_TOP).bit: $(FPGA_DIR)/$(FPGA_TOP).config
	ecppack --compress $< $@

fpga-prog: $(FPGA_DIR)/$(FPGA_TOP).bit
	openFPGALoader -b $(FPGA_BOARD) $<

fpga-flash: $(FPGA_DIR)/$(FPGA_TOP).bit
	openFPGALoader -b $(FPGA_BOARD) -f $<

fpga-clean:
	rm -rf ./build
