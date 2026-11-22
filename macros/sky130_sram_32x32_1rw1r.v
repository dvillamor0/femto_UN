// sky130_sram_32x32_1rw1r.v  --  MODELO FUNCIONAL DE SUSTITUCION (solo simulación)
//
// Escrito a mano siguiendo el comportamiento del modelo que genera OpenRAM
// (entradas registradas en posedge, lectura/escritura en negedge, dout valido DELAY
// despues del negedge y puesto a X T_HOLD despues del posedge): 32 palabras x 32 bits,
// puerto 0 RW con wmask de 4 bits, puerto 1 solo lectura.
//
// REEMPLAZAR por el .v que produce OpenRAM con open_ram/sram_32x32_1rw1r_config.py.
// El resto del diseño solo depende de los nombres de puerto y de que el array
// interno se llame `mem` (usado por el initial BENCH de femto_regfile_sram.v).

module sky130_sram_32x32_1rw1r(
`ifdef USE_POWER_PINS
    vccd1,
    vssd1,
`endif
    clk0, csb0, web0, wmask0, addr0, din0, dout0,
    clk1, csb1, addr1, dout1
);

    parameter NUM_WMASKS = 4;
    parameter DATA_WIDTH = 32;
    parameter ADDR_WIDTH = 5;
    parameter RAM_DEPTH  = 1 << ADDR_WIDTH;
    parameter DELAY      = 3;   // arbitrario, como en OpenRAM
    parameter VERBOSE    = 0;
    parameter T_HOLD     = 1;

`ifdef USE_POWER_PINS
    inout vccd1;
    inout vssd1;
`endif
    input                   clk0;
    input                   csb0;
    input                   web0;
    input [NUM_WMASKS-1:0]  wmask0;
    input [ADDR_WIDTH-1:0]  addr0;
    input [DATA_WIDTH-1:0]  din0;
    output [DATA_WIDTH-1:0] dout0;
    input                   clk1;
    input                   csb1;
    input [ADDR_WIDTH-1:0]  addr1;
    output [DATA_WIDTH-1:0] dout1;

    reg [DATA_WIDTH-1:0] mem [0:RAM_DEPTH-1];

    reg                   csb0_reg;
    reg                   web0_reg;
    reg [NUM_WMASKS-1:0]  wmask0_reg;
    reg [ADDR_WIDTH-1:0]  addr0_reg;
    reg [DATA_WIDTH-1:0]  din0_reg;
    reg [DATA_WIDTH-1:0]  dout0;

    reg                   csb1_reg;
    reg [ADDR_WIDTH-1:0]  addr1_reg;
    reg [DATA_WIDTH-1:0]  dout1;

    // ---- puerto 0 (RW) ----
    always @(posedge clk0) begin
        csb0_reg   = csb0;
        web0_reg   = web0;
        wmask0_reg = wmask0;
        addr0_reg  = addr0;
        din0_reg   = din0;
        #(T_HOLD) dout0 = {DATA_WIDTH{1'bx}};
        if (VERBOSE && !csb0_reg && web0_reg)
            $display($time, " Reading %m port0 addr0=%b dout0=%b", addr0_reg, mem[addr0_reg]);
        if (VERBOSE && !csb0_reg && !web0_reg)
            $display($time, " Writing %m port0 addr0=%b din0=%b wmask0=%b", addr0_reg, din0_reg, wmask0_reg);
    end

    always @(negedge clk0) begin : MEM_WRITE0
        if (!csb0_reg && !web0_reg) begin
            if (wmask0_reg[0]) mem[addr0_reg][7:0]   = din0_reg[7:0];
            if (wmask0_reg[1]) mem[addr0_reg][15:8]  = din0_reg[15:8];
            if (wmask0_reg[2]) mem[addr0_reg][23:16] = din0_reg[23:16];
            if (wmask0_reg[3]) mem[addr0_reg][31:24] = din0_reg[31:24];
        end
    end

    always @(negedge clk0) begin : MEM_READ0
        if (!csb0_reg && web0_reg)
            dout0 <= #(DELAY) mem[addr0_reg];
    end

    // ---- puerto 1 (solo lectura) ----
    always @(posedge clk1) begin
        csb1_reg  = csb1;
        addr1_reg = addr1;
        #(T_HOLD) dout1 = {DATA_WIDTH{1'bx}};
        if (VERBOSE && !csb1_reg)
            $display($time, " Reading %m port1 addr1=%b dout1=%b", addr1_reg, mem[addr1_reg]);
    end

    always @(negedge clk1) begin : MEM_READ1
        if (!csb1_reg)
            dout1 <= #(DELAY) mem[addr1_reg];
    end

endmodule
