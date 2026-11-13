// MappedSPIMultidrop.v
// Top multi-drop: W25Q (QSPI) + SPI RAM comparten SCK e IO0..IO3; cada chip tiene su CS_N.
// Instancia MappedQSPIFlash y MappedSPIRAM (sin modificar).
//
// Los CS_N de ambos modulos son quienes controlan el bus:
//   - "dueno del bus"  : CS_N = 0  -> selecciona SCK / IO que van a los pines
//   - arranque/fin     : la FSM espera CS_N = 0 (aceptado) y luego CS_N = 1 (terminado)
//
// Estructura en tres bloques:
//   1) entrada combinacional : next_state a partir de strobes y CS_N
//   2) maquina de control    : registro de estado
//   3) salida combinacional  : strobes, busy, mux de SCK / IO, tri-state
//
// Supuesto: un solo maestro (CPU) que no emite otro pedido mientras *_busy = 1
// y mantiene direccion / wdata estables hasta que termina.
//
// Todo opera en el flanco de bajada de clk, igual que los submodulos.

module MappedSPIMultidrop #(
    parameter FLASH_DIV = 2,     // semiperiodo de SCK de la flash, en ciclos de clk
    parameter RAM_DIV   = 10     // parametro divisor de MappedSPIRAM
)(
    input  wire        clk,
    input  wire        reset,                 // activo en bajo

    // lado CPU: flash
    input  wire        flash_rstrb,
    input  wire [19:0] flash_word_address,
    output wire [31:0] flash_rdata,
    output wire        flash_rbusy,

    // lado CPU: RAM
    input  wire        ram_rd,
    input  wire        ram_wr,
    input  wire [15:0] ram_word_address,
    input  wire [31:0] ram_wdata,
    output wire [31:0] ram_rdata,
    output wire        ram_rbusy,
    output wire        ram_wbusy,

    // pines SPI
    output wire        spi_sck,
    output wire        spi_cs_flash_n,
    output wire        spi_cs_ram_n,
    inout  wire [3:0]  spi_io                 // IO0 = MOSI/DI, IO1 = MISO/DO, IO2, IO3
);

    localparam [2:0] T_IDLE   = 3'd0,
                     T_REQ_F  = 3'd1,   // strobe retenido hacia la flash hasta CS_N = 0
                     T_RUN_F  = 3'd2,   // flash dueña del bus hasta CS_N = 1
                     T_REQ_RD = 3'd3,
                     T_REQ_WR = 3'd4,
                     T_RUN_RD = 3'd5,
                     T_RUN_WR = 3'd6;

    // ------------------------------------------------------------------
    // Submodulos
    // ------------------------------------------------------------------
    wire        f_rstrb_g, r_rd_g, r_wr_g;
    wire        f_rbusy, r_rbusy, r_wbusy;
    wire        f_sck, f_cs_n, r_sck, r_cs_n, r_mosi;
    wire [3:0]  f_io_o, f_io_oe;
    wire [3:0]  io_in;

    MappedQSPIFlash #(.DIV(FLASH_DIV)) u_flash (
        .clk(clk), .reset(reset),
        .rstrb(f_rstrb_g), .word_address(flash_word_address),
        .rdata(flash_rdata), .rbusy(f_rbusy),
        .CLK(f_sck), .CS_N(f_cs_n),
        .io_o(f_io_o), .io_oe(f_io_oe), .io_i(io_in)
    );

    MappedSPIRAM #(.divisor(RAM_DIV)) u_ram (
        .clk(clk), .reset(reset),
        .rd(r_rd_g), .wr(r_wr_g),
        .word_address(ram_word_address), .wdata(ram_wdata),
        .rdata(ram_rdata), .rbusy(r_rbusy), .wbusy(r_wbusy),
        .CLK(r_sck), .CS_N(r_cs_n),
        .MOSI(r_mosi), .MISO(io_in[1])
    );

    // ------------------------------------------------------------------
    // Bloque 1: entrada combinacional
    // ------------------------------------------------------------------
    reg [2:0] state, next_state;

    always @* begin
        next_state = state;
        case (state)
            T_IDLE:   if      (flash_rstrb) next_state = T_REQ_F;
                      else if (ram_wr)      next_state = T_REQ_WR;
                      else if (ram_rd)      next_state = T_REQ_RD;
            T_REQ_F:  if (!f_cs_n)          next_state = T_RUN_F;
            T_RUN_F:  if ( f_cs_n)          next_state = T_IDLE;
            T_REQ_RD: if (!r_cs_n)          next_state = T_RUN_RD;
            T_REQ_WR: if (!r_cs_n)          next_state = T_RUN_WR;
            T_RUN_RD: if ( r_cs_n)          next_state = T_IDLE;
            T_RUN_WR: if ( r_cs_n)          next_state = T_IDLE;
            default:                        next_state = T_IDLE;
        endcase
    end

    // ------------------------------------------------------------------
    // Bloque 2: maquina de control
    // ------------------------------------------------------------------
    always @(negedge clk) begin
        if (!reset) state <= T_IDLE;
        else        state <= next_state;
    end

    // ------------------------------------------------------------------
    // Bloque 3: salida combinacional
    // ------------------------------------------------------------------
    assign f_rstrb_g   = (state == T_REQ_F);
    assign r_rd_g      = (state == T_REQ_RD);
    assign r_wr_g      = (state == T_REQ_WR);

    // busy depende solo del estado: baja un ciclo despues de que CS_N sube,
    // asi la FSM ya esta en IDLE cuando el CPU puede emitir el siguiente pedido
    assign flash_rbusy = (state == T_REQ_F)  | (state == T_RUN_F);
    assign ram_rbusy   = (state == T_REQ_RD) | (state == T_RUN_RD);
    assign ram_wbusy   = (state == T_REQ_WR) | (state == T_RUN_WR);

    assign spi_cs_flash_n = f_cs_n;
    assign spi_cs_ram_n   = r_cs_n;

    // el CS_N en 0 indica quien es dueno del bus
    wire own_f = ~f_cs_n;
    wire own_r = ~r_cs_n;

    assign spi_sck = own_f ? f_sck :
                     own_r ? r_sck : 1'b0;

    // RAM: IO0 = MOSI, IO1 = MISO (entrada), IO2/IO3 = 1 (WP#, HOLD# inactivos)
    // reposo: IO2/IO3 a 1, IO0/IO1 liberados
    wire [3:0] io_o  = own_r ? {3'b111, r_mosi} :
                       own_f ? f_io_o           : 4'b1111;
    wire [3:0] io_oe = own_r ? 4'b1101 :
                       own_f ? f_io_oe          : 4'b1100;

    genvar i;
    generate
        for (i = 0; i < 4; i = i + 1) begin : g_io
            assign spi_io[i] = io_oe[i] ? io_o[i] : 1'bz;
        end
    endgenerate

    assign io_in = spi_io;

endmodule
