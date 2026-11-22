// sky130_sram_32x32_1rw1r_fpga.v
// Sustituto SINTETIZABLE (FPGA) de la macro OpenRAM sky130_sram_32x32_1rw1r: misma
// interfaz y mismo comportamiento ciclo a ciclo (lectura síncrona), sin retardos ni X.
// Solo para el flujo de la Colorlight i9 (make fpga-bit); en el ASIC se usa la macro
// real (src/sky130_sram_32x32_1rw1r_bb.v + macros/).
module sky130_sram_32x32_1rw1r (
    input  wire        clk0,
    input  wire        csb0,
    input  wire        web0,
    input  wire [3:0]  wmask0,
    input  wire [4:0]  addr0,
    input  wire [31:0] din0,
    output reg  [31:0] dout0,
    input  wire        clk1,
    input  wire        csb1,
    input  wire [4:0]  addr1,
    output reg  [31:0] dout1
);
    reg [31:0] mem [0:31];

    always @(posedge clk0) begin
        if (!csb0) begin
            if (!web0) begin
                if (wmask0[0]) mem[addr0][7:0]   <= din0[7:0];
                if (wmask0[1]) mem[addr0][15:8]  <= din0[15:8];
                if (wmask0[2]) mem[addr0][23:16] <= din0[23:16];
                if (wmask0[3]) mem[addr0][31:24] <= din0[31:24];
            end else begin
                dout0 <= mem[addr0];
            end
        end
    end

    always @(posedge clk1) begin
        if (!csb1) dout1 <= mem[addr1];
    end
endmodule
