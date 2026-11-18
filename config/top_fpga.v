// top_fpga.v
// Wrapper para sintetizar tt_um_femto en la Colorlight i9 (Lattice ECP5)
// Conecta el bus bidireccional uio[3:0] con buffers tri-estado reales.

module top_fpga (
    input  wire       clk,      // Oscilador de 25 MHz de la Colorlight i9 (pin P3)
    input  wire       rst_n,    // Boton de reset activo en bajo (pin K18)

    // Interfaz UART
    input  wire       uart_rx,  // RXD desde el conversor USB-UART
    output wire       uart_tx,  // TXD hacia el conversor USB-UART

    // LED de estado
    output wire       led,      // Salida LEDS de femto

    // Bus SPI / QSPI Multi-drop hacia Flash y RAM
    output wire       spi_sck,
    output wire       spi_cs_flash_n,
    output wire       spi_cs_ram_n,
    inout  wire [3:0] spi_io    // IO0=MOSI/DI, IO1=MISO/DO, IO2=WP#, IO3=HOLD#
);

    // Cables internos hacia el modulo tt_um_femto
    wire [7:0] ui_in;
    wire [7:0] uo_out;
    wire [7:0] uio_in;
    wire [7:0] uio_out;
    wire [7:0] uio_oe;

    // ------------------------------------------------------------------
    // Asignacion de entradas dedicadas (ui_in)
    // ------------------------------------------------------------------
    assign ui_in[1:0] = 2'b00;
    assign ui_in[2]   = uart_rx;
    assign ui_in[7:3] = 5'b00000;

    // ------------------------------------------------------------------
    // Asignacion de salidas dedicadas (uo_out)
    // ------------------------------------------------------------------
    assign spi_sck        = uo_out[0];
    assign spi_cs_flash_n = uo_out[1];
    assign spi_cs_ram_n   = uo_out[2];
    // uo_out[5:3] no se usan
    assign led            = uo_out[6];
    assign uart_tx        = uo_out[7];

    // ------------------------------------------------------------------
    // Buffers tri-estado para el bus bidireccional QSPI/SPI (uio[3:0])
    // ------------------------------------------------------------------
    // Yosys infiere automaticamente primitivas BB (Bidirectional Buffer)
    // del Lattice ECP5 a partir de esta construccion estandar.
    genvar i;
    generate
        for (i = 0; i < 4; i = i + 1) begin : gen_spi_io
            assign spi_io[i] = uio_oe[i] ? uio_out[i] : 1'bz;
            assign uio_in[i] = spi_io[i];
        end
    endgenerate

    // Pines bidireccionales superiores sin usar (uio[7:4])
    assign uio_in[7:4] = 4'b0000;

    // ------------------------------------------------------------------
    // Instancia del top de Tiny Tapeout
    // ------------------------------------------------------------------
    tt_um_femto u_tt_um_femto (
        .ui_in   (ui_in),
        .uo_out  (uo_out),
        .uio_in  (uio_in),
        .uio_out (uio_out),
        .uio_oe  (uio_oe),
        .ena     (1'b1),    // Siempre habilitado en la FPGA
        .clk     (clk),
        .rst_n   (rst_n)
    );

endmodule