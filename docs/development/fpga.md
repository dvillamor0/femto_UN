---
title: "Prototipo en FPGA"
permalink: /development/fpga/
lead: "El mismo RTL de src/ sintetizado para la Colorlight i9 (Lattice ECP5), con un envoltorio que convierte el bus de Tiny Tapeout en pines reales."
---

## Qué se sintetiza {#que-se-sintetiza}

| Elemento | Valor |
|---|---|
| Placa | Colorlight i9 v7.2 |
| FPGA | Lattice ECP5 LFE5U-45F-6BG381C (`--45k --package CABGA381 --speed 6`) |
| Reloj | 25 MHz de la placa (pin P3) |
| Módulo superior | `top_fpga` (`config/top_fpga.v`) |
| Fuentes | `src/femto.v`, `src/femtorv32_quark.v`, `src/perip_uart.v`, `src/uart.v`, `src/MappedSPIMultidrop.v`, `config/top_fpga.v` |
| Restricciones | `config/colorlight_i9.lpf` |

<div class="callout aviso" markdown="1">
**No se usa `tt_um_femto.v` de la raíz.** Ese archivo es la *netlist* a nivel de compuertas de sky130 generada por el flujo ASIC y no se puede sintetizar para ECP5. El flujo toma el RTL de `src/`.
</div>

## Comandos {#comandos}

```bash
make fpga-synth    # Yosys → build/fpga/top_fpga.json
make fpga-pnr      # nextpnr-ecp5 → build/fpga/top_fpga.config
make fpga-bit      # ecppack → build/fpga/top_fpga.bit
make fpga-prog     # openFPGALoader -b colorlight-i9   (SRAM, volátil)
make fpga-flash    # openFPGALoader -b colorlight-i9 -f   (flash de la placa, persistente)
make fpga-clean    # borra build/
```

Los parámetros están en variables del `Makefile` (`FPGA_DEVICE`, `FPGA_FREQ`, `FPGA_PNR_OPT`, `FPGA_BOARD`) y los registros de Yosys y nextpnr quedan en `build/fpga/`.

## El envoltorio `top_fpga` {#envoltorio}

Hace de adaptador entre la interfaz de Tiny Tapeout y los pines de la FPGA:

- `ui_in[2]` ← `uart_rx`; el resto de entradas dedicadas, a 0.
- `uo_out[0]`, `[1]`, `[2]` → `spi_sck`, `spi_cs_flash_n`, `spi_cs_ram_n`; `uo_out[6]` → `led`; `uo_out[7]` → `uart_tx`.
- **Buffers triestado** para el bus `spi_io[3:0]`: para cada línea, `assign spi_io[i] = uio_oe[i] ? uio_out[i] : 1'bz;` y `uio_in[i] = spi_io[i]`. Yosys infiere de ahí las primitivas bidireccionales del ECP5.
- `uio_in[7:4]` a 0 y `ena` a 1.

## Pines {#pines}

Según `config/colorlight_i9.lpf`, todos en LVCMOS33:

| Señal | Sitio | Observaciones |
|---|---|---|
| `clk` | P3 | 25 MHz |
| `rst_n` | K18 | *pull-up* |
| `spi_io[0]` | D20 | |
| `spi_io[1]` | B19 | |
| `spi_io[2]` | A19 | *pull-up* |
| `spi_io[3]` | A18 | *pull-up* |
| `spi_sck` | C4 | flanco rápido |
| `spi_cs_flash_n` | C3 | |
| `spi_cs_ram_n` | A3 | |
| `led` | B1 | |
| `uart_tx` | D2 | |
| `uart_rx` | E2 | *pull-up* |

Los *pull-up* de `spi_io[2]` y `spi_io[3]` mantienen WP# y HOLD# inactivos cuando la FPGA no maneja esas líneas.

## El lazo combinacional {#lazo}

El RTL contiene un **lazo combinacional** entre `MappedSPIMultidrop` y la CPU (`writeBack` y `aluWr`). Sin ayuda, `nextpnr` aborta el análisis de tiempos.
Por eso el `Makefile` le pasa `--ignore-loops` (variable `FPGA_PNR_OPT`).

<div class="callout nota" markdown="1">
`--ignore-loops` evita el aborto, pero el análisis de tiempos de `nextpnr` deja de ser concluyente para ese camino. Conviene validar el diseño en la placa y no fiarse solo del informe de frecuencia.
</div>

## Flujo del CI {#ci}

El flujo `fpga` de GitHub Actions apunta a una **ICE40UP5K** (la plataforma de simulación de Tiny Tapeout) y está desactivado por defecto con `branches: none`. No genera el *bitstream* de la Colorlight.
