---
title: "Limitaciones conocidas"
permalink: /development/limitaciones/
lead: "Lo que hoy no funciona, o funciona con condiciones, con su causa en el RTL y la forma de evitarlo. Ordenado por impacto para quien escribe firmware o conecta hardware."
---

## Cómo leer esta lista {#como-leer}

Cada entrada indica de dónde sale la afirmación:

- **Medido**: aparece en los resultados de la suite del repositorio.
- **RTL**: se deduce de leer el código fuente, sin simularlo aquí.
- **Diseño**: es una decisión de diseño documentada en el propio RTL.

## Resumen {#resumen}

| ID | Área | Resumen | Origen | Gravedad |
|---|---|---|---|---|
| L1 | UART | **Resuelta en `main`**: la UART nueva da 217 ciclos por bit (115 207 baudios a 25 MHz) | RTL | — |
| L2 | UART | **Resuelta en `main`**: el receptor nuevo evalúa el bit de parada a mitad de bit | RTL | — |
| L3 | RAM | Los accesos de byte y media palabra no funcionan; solo `lw` y `sw` alineados | RTL y medido | Alta |
| L4 | CPU | `ecall` y `ebreak` actúan como `mret`; no hay excepciones ni `fence` | Diseño | Media |
| L5 | CPU | Direcciones truncadas a 24 bits | Diseño | Info |
| L6 | CPU | Los registros (macro SRAM) arrancan sin valor definido | Diseño | Media |
| L7 | SoC | Las direcciones sin mapear hacen alias a la flash; escribir en la flash no hace nada | Diseño | Info |
| L8 | Memorias | Requieren flash con QE activo y RAM con dirección de 3 bytes | Diseño | Media |
| L9 | FPGA | Lazo combinacional: `nextpnr` necesita `--ignore-loops` | RTL | Media |
| L10 | Pruebas | La biblioteca de pruebas aún asume 208 ciclos por bit (la UART nueva usa 217) y los resultados guardados son anteriores | Medido | Media |
| L11 | ASIC | Faltan el LEF, el GDS y el `.lib` de la macro SRAM; el flujo de GDS no puede completarse | Medido | Alta |

## L1 · Velocidad de la UART (resuelta) {#l1}

El generador de baudios anterior daba 192 ciclos por bit (130 208 baudios, +13 %). El *commit* `0b692c7` reescribió `uart.v` con contadores y redondeo al entero más próximo: con 25 MHz salen **217 ciclos por bit, 115 207 baudios** (+0,006 %). Detalle en [UART]({{ '/development/uart/' | relative_url }}#baudios).

**Qué tener en cuenta.** El divisor depende del parámetro `freq_hz` (25 MHz), no del reloj real: a otro reloj, la velocidad se desvía en proporción (a 24 MHz sería −3,99 %).

## L2 · Bit de parada del receptor (resuelta) {#l2}

El receptor nuevo evalúa el bit de parada a mitad de bit y vuelve a `IDLE` sin esperar más, de modo que reconoce de inmediato una trama consecutiva. Es una conclusión de leer el RTL; no se ha simulado aquí.

## L3 · Accesos de byte y media palabra a la RAM {#l3}

La CPU envía `mem_address[15:0]` sin alinear y el controlador siempre escribe 32 bits sin máscara. Un `sb` o `sh` sobre la RAM no actúa como un almacenamiento parcial, y un `lb` o `lh` recibe 32 bits que empiezan en una dirección no alineada.
Las pruebas `i06`, `f10`, `sb` y `sh` fallan por esto.

**Qué hacer.**

- Usa solo `lw` y `sw` alineados en `0x0001_0000` y siguientes.
- No coloques `char`, `short` ni estructuras compactas en la RAM.
- Las constantes en flash no tienen esta restricción: `lb`, `lh`, `lbu` y `lhu` funcionan.

## L4 · `ecall`, `ebreak`, excepciones y `fence` {#l4}

`MRET` se decodifica como cualquier instrucción `SYSTEM` con `funct3 = 0`, de modo que `ecall` y `ebreak` saltan a `mepc` (que vale 0 hasta la primera interrupción). No hay excepciones: solo existe la línea de interrupción. `fence` decodifica como `jal`. Las pruebas que esperaban que `ecall` y `ebreak` fueran instrucciones nulas (ISA `ecall`/`ebreak` y `test_rdcycle_and_system`) fallan por esta causa. Evita ambas instrucciones en el firmware.

## L5 · Direcciones de 24 bits {#l5}

`ADDR_WIDTH = 24`: `PC`, `auipc` y las direcciones de carga o almacenamiento se truncan. Hay alias cada 16 MiB. Solo afecta a programas que generen direcciones fuera de la ventana de interés.

## L6 · Estado inicial indeterminado {#l6}

El banco de registros es una SRAM y no se inicializa: `x1`–`x31` arrancan con contenido arbitrario. Inicialízalos al arrancar (lo hace `crt0.S`). El contador `cycles` sí se pone a cero con el *reset*.

## L7 · Direcciones sin mapear {#l7}

El decodificador cae por defecto en la flash: leer fuera de los rangos de la RAM y la UART devuelve datos de la flash, no un error. Escribir en el rango de la flash no genera tráfico SPI.

## L8 · Requisitos de las memorias {#l8}

- **Flash:** el controlador solo implementa *Fast Read Quad I/O* (`0xEB`). Si el bit QE de la flash está desactivado, IO2 e IO3 no actúan como datos y la lectura falla.
- **RAM:** solo SPI estándar con comandos `0x03` y `0x02`, con tres bytes de dirección (`0x00` seguido de 16 bits). Las RAM de dos bytes de dirección no son compatibles, y la RAM debe permitir leer y escribir 32 bits seguidos en una sola transacción.

## L9 · Lazo combinacional {#l9}

Entre `MappedSPIMultidrop` y la CPU (`writeBack`, `aluWr`) existe un lazo combinacional. Para la FPGA, `nextpnr-ecp5` necesita `--ignore-loops`, y su informe de frecuencia deja de ser concluyente para ese camino.

## L10 · Estado de la suite de pruebas {#l10}

Dos cosas siguen sin resolver en el lado de las pruebas:

- `UART_CYCLES_PER_BIT = 208` en `test/lib/soc.py` (y 208 literal en pruebas funcionales, de extremo a extremo y en `spimodels.py`), frente a los 217 de la UART actual. Por el cálculo de [UART]({{ '/development/uart/' | relative_url }}#pruebas), la diferencia cabe dentro del margen de muestreo; aun así conviene alinearlos.
- `REQ-05a` mide la velocidad con un reloj de referencia de 24 MHz; con el divisor de 25 MHz da −3,99 % y quedaría fuera de ±3 %. `REQ-06c` (27 MHz) se eliminó.

Además, `test/results/` y el informe en PDF son anteriores a los cambios recientes del RTL (UART, banco SRAM e interrupciones); véase [Verificación]({{ '/development/verificacion/' | relative_url }}). La suite de aceptación (lo único que corre el CI) tarda más de diez minutos.

## L11 · Macro SRAM sin generar {#l11}

`src/config.json` y `info.yaml` ya apuntan a la macro `sky130_sram_32x32_1rw1r`, pero `macros/` solo contiene un modelo funcional escrito a mano. Faltan los archivos `.lef`, `.gds` y `_TT_1p8V_25C.lib`, que se generan con OpenRAM (`open_ram/sram_32x32_1rw1r_config.py`). Mientras no estén, la simulación funciona pero el endurecimiento no. Detalles en [Flujo ASIC]({{ '/development/asic/' | relative_url }}#macro).

## Qué falta por hacer {#pendiente}

1. Generar la macro SRAM con OpenRAM y colocar el LEF, el GDS y el `.lib` en `macros/` (L11).
2. Alinear la biblioteca de pruebas con la UART nueva (217 ciclos por bit) y decidir qué hacer con `REQ-05a` (L10).
3. Añadir máscara de bytes y alineación en el controlador de RAM, o documentar de forma definitiva que solo se admiten palabras completas (L3).
4. Repetir la verificación completa y actualizar `test/results/` y el informe en PDF para el diseño multidrop.
5. Validar en hardware, con la FPGA y con el silicio, la salida esperada de `hello.c`.
