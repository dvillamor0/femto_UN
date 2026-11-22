// femto_regfile_sram.v
// Banco de registros de FemtoRV32 (32 x 32 bits) sobre UNA macro OpenRAM
// sky130_sram_32x32_1rw1r: puerto 0 lectura/escritura + puerto 1 solo lectura
// ("dual access" de OpenRAM, pensado para bancos de registros).
//
// Interfaz lógica (independiente de los pines físicos de la macro):
//   lectura : rd_en=1 con rd_addr1 / rd_addr2 en el ciclo N -> rd_data1 / rd_data2
//             validos en el ciclo N+1 (la macro muestrea las direcciones en el flanco
//             que cierra el ciclo N; el dato se captura en el flanco que cierra N+1).
//             Fuera de ese ciclo los datos NO son validos (el modelo OpenRAM los pone a X).
//   escritura: wr_en=1 en el ciclo N -> escribe wr_data en wr_addr (palabra completa)
//             por el puerto 0.
//
// rs1 sale por el puerto 1 y rs2 por el puerto 0. rd_en y wr_en no deben activarse a
// la vez (el puerto 0 es compartido); en FemtoRV32 es así por construcción.
// x0 no lo gestiona este módulo: el núcleo no escribe en x0 y lo lee como 0.

module femto_regfile_sram (
    input  wire        clk,
    input  wire        rd_en,
    input  wire [4:0]  rd_addr1,
    output wire [31:0] rd_data1,
    input  wire [4:0]  rd_addr2,
    output wire [31:0] rd_data2,
    input  wire        wr_en,
    input  wire [4:0]  wr_addr,
    input  wire [31:0] wr_data
);

    wire [31:0] dout0, dout1;

    wire       csb0  = ~(rd_en | wr_en);       // activo en bajo
    wire       web0  = ~wr_en;                 // activo en bajo (1 = lectura)
    wire [4:0] addr0 = wr_en ? wr_addr : rd_addr2;
    wire       csb1  = ~rd_en;

    sky130_sram_32x32_1rw1r u_sram (
`ifdef USE_POWER_PINS
        .vccd1  (1'b1),
        .vssd1  (1'b0),
`endif
        // puerto 0: lectura/escritura (rs2 y escritura de rd)
        .clk0   (clk),
        .csb0   (csb0),
        .web0   (web0),
        .wmask0 (4'b1111),                     // palabra completa
        .addr0  (addr0),
        .din0   (wr_data),
        .dout0  (dout0),
        // puerto 1: solo lectura (rs1)
        .clk1   (clk),
        .csb1   (csb1),
        .addr1  (rd_addr1),
        .dout1  (dout1)
    );

    assign rd_data1 = dout1;
    assign rd_data2 = dout0;

`ifdef BENCH
    // Simulación: la SRAM arranca con X (igual que el silicio arranca con basura).
    // Se ponen a 0 los 32 registros, como hacía el initial del banco original.
    integer i;
    initial begin
        for (i = 0; i < 32; i = i + 1)
            u_sram.mem[i] = 0;
    end
`endif

endmodule
