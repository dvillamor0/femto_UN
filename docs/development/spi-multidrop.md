---
title: "Bus SPI multidrop"
permalink: /development/spi-multidrop/
lead: "Un único controlador, MappedSPIMultidrop.v, atiende la flash QSPI y la RAM SPI sobre los mismos cinco hilos de datos y reloj. Aquí se explica cómo lo consigue."
---

## Por qué un solo controlador {#motivo}

El silicio original tenía un controlador para la flash y otro para la RAM, con ocho pines. El diseño actual los fusiona en uno y comparte el bus: **SCK, IO0–IO3** son comunes y cada memoria conserva su propio `CS_N`.
Los beneficios, según los comentarios del propio RTL, son de área:

- un único registro de desplazamiento de 32 bits (`sh`) que sirve de salida (cabecera o dato a escribir) y de entrada (dato leído);
- un único divisor de reloj, un único contador de ciclos de 5 bits y un único SCK;
- sin estados de petición, arranque y espera: el *strobe* se muestrea directamente en reposo;
- `CS_N` sale directo de registros (`act_f`, `act_r`), sin *glitches*.

## Dos transacciones sobre el mismo motor {#transacciones}

<figure class="figure">
<img src="{{ '/assets/img/spi-transacciones.svg' | relative_url }}" alt="Línea de tiempo de una lectura de flash (28 ciclos: opcode, dirección, modo, dummy, datos) y de un acceso a RAM (64 ciclos: cabecera y datos).">
<figcaption>Figura 2. Fases de cada transacción. Las dos filas no están a la misma escala.</figcaption>
</figure>

### Flash: Fast Read Quad I/O {#flash}

| Fase | Ciclos de SCK | Líneas | Quién maneja |
|---|---|---|---|
| `P_CMD`: opcode `0xEB` | 8 | IO0 | maestro |
| `P_ADDR`: dirección de 24 bits | 6 | IO0–IO3 | maestro |
| `P_TURN`: 2 de modo (`0x00`) y 4 *dummy* | 6 | IO0–IO3 | maestro en los 2 primeros, bus liberado en los 4 siguientes |
| `P_DATA`: 32 bits de datos | 8 | IO0–IO3 | flash |
| **Total** | **28** | | |

La dirección de 24 bits se forma como `{2'b00, flash_word_address[19:0], 2'b00}`: la CPU entrega una dirección de palabra y el controlador la convierte en dirección de byte.
La flash entrega primero el byte menos significativo, de modo que `flash_rdata` reordena los bytes de `sh` para presentar la palabra en *little-endian*.

### RAM: SPI estándar {#ram}

| Fase | Ciclos de SCK | Contenido |
|---|---|---|
| `P_CMD`: cabecera | 32 | comando `0x03` (lectura) o `0x02` (escritura), un byte `0x00` y 16 bits de dirección |
| `P_DATA`: datos | 32 | lectura por IO1 (MISO) o escritura por IO0 (MOSI) |
| **Total** | **64** | |

En una escritura, al terminar la cabecera el registro `sh` se recarga con `ram_wdata` (señal `ldw`) y esos 32 bits salen por IO0.

### Los cuatro estados de fase {#fases}

Flash y RAM reutilizan la misma variable de fase `ph`:

| `ph` | Flash | RAM |
|---|---|---|
| `P_CMD` = 0 | opcode, 8 ciclos | cabecera, 32 ciclos |
| `P_ADDR` = 1 | dirección, 6 ciclos | no se usa |
| `P_TURN` = 2 | modo y *dummy*, 6 ciclos | no se usa |
| `P_DATA` = 3 | datos, 8 ciclos | datos, 32 ciclos |

En la RAM la fase alterna `P_CMD` ↔ `P_DATA` (`next_ph = ~ph`); en la flash avanza `ph + 1`. Al terminar `P_DATA` se bajan `act_f` y `act_r`, y `CS_N` sube cuando SCK ya está en bajo.

## Tiempos {#tiempos}

El semiperiodo de SCK es configurable por parámetro, en ciclos de `clk`:

| Parámetro | Valor | SCK | Ciclos de reloj por acceso | Con 25 MHz |
|---|---|---|---|---|
| `FLASH_DIV` | 2 | `clk / 4` | 28 × 4 = **112** | 4,48 µs, SCK de 6,25 MHz |
| `RAM_DIV` | 5 | `clk / 10` | 64 × 10 = **640** | 25,6 µs, SCK de 2,5 MHz |

Estimación sobre estas cifras: con la flash en el camino, una instrucción aritmética cuesta alrededor de 115–120 ciclos (112 del bus más 4 de CPU), es decir, unos 200 000 instrucciones por segundo a 25 MHz;
una carga o un almacenamiento sobre la RAM suma otros 640 ciclos y baja a unas 33 000 instrucciones por segundo.

El **muestreo** se hace un ciclo de reloj después de cada flanco de subida de SCK (`smp_q`), con SCK estable. Todo el módulo opera en el flanco de **bajada** de `clk`.

## Qué pines maneja el maestro en cada momento {#pines-fase}

`io_oe` decide si el chip maneja cada línea; `io_o` es lo que presenta cuando la maneja:

| Momento | IO0 | IO1 | IO2 | IO3 |
|---|---|---|---|---|
| Reposo | entrada | entrada | 1 | 1 |
| Flash, opcode | salida (opcode) | entrada | 1 | 1 |
| Flash, dirección y modo | salida | salida | salida | salida |
| Flash, *dummy* y datos | entrada | entrada | entrada | entrada |
| RAM, cabecera y escritura | salida | entrada | 1 | 1 |
| RAM, lectura de datos | salida (sin efecto) | **entrada** | 1 | 1 |

IO2 e IO3 se mantienen en 1 salvo cuando la flash los usa (WP# y HOLD# inactivos).

## Prioridades y suposiciones {#suposiciones}

- **Prioridad de petición:** flash sobre escritura de RAM, y escritura sobre lectura. Con un solo maestro (la CPU) solo importa si coinciden peticiones.
- El maestro **no emite otra petición mientras `*_busy = 1`** y mantiene `ram_wdata` estable hasta que termine una escritura.
- Las direcciones se muestrean al aceptar el *strobe*.
- `flash_rdata` y `ram_rdata` **comparten registro**: cada una es válida cuando su `busy` baja y hasta la siguiente petición. La CPU debe capturarla (el Quark guarda la instrucción en `instr`).
- No hay máscara de bytes en la escritura de RAM: siempre se escriben 32 bits.

## Estructura interna del módulo {#estructura}

El RTL se organiza en tres bloques:

1. **Entrada combinacional**: decodifica *strobes* y eventos (`half_done`, `rise_step`, `fall_step`, `last_cyc`) y calcula cuándo cargar o desplazar `sh`.
2. **Máquina de control**: registros de fase y de actividad (`ph`, `act_f`, `act_r`, `wr`), contador de ciclos, divisor, SCK y muestreo.
3. **Salida combinacional**: `CS_N`, `busy`, `io_o`, `io_oe` y los datos de lectura.

<div class="callout analisis" markdown="1">
**Consecuencia para el firmware.** La CPU envía a la RAM `mem_address[15:0]` tal cual, aunque el acceso sea de byte o de media palabra, y el controlador escribe siempre una palabra de 32 bits sin máscara.
Un `sb` o un `sh` sobre la RAM no se comporta como un almacenamiento parcial, y una carga de byte o media palabra recibe 32 bits que empiezan en una dirección no alineada.
Esto coincide con los fallos de las pruebas `i06`, `f10`, `sb` y `sh`. **Usa solo `lw` y `sw` alineados en la RAM.**
</div>

## Parámetros y puertos {#puertos}

| Puerto | Dir. | Ancho | Descripción |
|---|---|---|---|
| `flash_rstrb` | in | 1 | Pide una lectura de flash |
| `flash_word_address` | in | 20 | Dirección de palabra (4 MiB) |
| `flash_rdata` | out | 32 | Palabra leída, ya en *little-endian* |
| `flash_rbusy` | out | 1 | Lectura de flash en curso |
| `ram_rd`, `ram_wr` | in | 1 | Pide lectura o escritura de RAM |
| `ram_word_address` | in | 16 | Dirección de **byte** de la RAM (el nombre es heredado) |
| `ram_wdata` | in | 32 | Dato a escribir |
| `ram_rdata` | out | 32 | Dato leído |
| `ram_rbusy`, `ram_wbusy` | out | 1 | Lectura o escritura de RAM en curso |
| `spi_sck`, `spi_cs_flash_n`, `spi_cs_ram_n` | out | 1 | Reloj y selectores |
| `spi_io_o`, `spi_io_oe`, `spi_io_i` | out/out/in | 4 | Datos, habilitación y entrada de IO0–IO3 |
