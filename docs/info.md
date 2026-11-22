<!---
Datasheet de Tiny Tapeout. Lo consume la acción "docs"; Jekyll lo excluye del sitio (ver _config.yml).
-->

## How it works

femto_UN is a minimal RISC-V system on chip: Bruno Levy's FemtoRV32 *Quark* core (RV32I, no M/C extensions) with no on-chip memory.
Instructions are fetched from an external Quad-SPI flash (Fast Read Quad I/O, `0xEB`) and data lives in an external SPI RAM.
Both memories share SCK and IO0–IO3 on a single multi-drop bus, each with its own chip select, handled by one controller (`MappedSPIMultidrop`).
A UART (8N1) provides the console and one register bit drives an LED.

Memory map seen by the CPU:

| Address range | Target |
|---|---|
| `0x0000_0000` – `0x0000_FFFF` | SPI flash (code and constants); unmapped addresses alias to the flash |
| `0x0001_0000` – `0x0001_FFFF` | SPI RAM (data and stack, aligned 32-bit `lw`/`sw` only) |
| `0x0040_0000` | UART: `+0x08` data, `+0x10` status/control (bit 2 LED, bit 3 `tx_wr`, bit 0 `rx_ack`) |

Nominal clock: 25 MHz. Full documentation (in Spanish): https://dvillamor0.github.io/femto_UN/

## How to test

1. Compile a program with a `riscv64-unknown-elf-` toolchain (`-march=rv32i -mabi=ilp32`, see `test/firmware`) and program the resulting binary into the external flash at offset 0.
2. Connect the flash (with its Quad Enable bit set) and a SPI RAM with 3-byte addressing to the bidirectional pins, and a USB-serial dongle to TXD/RXD.
3. Release reset and open the serial port. The test program prints a banner and turns the LED on.

Note: the UART divider is derived from `clk_freq` in `femto.v`; check the documentation for the effective baud rate at your clock.

## External hardware

- Quad-SPI flash (W25Q family or compatible) and a SPI RAM with 3-byte addressing (23LC1024 family or compatible)
- One USB-serial dongle (3.3 V)
- One LED with a series resistor
