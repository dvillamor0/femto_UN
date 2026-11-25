---
title: "Introducción"
permalink: /user/introduccion/
lead: "Qué contiene el repositorio, cómo ve el programa la memoria y qué señales salen del chip. Es la página de consulta rápida para quien va a escribir firmware."
---

## Qué hace el SoC {#que-hace}

Tras el *reset* la CPU empieza a ejecutar en la dirección `0x0000_0000`, que corresponde a la **flash externa**. Cada
instrucción se trae con una lectura QSPI de 32 bits. Los datos se guardan en una **RAM SPI externa** y la salida de texto
va por una **UART**. No hay memoria de programa ni de datos dentro del chip.

Dos consecuencias prácticas:

- Un programa es solo una imagen binaria (`hello.bin`) que se graba en la flash a partir del *offset* 0.
- El rendimiento lo marca el bus SPI: la lectura de una instrucción cuesta unos **112 ciclos de reloj** solo en pulsos de SCK
  (véase [Bus SPI multidrop]({{ '/development/spi-multidrop/' | relative_url }})).

## Estructura del repositorio {#estructura}

```text
src/            RTL del diseño (femto.v, femtorv32_quark.v, femto_regfile_sram.v, MappedSPIMultidrop.v, perip_uart.v, uart.v)
macros/         Macro SRAM del banco de registros (hoy solo el modelo de simulación)
open_ram/       Configuración de OpenRAM para generar la macro
test/           Suite de verificación cocotb + Icarus (lib/, unit/, integration/, functional/, e2e/, acceptance/)
test/firmware/  crt0.S, link.ld, hello.c y su Makefile
config/         Envoltorio y pines para la FPGA Colorlight i9 (top_fpga.v, colorlight_i9.lpf)
docs/           Esta documentación y el datasheet de Tiny Tapeout (info.md)
tt/             Herramientas de Tiny Tapeout (submódulo)
.github/        Flujos de GitHub Actions: test, gds, docs, fpga
info.yaml       Metadatos del proyecto: pines, archivos fuente, tamaño
Makefile        ASIC (podman), pruebas y flujo de FPGA
tt_um_femto.v   Netlist a nivel de compuertas sky130 (generada; no sintetizable en FPGA)
```

<div class="callout nota" markdown="1">
En `src/` hay más archivos de los que usa el diseño (`acc.v`, `bram.v`, `comp.v`, `control_mult.v`, `lsr.v`, `mult.v`, `mult_32.v`, `perip_mult.v`, `rsr.v`, `project.v`).
Son restos de un multiplicador y de una memoria interna; **no** figuran en `source_files` de `info.yaml`.
</div>

## Mapa de memoria {#mapa-de-memoria}

El decodificador mira solo `mem_address[31:16]`:

| Rango | Destino | Observaciones |
|---|---|---|
| `0x0000_0000` – `0x0000_FFFF` | Flash (código y constantes) | Se leen todos los anchos: `lb`, `lh`, `lw`, `lbu`, `lhu`. Escribir aquí no genera tráfico SPI. |
| `0x0001_0000` – `0x0001_FFFF` | RAM SPI (datos y pila) | Solo `lw` y `sw` alineados. |
| `0x0040_0000` – `0x0040_FFFF` | UART y LED | Registros en `+0x08` y `+0x10`. |
| Cualquier otra | Alias de la flash | La dirección de flash se toma de los bits `[21:2]` (4 MiB). |

<div class="callout dato" markdown="1">
La CPU genera direcciones de **24 bits** (`ADDR_WIDTH = 24`): todo lo que pase de 16 MiB se repliega. Para el firmware importa poco, pero explica por qué
`auipc` y las direcciones de carga y almacenamiento se truncan.
</div>

## Registros de la UART {#registros-uart}

Base `0x0040_0000`. El resto de offsets no hacen nada.

| Offset | Lectura | Escritura |
|---|---|---|
| `0x08` | `rx_data[7:0]`: último byte recibido | `tx_data`: byte a transmitir |
| `0x10` | Estado: bit 9 `tx_busy`, bit 8 `rx_avail`, bit 7 `rx_error` | Control: bit 0 `rx_ack`, bit 2 LED, bit 3 `tx_wr` |

`tx_wr` es un **nivel, no un pulso**. La secuencia correcta para enviar un carácter es:

1. esperar a que `tx_busy` valga 0;
2. escribir el byte en `0x08`;
3. escribir `0x8` en `0x10` (inicia la transmisión);
4. escribir `0x0` en `0x10` (baja `tx_wr`; si se deja en 1 se vuelve a enviar el mismo byte).

El bit 2 del registro de control es el **LED**: lo que escribas en `0x10` lo fija, así que para mantener el LED encendido mientras transmites
hay que usar `0xC` y luego `0x4`. Para recibir, se espera `rx_avail`, se lee `0x08` y se confirma poniendo `rx_ack` (bit 0) a 1 y devolviéndolo enseguida a 0.

## Pines {#pines}

Definidos en `info.yaml`. Los demás pines del proyecto no se usan.

| Pin de Tiny Tapeout | Señal | Dirección | Se conecta a |
|---|---|---|---|
| `ui[2]` | `RXD` | entrada | TX del dongle USB-serie |
| `ui[3]` | `IRQ` | entrada | Petición de interrupción (activa en alto); sin uso, déjala a 0 |
| `uo[0]` | `spi_sck` | salida | CLK de flash y RAM |
| `uo[1]` | `spi_cs_flash_n` | salida | CS# de la flash |
| `uo[2]` | `spi_cs_ram_n` | salida | CS# de la RAM |
| `uo[6]` | `LEDS` | salida | LED con resistencia |
| `uo[7]` | `TXD` | salida | RX del dongle USB-serie |
| `uio[0]` | `IO0` (MOSI) | bidireccional | DI de la flash, SI de la RAM |
| `uio[1]` | `IO1` (MISO) | bidireccional | DO de la flash, SO de la RAM |
| `uio[2]` | `IO2` | bidireccional | WP#/IO2 de la flash |
| `uio[3]` | `IO3` | bidireccional | HOLD#/IO3 de la flash |

## Qué hay que saber antes de escribir firmware {#reglas}

<div class="callout aviso" markdown="1">
**Los registros arrancan con valores indeterminados.** El banco de registros del Quark es una SRAM sin *reset*; el código de arranque debe poner a cero
todo lo que vaya a usar antes de emplear la pila. `test/firmware/crt0.S` ya lo hace.
</div>

- **RAM: solo `lw` y `sw` alineados.** No uses `lb`, `lh`, `lbu`, `lhu`, `sb` ni `sh` sobre `0x0001_0000` y siguientes. Los tipos `char` y `short` en estructuras o
  arreglos globales están, por tanto, fuera de límites mientras vivan en la RAM. La causa está en [Bus SPI multidrop]({{ '/development/spi-multidrop/' | relative_url }}).
- **Código y constantes en la flash.** Ahí sí funcionan todos los anchos, de modo que las cadenas de texto se leen sin problema con `lbu`.
- **Sin multiplicación ni división por hardware.** El compilador las resuelve con rutinas de `libgcc` que cuestan decenas o cientos de instrucciones.
- **`ecall` y `ebreak` se ejecutan como `mret`**: saltan a `mepc`. No los uses; no hay excepciones. `fence` no está soportada. El contador de ciclos se lee con `rdcycle` (`cycle`/`cycleh`).
- **Interrupciones.** `ui[3]` genera una interrupción si el programa activó `mstatus.MIE` y escribió la rutina en `mtvec`; termina con `mret`. Véase [CPU]({{ '/development/cpu/' | relative_url }}#interrupciones).
- **El reloj condiciona la UART.** El divisor está calculado para 25 MHz (217 ciclos por bit); véase la página de [UART]({{ '/development/uart/' | relative_url }}).

Los archivos `crt0.S` y `link.ld` de `test/firmware/` incluyen además algunas precauciones heredadas de una versión anterior del silicio (por ejemplo, un `nop` en la dirección 0 y
máscaras de 31 bits al leer la RAM). Con el controlador actual no se han verificado como necesarias; se conservan por prudencia.
