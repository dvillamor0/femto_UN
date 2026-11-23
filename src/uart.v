
module uart #(
    parameter integer freq_hz = 25000000,
    parameter integer baud    = 115200
)(
    input  wire       reset,
    input  wire       clk,

    // Receptor
    input  wire       uart_rxd,
    output reg  [7:0] rx_data,
    output reg        rx_avail,
    output reg        rx_error,
    input  wire       rx_ack,

    // Transmisor
    input  wire [7:0] tx_data,
    input  wire       tx_wr,
    output wire       uart_txd,
    output wire       tx_busy
);

//============================================================
// PARAMETROS
//============================================================

// Redondeo al entero mas cercano para reducir error de baud.
localparam integer CLKS_PER_BIT =
    (freq_hz + baud/2) / baud;

localparam integer HALF_BIT = CLKS_PER_BIT / 2;

localparam integer CNT_WIDTH =
    (CLKS_PER_BIT > 1) ? $clog2(CLKS_PER_BIT) : 1;

//============================================================
// ESTADOS: 2 bits por maquina
//============================================================

localparam [1:0] IDLE  = 2'b00;
localparam [1:0] START = 2'b01;
localparam [1:0] DATA  = 2'b10;
localparam [1:0] STOP  = 2'b11;

//============================================================
// REGISTROS
//============================================================

reg [1:0] tx_state;
reg [1:0] rx_state;

reg [CNT_WIDTH-1:0] tx_count;
reg [CNT_WIDTH-1:0] rx_count;

reg [2:0] tx_bit;
reg [2:0] rx_bit;

reg [7:0] tx_shift;
reg [7:0] rx_shift;

//============================================================
// TRANSMISOR
//============================================================

always @(posedge clk) begin
    if (reset) begin
        tx_state <= IDLE;
        tx_count <= 0;
        tx_bit   <= 0;
        tx_shift <= 0;
    end
    else begin
        case (tx_state)

            IDLE: begin
                tx_count <= 0;
                tx_bit   <= 0;

                // tx_wr debe ser un pulso de un ciclo.
                if (tx_wr) begin
                    tx_shift <= tx_data;
                    tx_state <= START;
                end
            end

            START: begin
                if (tx_count == CLKS_PER_BIT - 1) begin
                    tx_count <= 0;
                    tx_bit   <= 0;
                    tx_state <= DATA;
                end
                else begin
                    tx_count <= tx_count + 1'b1;
                end
            end

            DATA: begin
                if (tx_count == CLKS_PER_BIT - 1) begin
                    tx_count <= 0;
                    tx_shift <= {1'b0, tx_shift[7:1]};

                    if (tx_bit == 3'd7) begin
                        tx_state <= STOP;
                    end
                    else begin
                        tx_bit <= tx_bit + 1'b1;
                    end
                end
                else begin
                    tx_count <= tx_count + 1'b1;
                end
            end

            STOP: begin
                if (tx_count == CLKS_PER_BIT - 1) begin
                    tx_count <= 0;
                    tx_state <= IDLE;
                end
                else begin
                    tx_count <= tx_count + 1'b1;
                end
            end

            default: begin
                tx_state <= IDLE;
                tx_count <= 0;
            end

        endcase
    end
end

//============================================================
// RECEPTOR
//============================================================

always @(posedge clk) begin
    if (reset) begin
        rx_state <= IDLE;
        rx_count <= 0;
        rx_bit   <= 0;
        rx_shift <= 0;
        rx_data  <= 0;
        rx_avail <= 0;
        rx_error <= 0;
    end
    else begin

        // Reconocimiento de datos y errores.
        if (rx_ack) begin
            rx_avail <= 0;
            rx_error <= 0;
        end

        case (rx_state)

            IDLE: begin
                rx_count <= 0;
                rx_bit   <= 0;

                if (!uart_rxd) begin
                    rx_state <= START;
                end
            end

            START: begin
                if (rx_count == HALF_BIT - 1) begin
                    rx_count <= 0;

                    if (!uart_rxd) begin
                        rx_state <= DATA;
                        rx_bit   <= 0;
                    end
                    else begin
                        rx_state <= IDLE;
                    end
                end
                else begin
                    rx_count <= rx_count + 1'b1;
                end
            end

            DATA: begin
                if (rx_count == CLKS_PER_BIT - 1) begin
                    rx_count <= 0;
                    rx_shift[rx_bit] <= uart_rxd;

                    if (rx_bit == 3'd7) begin
                        rx_state <= STOP;
                    end
                    else begin
                        rx_bit <= rx_bit + 1'b1;
                    end
                end
                else begin
                    rx_count <= rx_count + 1'b1;
                end
            end

            STOP: begin
                if (rx_count == CLKS_PER_BIT - 1) begin
                    rx_count <= 0;
                    rx_state <= IDLE;

                    if (uart_rxd) begin
                        rx_data  <= rx_shift;
                        rx_avail <= 1;
                    end
                    else begin
                        rx_error <= 1;
                    end
                end
                else begin
                    rx_count <= rx_count + 1'b1;
                end
            end

            default: begin
                rx_state <= IDLE;
                rx_count <= 0;
            end

        endcase
    end
end

//============================================================
// SALIDAS
//============================================================

// Reposo y stop: 1
// Start:          0
// Datos:          tx_shift[0], transmitido primero LSB
assign uart_txd =
    (tx_state == START) ? 1'b0 :
    (tx_state == DATA)  ? tx_shift[0] :
                          1'b1;

assign tx_busy = (tx_state != IDLE);

endmodule
