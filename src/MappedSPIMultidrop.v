// MappedSPIMultidrop.v
// Controlador UNICO multi-drop (unión de MappedQSPIFlash + MappedSPIMultidrop):
// flash W25Q (solo QSPI, 0xEB) + SPI RAM (solo SPI, 0x03 / 0x02).
// Comparten SCK, IO0..IO3 y todo el motor (registro de desplazamiento, divisor, contador);
// cada chip tiene su propio CS_N.
//
//   flash : 0xEB | addr[23:0] (4 lineas) | modo 0x00 (4 lineas) | 4 dummy | 32 bits (4 lineas)
//           = 8 + 6 + 2 + 4 + 8 = 28 ciclos de SCK
//   RAM   : 0x03/0x02 | 0x00 | addr[15:0] | 32 bits (1 linea, IO0 = MOSI, IO1 = MISO)
//           = 32 + 32 = 64 ciclos de SCK
//
// Estructura en tres bloques:
//   1) entrada combinacional : decodifica strobes y eventos (half_done, rise/fall_step, last_cyc),
//                              calcula las habilitaciones de carga / desplazamiento de sh
//   2) maquina de control    : registros de fase (ph, act_f, act_r, wr), contador de ciclos,
//                              divisor, SCK, muestreo y registro de desplazamiento sh
//   3) salida combinacional  : CS_N, busy, SCK, io_o, io_oe, rdata
//
// Ahorro de area respecto a MappedQSPIFlash + MappedSPIRAM + top:
//   * un unico registro de 32 bits (sh) hace de salida (cabecera / wdata) y de entrada (rdata)
//   * un unico divisor, un unico contador de ciclos (5 bits) y un unico SCK
//   * no hay estados REQ/START/WAIT: el strobe se muestrea directamente en reposo
//   * el estado es (ph, act_f, act_r): CS_N sale directo de los flops (sin glitches)
//
// Supuestos: un solo maestro (CPU) que no emite otro pedido mientras *_busy = 1 y mantiene
// ram_wdata estable hasta que termina una escritura. Las direcciones se muestrean al aceptar
// el strobe. flash_rdata / ram_rdata comparten registro: cada una es valida cuando su
// *_busy baja y hasta el siguiente pedido (el CPU debe capturarla, p.ej. FemtoRV latchea instr).
//
// Todo opera en el flanco de bajada de clk, igual que los modulos originales.

module MappedSPIMultidrop #(
    parameter FLASH_DIV = 2,     // semiperiodo de SCK de la flash, en ciclos de clk (>= 1)
    parameter RAM_DIV   = 5      // semiperiodo de SCK de la RAM,   en ciclos de clk (>= 1)
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
    // bus de datos separado en salida / habilitacion / entrada (sin inout): se conecta directo a
    // uio_out / uio_oe / uio_in de Tiny Tapeout.  IO0 = MOSI/DI, IO1 = MISO/DO, IO2, IO3
    output wire [3:0]  spi_io_o,
    output wire [3:0]  spi_io_oe,              // 1 = el maestro maneja el pin
    input  wire [3:0]  spi_io_i
);

    // fases (compartidas por flash y RAM)
    localparam [1:0] P_CMD  = 2'd0,   // flash: opcode (8 ciclos, 1 linea) | RAM: cabecera (32 ciclos)
                     P_ADDR = 2'd1,   // flash: direccion (6 ciclos, 4 lineas)
                     P_TURN = 2'd2,   // flash: 2 ciclos de modo (se manejan) + 4 dummy (liberado)
                     P_DATA = 2'd3;   // flash: 8 ciclos | RAM: 32 ciclos

    localparam MAXD = (FLASH_DIV > RAM_DIV) ? FLASH_DIV : RAM_DIV;
    localparam W    = (MAXD > 2) ? $clog2(MAXD) : 1;
    localparam [W-1:0] FLASH_M1 = FLASH_DIV - 1;
    localparam [W-1:0] RAM_M1   = RAM_DIV   - 1;

    // ------------------------------------------------------------------
    // Registros (bloque 2)
    // ------------------------------------------------------------------
    reg          act_f;     // transaccion de flash en curso  (CS_N flash = ~act_f)
    reg          act_r;     // transaccion de RAM en curso    (CS_N RAM   = ~act_r)
    reg          wr;        // la transaccion de RAM es escritura
    reg  [1:0]   ph;        // fase
    reg  [4:0]   cnt;       // ciclos de SCK completados dentro de la fase
    reg  [W-1:0] div_cnt;   // divisor de SCK
    reg          sck_q;     // SCK
    reg          smp_q;     // 1 ciclo despues de cada flanco de subida de SCK
    reg  [31:0]  sh;        // registro de desplazamiento comun

    wire [3:0]   io_in;
    assign io_in = spi_io_i;

    // ------------------------------------------------------------------
    // Bloque 1: entrada combinacional
    // ------------------------------------------------------------------
    reg        idle, start;
    reg        half_done, rise_step, fall_step, last_cyc;
    reg        p_cmd, p_data;
    reg        ld, ldw, smp1, smp4, sh1, sh4, fill;
    reg [1:0]  next_ph;

    always @* begin
        idle      = ~(act_f | act_r);
        start     = idle & (flash_rstrb | ram_wr | ram_rd);        // prioridad: flash > wr > rd

        half_done = (div_cnt == (act_r ? RAM_M1 : FLASH_M1));
        rise_step = half_done & ~sck_q;
        fall_step = half_done &  sck_q;

        p_cmd     = (ph == P_CMD);
        p_data    = (ph == P_DATA);

        if (act_r) last_cyc = (cnt == 5'd31);                       // RAM: 32 ciclos por fase
        else       last_cyc = (cnt[2:0] == (((ph == P_ADDR) || (ph == P_TURN)) ? 3'd5 : 3'd7));

        next_ph   = act_r ? ~ph : (ph + 2'd1);                      // RAM: CMD <-> DATA

        ld        = start;                                          // cargar cabecera
        ldw       = fall_step & last_cyc & act_r & p_cmd & wr;      // RAM wr: recargar con wdata
        smp1      = smp_q & act_r & p_data & ~wr;                   // RAM rd: entra 1 bit
        smp4      = smp_q & act_f & p_data;                         // flash : entra 1 nibble
        sh1       = (fall_step & (act_f ? p_cmd : (p_cmd | wr))) | smp1;  // sale / entra 1 bit
        sh4       = (fall_step & act_f & (ph == P_ADDR)) | smp4;          // sale / entra 1 nibble
        fill      = smp1 & io_in[1];
    end

    // ------------------------------------------------------------------
    // Bloque 2: maquina de control (secuencial, flanco de bajada)
    // ------------------------------------------------------------------
    always @(negedge clk) begin
        if (!reset) begin
            act_f   <= 1'b0;
            act_r   <= 1'b0;
            wr      <= 1'b0;
            ph      <= P_CMD;
            cnt     <= 5'd0;
            div_cnt <= {W{1'b0}};
            sck_q   <= 1'b0;
            smp_q   <= 1'b0;
        end
        else if (idle) begin
            // reposo: divisor y SCK detenidos, cada transferencia arranca en fase conocida
            cnt     <= 5'd0;
            div_cnt <= {W{1'b0}};
            sck_q   <= 1'b0;
            smp_q   <= 1'b0;
            if (start) begin
                act_f <= flash_rstrb;
                act_r <= ~flash_rstrb;
                wr    <= ram_wr;
            end
        end
        else begin
            smp_q <= rise_step;
            if (half_done) begin
                div_cnt <= {W{1'b0}};
                sck_q   <= ~sck_q;
            end
            else begin
                div_cnt <= div_cnt + 1'b1;
            end
            if (fall_step) begin
                cnt <= last_cyc ? 5'd0 : (cnt + 5'd1);
                if (last_cyc) begin
                    ph <= next_ph;                       // tras DATA vuelve a P_CMD
                    if (p_data) begin
                        act_f <= 1'b0;                   // CS_N sube con SCK ya en bajo
                        act_r <= 1'b0;
                    end
                end
            end
        end
    end

    // registro de desplazamiento comun (sin reset: se recarga entero al iniciar)
    always @(negedge clk) begin
        if      (ld)  sh <= flash_rstrb ? {8'hEB, 2'b00, flash_word_address, 2'b00}
                                        : {6'b000000, 1'b1, ~ram_wr, 8'h00, ram_word_address};
        else if (ldw) sh <= ram_wdata;
        else if (sh1) sh <= {sh[30:0], fill};
        else if (sh4) sh <= {sh[27:0], io_in};
    end

    // ------------------------------------------------------------------
    // Bloque 3: salida combinacional
    // ------------------------------------------------------------------
    // nib : fases de 4 lineas manejadas por el maestro (direccion y los 2 ciclos de modo)
    // rel : bus liberado (dummy y datos de la flash)
    wire nib = act_f & ((ph == P_ADDR) | (ph == P_TURN));
    wire rel = act_f & ((ph == P_DATA) | ((ph == P_TURN) & (cnt[2] | cnt[1])));

    assign spi_sck        = sck_q;
    assign spi_cs_flash_n = ~act_f;
    assign spi_cs_ram_n   = ~act_r;

    assign flash_rbusy    = act_f;
    assign ram_rbusy      = act_r & ~wr;
    assign ram_wbusy      = act_r &  wr;

    // IO2/IO3 a 1 (WP#/HOLD# inactivos) salvo cuando la flash los maneja o los lee;
    // en reposo IO0/IO1 liberados
    wire [3:0] io_o  = nib ? sh[31:28] : {3'b111, sh[31]};
    wire [3:0] io_oe = {~rel, ~rel, nib & ~rel, (act_f | act_r) & ~rel};

    assign spi_io_o  = io_o;
    assign spi_io_oe = io_oe;

    // la flash entrega primero el byte menos significativo -> hay que reordenar
    assign flash_rdata = {sh[7:0], sh[15:8], sh[23:16], sh[31:24]};
    assign ram_rdata   = sh;

endmodule
