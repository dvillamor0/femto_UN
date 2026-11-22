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
| L1 | UART | Con 25 MHz, el transmisor sale a unos 130 208 baudios en lugar de 115 200 | RTL | Alta |
| L2 | UART | El bit de parada del receptor se evalúa un bit tarde; fallan las tramas consecutivas | RTL | Media |
| L3 | RAM | Los accesos de byte y media palabra no funcionan; solo `lw` y `sw` alineados | RTL y medido | Alta |
| L4 | CPU | `ecall`, `ebreak` y `SYSTEM` leen el contador de ciclos; no hay `fence` | Diseño | Info |
| L5 | CPU | Direcciones truncadas a 24 bits | Diseño | Info |
| L6 | CPU | Los registros y el contador de ciclos arrancan sin valor definido | Diseño | Media |
| L7 | SoC | Las direcciones sin mapear hacen alias a la flash; escribir en la flash no hace nada | Diseño | Info |
| L8 | Memorias | Requieren flash con QE activo y RAM con dirección de 3 bytes | Diseño | Media |
| L9 | FPGA | Lazo combinacional: `nextpnr` necesita `--ignore-loops` | RTL | Media |
| L10 | Pruebas | Las pruebas esperan 208 ciclos por bit de UART; el CI de aceptación probablemente falle | Medido | Media |

## L1 · Velocidad de la UART {#l1}

Con `clk_freq = 25000000` el generador de baudios da **192 ciclos por bit**, es decir 130 208 baudios (+13 %). Ninguna combinación de 24, 25 y 27 MHz con la fórmula actual queda en el ±3 %.

**Qué hacer.** Abre la terminal a 130208 baudios mientras no se corrija, o aplica alguna de las opciones descritas en [UART]({{ '/development/uart/' | relative_url }}).

## L2 · Bit de parada del receptor {#l2}

`rx_bitcount == 10` evalúa el bit de parada un bit después de haberlo desplazado. Con tramas consecutivas sin pausa puede ver el siguiente bit de inicio como un error de trama y perder el byte.

**Qué hacer.** Deja al menos un carácter de pausa entre bytes enviados desde el PC. Corresponde al defecto `DEF-U2` del catálogo de pruebas.

## L3 · Accesos de byte y media palabra a la RAM {#l3}

La CPU envía `mem_address[15:0]` sin alinear y el controlador siempre escribe 32 bits sin máscara. Un `sb` o `sh` sobre la RAM no actúa como un almacenamiento parcial, y un `lb` o `lh` recibe 32 bits que empiezan en una dirección no alineada.
Las pruebas `i06`, `f10`, `sb` y `sh` fallan por esto.

**Qué hacer.**

- Usa solo `lw` y `sw` alineados en `0x0001_0000` y siguientes.
- No coloques `char`, `short` ni estructuras compactas en la RAM.
- Las constantes en flash no tienen esta restricción: `lb`, `lh`, `lbu` y `lhu` funcionan.

## L4 · `ecall`, `ebreak`, CSR y `fence` {#l4}

Cualquier instrucción con *opcode* `SYSTEM` devuelve el contador de ciclos. `fence` decodifica como `jal`. No hay excepciones ni interrupciones. La prueba ISA `ecall` y `ebreak` falla porque espera que sean instrucciones nulas.

## L5 · Direcciones de 24 bits {#l5}

`ADDR_WIDTH = 24`: `PC`, `auipc` y las direcciones de carga o almacenamiento se truncan. Hay alias cada 16 MiB. Solo afecta a programas que generen direcciones fuera de la ventana de interés.

## L6 · Estado inicial indeterminado {#l6}

El banco de registros no tiene *reset* y `cycles` arranca sin valor. Inicializa todos los registros al arrancar (lo hace `crt0.S`) y usa `cycles` solo para diferencias entre dos lecturas.

## L7 · Direcciones sin mapear {#l7}

El decodificador cae por defecto en la flash: leer fuera de los rangos de la RAM y la UART devuelve datos de la flash, no un error. Escribir en el rango de la flash no genera tráfico SPI.

## L8 · Requisitos de las memorias {#l8}

- **Flash:** el controlador solo implementa *Fast Read Quad I/O* (`0xEB`). Si el bit QE de la flash está desactivado, IO2 e IO3 no actúan como datos y la lectura falla.
- **RAM:** solo SPI estándar con comandos `0x03` y `0x02`, con tres bytes de dirección (`0x00` seguido de 16 bits). Las RAM de dos bytes de dirección no son compatibles, y la RAM debe permitir leer y escribir 32 bits seguidos en una sola transacción.

## L9 · Lazo combinacional {#l9}

Entre `MappedSPIMultidrop` y la CPU (`writeBack`, `aluWr`) existe un lazo combinacional. Para la FPGA, `nextpnr-ecp5` necesita `--ignore-loops`, y su informe de frecuencia deja de ser concluyente para ese camino.

## L10 · Estado de la suite de pruebas {#l10}

Con las causas L1 y L3 sin resolver, la suite de aceptación (lo único que corre el CI) probablemente no pase, y tarda más de diez minutos. Además, `test/results/` y el informe en PDF corresponden a versiones anteriores
del diseño; véase [Verificación]({{ '/development/verificacion/' | relative_url }}).

## Qué falta por hacer {#pendiente}

1. Decidir si se corrige el generador de baudios o las pruebas (L1 y L10), y hacerlo en ambos lados.
2. Añadir máscara de bytes y alineación en el controlador de RAM, o documentar de forma definitiva que solo se admiten palabras completas (L3).
3. Corregir la evaluación del bit de parada del receptor (L2).
4. Repetir la verificación completa y actualizar `test/results/` y el informe en PDF para el diseño multidrop.
5. Validar en hardware, con la FPGA y con el silicio, la salida esperada de `hello.c`.
