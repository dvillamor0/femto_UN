---
title: "CPU FemtoRV32 Quark"
permalink: /development/cpu/
lead: "El núcleo RV32I más pequeño de la familia FemtoRV32, tal como está en src/femtorv32_quark.v: interfaz, máquina de estados y límites."
---

## Resumen {#resumen}

| Característica | Valor |
|---|---|
| Conjunto de instrucciones | RV32I (37 instrucciones) más lectura del contador de ciclos |
| Extensiones | Ninguna: sin M, sin C |
| Ancho de dirección | `ADDR_WIDTH = 24` (parámetro del módulo) |
| Dirección de *reset* | `RESET_ADDR = 0x0000_0000` |
| Accesos a memoria | Alineados; los de byte y media palabra se resuelven dentro de la CPU |
| Desplazamientos | Un bit por ciclo: un desplazamiento de *s* posiciones tarda *s* + 4 ciclos |

El archivo es una versión del *Quark* de Bruno Levy con la máquina de estados escrita de forma explícita. Las opciones de compilación del original
(`NRV_COUNTER_WIDTH`, `NRV_TWOLEVEL_SHIFTER`) no se activan.

## Interfaz de memoria {#interfaz}

| Puerto | Dir. | Función |
|---|---|---|
| `mem_addr[31:0]` | salida | Dirección: el `PC` al buscar instrucciones, la de carga o almacenamiento en los demás casos |
| `mem_rdata[31:0]` | entrada | Palabra leída (instrucción o dato) |
| `mem_rstrb` | salida | Pide una lectura; activa en `FETCH_INSTR` y, en cargas, en `EXECUTE` |
| `mem_rbusy` | entrada | La lectura aún no está lista |
| `mem_wdata[31:0]` | salida | Dato a escribir, con los bytes ya replicados según el ancho |
| `mem_wmask[3:0]` | salida | Máscara de bytes; distinta de cero durante un ciclo en un almacenamiento |
| `mem_wbusy` | entrada | La escritura aún no ha terminado |
| `reset` | entrada | Activo en **bajo** |

## Máquina de estados {#fsm}

Cuatro estados *one-hot*:

| Estado | Qué hace |
|---|---|
| `FETCH_INSTR` | Activa `mem_rstrb` con `mem_addr = PC` |
| `WAIT_INSTR` | Espera a que `mem_rbusy` baje; captura `mem_rdata[31:2]` en `instr` y lee `rs1` y `rs2` del banco |
| `EXECUTE` | Calcula el siguiente `PC`; en saltos y operaciones sencillas vuelve a `FETCH_INSTR` |
| `WAIT_ALU_OR_MEM` | Para cargas, almacenamientos y desplazamientos: espera a `!mem_rbusy & !mem_wbusy & !aluBusy` |

Con memoria de latencia cero, las pruebas unitarias miden estas latencias:

| Instrucción | Ciclos |
|---|---|
| ALU, salto, `jal`, `jalr` | 3 |
| Carga o almacenamiento | 4 |
| Desplazamiento de *s* bits | *s* + 4 |

En el SoC se suma la latencia del bus SPI: una instrucción cuesta, como mínimo, los 112 ciclos de reloj de una lectura de flash más estos 3 o 4.
Con una carga o un almacenamiento sobre la RAM, cada acceso añade otros 640 ciclos
(véase [Bus SPI multidrop]({{ '/development/spi-multidrop/' | relative_url }})).

## Banco de registros y contador de ciclos {#registros}

- El banco de 32 registros se escribe en el flanco de **bajada** del reloj y **no tiene *reset***: `x1`–`x31` arrancan con valores arbitrarios. Solo `x0` se fuerza a cero en cada escritura.
- Un contador de 32 bits `cycles` sube en cada ciclo y también arranca sin valor definido; sirve para medir tiempos *relativos*.
- Cualquier instrucción con *opcode* `SYSTEM` (`ecall`, `ebreak`, `csrr…`) escribe `cycles` en `rd`. En la práctica, `rdcycle` es `csrrs rd, cycle, x0`.

## Lo que el núcleo no hace {#limites}

| Tema | Comportamiento |
|---|---|
| `ecall`, `ebreak`, CSR | Se ejecutan como `RDCYCLE`; no hay excepciones ni interrupciones |
| `fence` | No soportada: decodifica como `jal` (`isJAL = instr[3]`) |
| Accesos no alineados | No soportados: el SoC solo garantiza `lw` y `sw` alineados sobre la RAM |
| Direcciones | `PC`, `auipc` y direcciones de carga o almacenamiento se truncan a 24 bits |

## Ver también {#ver-tambien}

La verificación del núcleo es la parte más sólida del proyecto: 20 pruebas unitarias contra un simulador de referencia en Python, que incluyen una por familia de instrucciones y
programas aleatorios con y sin estados de espera. Véase [Verificación]({{ '/development/verificacion/' | relative_url }}).
