// sky130_sram_32x32_1rw1r_bb.v
// Blackbox de síntesis (Yosys) de la macro OpenRAM sky130_sram_32x32_1rw1r
// (1 puerto RW + 1 puerto R). Mismos puertos que macros/sky130_sram_32x32_1rw1r.lef.
// Verificar contra el .v/.lef que genere OpenRAM (p.ej. si aparece spare_wen0).
// NO usar en simulación: allí se compila macros/sky130_sram_32x32_1rw1r.v.
/* verilator lint_off UNUSED */
(* blackbox *)
module sky130_sram_32x32_1rw1r (
`ifdef USE_POWER_PINS
    inout  wire        vccd1,
    inout  wire        vssd1,
`endif
    // puerto 0: lectura/escritura
    input  wire        clk0,
    input  wire        csb0,        // activo en bajo
    input  wire        web0,        // activo en bajo
    input  wire [3:0]  wmask0,      // máscara por byte, activa en alto
    input  wire [4:0]  addr0,
    input  wire [31:0] din0,
    output wire [31:0] dout0,
    // puerto 1: solo lectura
    input  wire        clk1,
    input  wire        csb1,        // activo en bajo
    input  wire [4:0]  addr1,
    output wire [31:0] dout1
);
endmodule
/* verilator lint_on UNUSED */
