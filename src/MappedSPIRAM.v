`define SPI_FLASH_DUMMY_CLOCKS 0

// SPI RAM controller (mode 0, MSB first)
//   read  : 8'h03 | 8'h00 | word_address[15:0] | 32 bits received
//   write : 8'h02 | 8'h00 | word_address[15:0] | 32 bits sent
//
// Both operations are exactly 64 SCK pulses. SCK idles low and CS_N is
// released only after SCK has returned low.
//
// rd / wr are strobes sampled while idle. rbusy / wbusy rise on the cycle
// after the strobe and fall when the transfer is complete (rdata valid).
// If rd and wr are asserted together, wr wins.

module MappedSPIRAM(
    input wire 	        clk,           // system clock
    input wire          reset,         // system reset (active low)
    input wire 	        rd,            // read strobe
    input wire          wr,            // write strobe
    input wire [15:0]   word_address,  // address of the word to be read/written

    input wire [31:0]   wdata,         // data to be written
    output wire [31:0]  rdata,         // data read
    output reg          rbusy,         // asserted if busy receiving data
    output reg          wbusy,         // asserted if busy writing data

		             // SPI RAM pins
    output reg         CLK,  // clock
    output reg         CS_N, // chip select negated (active low)
    output wire        MOSI, // master out slave in (data to be sent to RAM)
    input  wire        MISO  // master in slave out (data received from RAM)
);

 parameter START      = 3'b000;
 parameter WAIT_INST  = 3'b001;
 parameter SEND       = 3'b010;
 parameter RECEIVE    = 3'b011;

 parameter divisor    = 10;   // SCK period = (divisor+1) system clocks, divisor >= 2

 reg [2:0]  state;
 reg        clk_div;        // 1 cycle pulse just after SCK falls (shift MOSI)
 reg        clk_div_rise;   // 1 cycle pulse just after SCK rises (sample MISO)
 reg [5:0]  div_counter;

 reg [6:0]  snd_bitcount;
 reg [63:0] cmd_addr;
 reg [5:0]  rcv_bitcount;
 reg [31:0] rcv_data;

 // The divider and SCK are held in reset while idle, so every transfer
 // starts from a known phase and SCK does not free-run while CS_N is high.
 wire idle = (state == START) || (state == WAIT_INST);

always @(negedge clk) begin
    if (!reset || idle) begin
      clk_div      <= 0;
      clk_div_rise <= 0;
      div_counter  <= 0;
    end
    else begin
      clk_div_rise <= (div_counter == divisor/2);

      if (div_counter >= divisor) begin
        clk_div      <= 1;
        div_counter  <= 0;
      end
      else begin
        clk_div      <= 0;
        div_counter  <= div_counter + 1;
      end
    end
end

always @(negedge clk) begin
    if (!reset || idle) begin
      CLK <= 0;
    end
    else begin
      if ( (div_counter == divisor/2) | (div_counter == divisor) ) begin
        CLK <= ~CLK;
      end
    end
end

always @(negedge clk) begin
    if (!reset) begin
      state        <= START;
      rbusy        <= 1'b0;
      wbusy        <= 1'b0;
      rcv_data     <= 0;
      CS_N         <= 1;
      cmd_addr     <= 0;
      snd_bitcount <= 0;
      rcv_bitcount <= 0;
    end else begin
    case(state)

      START: begin
        CS_N         <= 1'b1;
        rbusy        <= 1'b0;
        wbusy        <= 1'b0;
        snd_bitcount <= 7'd0;
        rcv_bitcount <= 6'd0;
        state        <= WAIT_INST;
      end

      WAIT_INST: begin
        if (wr) begin
          CS_N         <= 1'b0;
          rbusy        <= 1'b0;
          wbusy        <= 1'b1;
          snd_bitcount <= 7'd64;
          rcv_bitcount <= 6'd0;
          cmd_addr     <= {8'h02, 8'h00, word_address[15:0], wdata[31:0]};
          state        <= SEND;
        end
        else if (rd) begin
          CS_N         <= 1'b0;
          rbusy        <= 1'b1;
          wbusy        <= 1'b0;
          snd_bitcount <= 7'd32;
          rcv_bitcount <= 6'd32;
          cmd_addr     <= {8'h03, 8'h00, word_address[15:0], 32'd0};
          state        <= SEND;
        end
      end

      // Shift MOSI after every SCK falling edge. After the last bit has
      // been clocked out: reads go on to RECEIVE, writes are finished.
      SEND: begin
        if (clk_div) begin
          if (snd_bitcount == 1) begin
            if (rcv_bitcount == 0) state <= START;
            else                   state <= RECEIVE;
          end
          else begin
            snd_bitcount <= snd_bitcount - 7'd1;
            cmd_addr     <= {cmd_addr[62:0], 1'b1};
          end
        end
      end

      // Sample MISO one cycle after every SCK rising edge (the RAM changes
      // MISO on the falling edge), then wait for SCK to fall before CS_N.
      RECEIVE: begin
        if (clk_div_rise && (rcv_bitcount != 0)) begin
          rcv_bitcount <= rcv_bitcount - 6'd1;
          rcv_data     <= {rcv_data[30:0], MISO};
        end
        else if (clk_div && (rcv_bitcount == 0)) begin
          state <= START;
        end
      end

      default:
        state <= START;

    endcase
  end
end

   assign MOSI  = cmd_addr[63];
   assign rdata = rcv_data;

endmodule