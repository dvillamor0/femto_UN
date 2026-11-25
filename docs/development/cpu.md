---
title: "CPU FemtoRV32 Quark"
permalink: /development/cpu/
lead: "El núcleo RV32I más pequeño de la familia FemtoRV32, tal como está en src/femtorv32_quark.v: interfaz, máquina de estados, banco de registros en SRAM, interrupciones y límites."
---

## Resumen {#resumen}

| Característica | Valor |
|---|---|
| Conjunto de instrucciones | RV32I (37 instrucciones), instrucciones CSR y `MRET` |
| Extensiones | Ninguna: sin M, sin C |
| Ancho de dirección | `ADDR_WIDTH = 24` (parámetro del módulo) |
| Dirección de *reset* | `RESET_ADDR = 0x0000_0000` |
| Banco de registros | Macro SRAM `sky130_sram_32x32_1rw1r` a través de `femto_regfile_sram.v` |
| Interrupciones | Una línea (`interrupt_request`), un nivel, con CSR `mstatus`, `mtvec`, `mepc`, `mcause` |
| Accesos a memoria | Alineados; los de byte y media palabra se resuelven dentro de la CPU |
| Desplazamientos | Un bit por ciclo: un desplazamiento de *s* posiciones tarda *s* + 5 ciclos |

El archivo es una versión del *Quark* de Bruno Levy adaptada para ASIC: máquina de estados escrita de forma explícita, todo registro con estado inicializado por *reset* (sin bloques `initial`) y salidas combinacionales asignadas en cada estado para no inferir *latches*. El mecanismo de interrupciones está tomado de la versión *Intermissum* del mismo autor. Las opciones de compilación del original (`NRV_COUNTER_WIDTH`, `NRV_TWOLEVEL_SHIFTER`) no se activan.

## Interfaz {#interfaz}

| Puerto | Dir. | Función |
|---|---|---|
| `mem_addr[31:0]` | salida | Dirección: el `PC` al buscar instrucciones, la de carga o almacenamiento en los demás casos |
| `mem_rdata[31:0]` | entrada | Palabra leída (instrucción o dato) |
| `mem_rstrb` | salida | Pide una lectura; activa en `FETCH_INSTR` y, en cargas, en `EXECUTE` |
| `mem_rbusy` | entrada | La lectura aún no está lista |
| `mem_wdata[31:0]` | salida | Dato a escribir, con los bytes ya replicados según el ancho |
| `mem_wmask[3:0]` | salida | Máscara de bytes; distinta de cero durante un ciclo en un almacenamiento |
| `mem_wbusy` | entrada | La escritura aún no ha terminado |
| `interrupt_request` | entrada | Petición de interrupción, activa en alto (en el chip, `ui_in[3]`) |
| `reset` | entrada | Activo en **bajo** |

## Máquina de estados {#fsm}

Cinco estados *one-hot*; el valor numérico es el que devuelve `soc.state()` en las pruebas.

| Valor | Estado | Qué hace |
|---|---|---|
| 1 | `FETCH_INSTR` | Activa `mem_rstrb` con `mem_addr = PC` |
| 2 | `WAIT_INSTR` | Espera a que `mem_rbusy` baje; captura `mem_rdata[31:2]` en `instr` y presenta a la SRAM las direcciones de `rs1` y `rs2` |
| 4 | `READ_REGS` | Captura `rs1` y `rs2`, que la SRAM entrega a la vez |
| 8 | `EXECUTE` | Calcula el siguiente `PC`, atiende interrupciones y escribe CSR; en saltos y operaciones sencillas vuelve a `FETCH_INSTR` |
| 16 | `WAIT_ALU_OR_MEM` | Para cargas, almacenamientos y desplazamientos: espera a `!mem_rbusy & !mem_wbusy & !aluBusy` |

`READ_REGS` existe porque la macro SRAM tiene lectura **síncrona**: el dato no está disponible en el mismo ciclo en que se presenta la dirección. Es un ciclo más por instrucción que con un banco de flip-flops. Un código de estado inválido lleva a `FETCH_INSTR`.

Con memoria de latencia cero, las pruebas unitarias esperan estas latencias (`RF_EXTRA = 1` es ese ciclo adicional):

| Instrucción | Ciclos |
|---|---|
| ALU, salto, `jal`, `jalr` | 4 |
| Carga o almacenamiento | 5 |
| Desplazamiento de *s* bits | *s* + 5 |

En el SoC se suma la latencia del bus SPI: una instrucción cuesta, como mínimo, los 112 ciclos de reloj de una lectura de flash más estos 4 o 5.
Con una carga o un almacenamiento sobre la RAM, cada acceso añade otros 640 ciclos
(véase [Bus SPI multidrop]({{ '/development/spi-multidrop/' | relative_url }})).

## Banco de registros y contador de ciclos {#registros}

- Los 32 registros están en una macro OpenRAM de un puerto de lectura/escritura y otro de solo lectura. `rs1` sale por el puerto 1 y `rs2` por el puerto 0, de modo que se leen a la vez. `rd` se escribe una sola vez, al terminar la instrucción.
- El banco **no se inicializa**: `x1`–`x31` arrancan con contenido arbitrario. `x0` no se almacena: el núcleo no escribe en él y lo lee como cero.
- El contador `cycles` es de **64 bits**, se pone a cero con el *reset* y sube en cada ciclo. `cycle` y `cycleh` leen sus dos mitades.
- La macro tiene un modelo funcional de simulación y, para la FPGA, un sustituto en `config/`; véanse [Prototipo en FPGA]({{ '/development/fpga/' | relative_url }}) y [Flujo ASIC]({{ '/development/asic/' | relative_url }}).

## Interrupciones y CSR {#interrupciones}

El núcleo atiende **una** interrupción a la vez, sin prioridades ni causas distintas.

| CSR | Dirección | Contenido | Escritura |
|---|---|---|---|
| `mstatus` | `0x300` | Solo el bit 3, `MIE`: habilita las interrupciones | Sí (bit 3 del valor escrito) |
| `mtvec` | `0x305` | Dirección de la rutina de interrupción | Sí |
| `mepc` | `0x341` | Dirección a la que vuelve `MRET` | No: la fija el hardware |
| `mcause` | `0x342` | Bit 31 a 1 mientras se atiende una interrupción | No |
| `cycle` | `0xC00` | `cycles[31:0]` | No |
| `cycleh` | `0xC80` | `cycles[63:32]` | No |

Cómo funciona:

1. `interrupt_request` se recuerda (es *pegajosa*) hasta que se acepta, porque solo se revisa en `EXECUTE`. Una petición que llega durante la atención de otra no se pierde.
2. Se acepta si `MIE = 1` y no hay otra en curso (`mcause = 0`). En `EXECUTE` la instrucción actual termina, `mepc` guarda la dirección de la siguiente, el `PC` salta a `mtvec` y `mcause` pasa a 1.
3. `MRET` restaura el `PC` desde `mepc` y limpia `mcause`.
4. Tras el *reset*, `mstatus`, `mtvec`, `mepc` y `mcause` valen cero: las interrupciones están deshabilitadas.

`MRET` se decodifica como **cualquier instrucción `SYSTEM` con `funct3 = 0`**, así que `ecall` y `ebreak` se ejecutan igual que `mret`. Las instrucciones `csrrw`, `csrrs`, `csrrc` y sus variantes con inmediato escriben en `mstatus` y `mtvec`; el resto de CSR son de solo lectura.

## Lo que el núcleo no hace {#limites}

| Tema | Comportamiento |
|---|---|
| `ecall`, `ebreak` | Actúan como `mret`; no hay excepciones |
| Excepciones | No hay: instrucciones ilegales, accesos no alineados y similares no generan trampas |
| `fence` | No soportada: decodifica como `jal` (`isJAL = instr[3]`) |
| Accesos no alineados | No soportados: el SoC solo garantiza `lw` y `sw` alineados sobre la RAM |
| Direcciones | `PC`, `auipc` y direcciones de carga o almacenamiento se truncan a 24 bits |

## Ver también {#ver-tambien}

La verificación del núcleo es la parte más sólida del proyecto: pruebas unitarias contra un simulador de referencia en Python, que incluyen una por familia de instrucciones y
programas aleatorios con y sin estados de espera. Véanse [Verificación]({{ '/development/verificacion/' | relative_url }}) y [Cómo crear tests]({{ '/development/crear-tests/' | relative_url }}).
