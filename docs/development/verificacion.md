---
title: "Verificación"
permalink: /development/verificacion/
lead: "Cinco niveles de pruebas con cocotb e Icarus Verilog, los requisitos de aceptación, lo que se ha medido y cómo leer esas cifras. Para escribir pruebas nuevas, ve a Cómo crear tests."
---

## Estrategia {#estrategia}

La suite verifica el RTL de `src/` **sin modificarlo**. Se organiza de lo pequeño a lo grande: primero cada módulo aislado, luego el SoC completo y por último el chip visto solo desde sus pines.

| Nivel | Qué verifica | Carpeta | Pruebas |
|---|---|---|---|
| Unit | El Quark contra un simulador de referencia en Python; el banco de registros SRAM; el controlador multidrop con modelos de flash y RAM; la UART | `test/unit/` | 20 + 6 + 20 + 9 |
| Integración | SoC completo: decodificador, protocolo *busy*, UART, y una prueba por cada instrucción RV32I | `test/integration/` | 13 + 40 (ISA) |
| Funcional | Programas RV32I que se ejecutan sobre el SoC (ALU, saltos, pila en RAM, UART, LED) | `test/functional/` | 15 |
| Extremo a extremo | Firmware real: hola mundo, Fibonacci, eco, LED, reinicio, autotest de ISA | `test/e2e/` | 6 |
| Aceptación | Los requisitos REQ-01 a REQ-08 con criterios cuantitativos | `test/acceptance/` | 10 |

Qué hace cada archivo, con detalle:

- `unit/test_unit_quark.py`: ISA completa contra el ISS de `lib/rvlib.py`, latencias (ALU = 4, carga o almacenamiento = 5, desplazamiento = *s* + 5 ciclos, contando el ciclo extra de lectura de la SRAM) y programas aleatorios con y sin estados de espera.
- `unit/test_unit_regfile.py`: el banco de registros sobre la macro SRAM: escritura y lectura, direcciones de los dos grupos de 16 registros, independencia entre registros y protocolo de latencia (direcciones en el ciclo N, datos capturados al cierre del N+1).
- `unit/test_unit_multidrop.py`: protocolos QSPI `0xEB` y SPI `0x03`/`0x02`, tiempos de SCK, fases del bus, prioridades, *reset* en mitad de una transacción y tráfico aleatorio.
- `unit/test_unit_uart.py`: trama 8N1, velocidad, `tx_busy`, recepción, error de trama, tramas seguidas, mapa de registros y LED.
- `integration/test_integration.py`: primera lectura, mapa de direcciones, palabras de 31 y 32 bits en la RAM, subpalabras, *handshake* de `busy`, UART y alias de direcciones sin mapear.
- `integration/test_integration_isa.py`: una prueba por instrucción; compara la traza del PC y los registros con el ISS.

## Requisitos de aceptación {#aceptacion}

| ID | Criterio |
|---|---|
| REQ-01 | El banner `OK` aparece en 50 000 ciclos o menos tras el *reset* |
| REQ-02 | Autotest RV32I: 10 de 10 grupos en *pass* |
| REQ-03 | Palabras de 32 bits íntegras en la RAM SPI |
| REQ-04 | Máximo 240 ciclos por instrucción (al menos 100 kIPS a 24 MHz), medido con `RDCYCLE` sobre 100 instrucciones ALU |
| REQ-05 | UART TX a 115 200 baudios ±3 % con relojes de 24 y 25 MHz (05a y 05b) |
| REQ-06 | UART RX desde un PC a 115 200 ±3 %: con pausa y sin pausa (06a, 06b); la variante de 27 MHz (06c) se eliminó con la UART nueva |
| REQ-07 | Tres estados iniciales aleatorios producen siempre el mismo banner |
| REQ-08 | Arranque con una flash W25Q y una RAM 23LC estándar |

## Resultados medidos {#resultados}

Estas cifras salen de los XML de `test/results/standard/` (Icarus 12, cocotb 2.0.0, perfil `standard`) tal como están en la rama `dvillamor`. **No todos son de la misma ejecución:** el último *commit* (banco de registros en SRAM e interrupciones) solo regeneró los de nivel unitario; el resto son de ejecuciones anteriores al cambio del RTL.

| Nivel | Pasan | Fallan | Ejecución |
|---|---|---|---|
| Unit Quark | 19 / 20 | `rdcycle_and_system` | actual |
| Unit regfile | 6 / 6 | — | actual |
| Unit Multidrop | 20 / 20 | — | actual |
| Unit UART | 5 / 9 | `tx_frame_format`, `tx_baud_rate_vs_spec`, `rx_at_own_timebase`, `rx_from_ideal_115200_sender` | actual |
| Integración ISA | 36 / 40 | `sb`, `sh`, `ecall`, `ebreak` | anterior |
| Funcional | 13 / 15 | `f10` (subpalabras en RAM), `f11` (transmisión UART) | anterior |
| Extremo a extremo | 1 / 6 | `e01`, `e02`, `e03`, `e05`, `e06`; solo pasa `e04` (LED) | anterior |
| Aceptación | 0 / 11 | las once (hoy el archivo tiene 10 pruebas; se eliminó `req06c`) | anterior |

La integración básica (`test_integration.py`, 13 pruebas) no tiene XML propio, porque `integration-isa` lo sobrescribe (ver más abajo).

<div class="callout aviso" markdown="1">
**Estas cifras no son una garantía.** Los niveles marcados como «anterior» se ejecutaron con el banco de registros de flip-flops y sin interrupciones: hay que repetirlos con `make all` para saber cómo quedan con el RTL actual. Esta documentación no ha repetido las simulaciones.
</div>

### Cómo leer los fallos {#lectura}

Los fallos se agrupan en tres causas, todas explicadas en este sitio:

<div class="callout analisis" markdown="1">
**1. UART (resultados anteriores a su refactorización).** Los XML guardados se generaron con la UART anterior (192 ciclos por bit) y las pruebas esperaban 208; eso explicaba los fallos de `unit_uart` de transmisión, `i08`, `f11` y los de extremo a extremo que usan la consola. La UART actual usa 217 ciclos por bit: hay que repetir esos niveles para saber cómo quedan. Véase [UART]({{ '/development/uart/' | relative_url }}#pruebas).

**2. Subpalabras en la RAM.** El controlador no aplica la máscara de bytes y envía direcciones no alineadas. Explica `i06`, `f10`, `sb` y `sh`.
Véase [Bus SPI multidrop]({{ '/development/spi-multidrop/' | relative_url }}).

**3. `ecall` y `ebreak`.** Las pruebas esperan que sean instrucciones nulas, pero con las interrupciones el Quark decodifica `MRET` como cualquier `SYSTEM` con `funct3 = 0`: `ecall` y `ebreak` saltan a `mepc`, que tras el *reset* vale 0. Por eso `test_rdcycle_and_system` no llega a su halt (agota el tiempo) y las pruebas ISA `ecall` y `ebreak` fallan. No es un defecto de la prueba sino una consecuencia del diseño actual (véase [CPU]({{ '/development/cpu/' | relative_url }}#interrupciones)).
</div>

La **aceptación** es lo único que corre el CI. Con los resultados guardados el flujo `test` fallaría, pero esos resultados son anteriores a la UART nueva y no se ha repetido la ejecución; además, por cálculo, `REQ-05a` (reloj de 24 MHz) quedaría en −3,99 %, fuera de ±3 % (véase [UART]({{ '/development/uart/' | relative_url }}#pruebas)).

## El informe de verificación en PDF {#informe}

`Informe_Verificacion_femto_UN.pdf` documenta la verificación del **silicio fabricado**, en el *commit* `f15fccd`, que tenía controladores separados para la flash y la RAM
(`MappedSPIFlash`, `MappedSPIRAM`) y ocho pines de memoria. Sus cifras (74 de 98 pruebas con el emulador de memoria; 0 de 45 pruebas de SoC con memorias estándar) **no son las del diseño actual**.
Sigue siendo útil para entender los defectos del silicio anterior y las reglas de firmware que de ahí salieron.

## Problemas conocidos de la infraestructura de pruebas {#infraestructura}

- `integration` e `integration-isa` escriben ambos en `results/<perfil>/integration.xml`; el segundo sobrescribe al primero.
- `make flashdbg` usa `MappedSPIFlash.v`, que ya no está en `src/`, y `tools/collect_flash.py` importa `test_unit_spiflash`, que ya no existe.
- `tools/defects.py` conserva entradas de `MappedSPIRAM` y `MappedSPIFlash` y los defectos del silicio anterior (`DEF-F*`, `DEF-S*`), que no aplican al controlador multidrop.
- `make hw` y `make hwdbg` (co-simulación con el emulador RTL de `test/hw/`) no aplican al diseño actual: asumen pines de flash y RAM separados.
- `test/results/` contiene resultados de otra ejecución, y los directorios `__pycache__` están versionados.
