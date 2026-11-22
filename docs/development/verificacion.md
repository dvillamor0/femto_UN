---
title: "Verificación"
permalink: /development/verificacion/
lead: "Cinco niveles de pruebas con cocotb e Icarus Verilog, los requisitos de aceptación, lo que se ha medido y cómo leer esas cifras."
---

## Estrategia {#estrategia}

La suite verifica el RTL de `src/` **sin modificarlo**. Se organiza de lo pequeño a lo grande: primero cada módulo aislado, luego el SoC completo y por último el chip visto solo desde sus pines.

| Nivel | Qué verifica | Carpeta | Pruebas |
|---|---|---|---|
| Unit | El Quark contra un simulador de referencia en Python; el controlador multidrop con modelos de flash y RAM; la UART | `test/unit/` | 20 + 20 + 9 |
| Integración | SoC completo: decodificador, protocolo *busy*, UART, y una prueba por cada instrucción RV32I | `test/integration/` | 13 + 40 (ISA) |
| Funcional | Programas RV32I que se ejecutan sobre el SoC (ALU, saltos, pila en RAM, UART, LED) | `test/functional/` | 15 |
| Extremo a extremo | Firmware real: hola mundo, Fibonacci, eco, LED, reinicio, autotest de ISA | `test/e2e/` | 6 |
| Aceptación | Los requisitos REQ-01 a REQ-08 con criterios cuantitativos | `test/acceptance/` | 11 |

Qué hace cada archivo, con detalle:

- `unit/test_unit_quark.py`: ISA completa contra el ISS de `lib/rvlib.py`, latencias (ALU = 3, carga o almacenamiento = 4, desplazamiento = *s* + 4 ciclos) y programas aleatorios con y sin estados de espera.
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
| REQ-06 | UART RX desde un PC a 115 200 ±3 %: con pausa, sin pausa y con reloj de 27 MHz (06a, 06b, 06c) |
| REQ-07 | Tres estados iniciales aleatorios producen siempre el mismo banner |
| REQ-08 | Arranque con una flash W25Q y una RAM 23LC estándar |

## Resultados medidos {#resultados}

Según el README del repositorio, con Icarus 12.0 y cocotb 2.0.0, perfil `standard`:

| Nivel | Pasan | Fallan |
|---|---|---|
| Unit Quark | 20 / 20 | — |
| Unit Multidrop | 20 / 20 | — |
| Unit UART | 5 / 9 | `tx_frame_format`, `tx_baud_rate_vs_spec`, `rx_at_own_timebase`, `rx_from_ideal_115200_sender` |
| Integración | 11 / 13 | `i06` (SB/SH/LB/LH sobre RAM), `i08` (escritura UART) |
| Integración ISA | 36 / 40 | `sb`, `sh`, `ecall`, `ebreak` |
| Funcional | 13 / 15 | `f10` (subpalabras en RAM), `f11` (transmisión UART) |
| Extremo a extremo | 1 / 6 | `e01`, `e02`, `e03`, `e05`, `e06`; solo pasa `e04` (LED) |
| Aceptación | sin terminar en 15 min | no hay XML en esa ejecución |

<div class="callout aviso" markdown="1">
**Estas cifras no están garantizadas.** Los archivos de `test/results/` que trae el repositorio proceden de otra ejecución y no coinciden del todo (por ejemplo, Unit UART aparece como 7/9 con otros fallos y aceptación como 0/11).
Vuelve a ejecutar la suite con `make all` antes de citarlos. Esta documentación no ha repetido las simulaciones.
</div>

### Cómo leer los fallos {#lectura}

Los fallos se agrupan en tres causas, dos de ellas explicadas en este sitio:

<div class="callout analisis" markdown="1">
**1. UART.** `femto.v` produce 192 ciclos por bit y las pruebas esperan 208. Explica los fallos de `unit_uart` de transmisión, `i08`, `f11` y los de extremo a extremo que usan la consola.
Véase [UART]({{ '/development/uart/' | relative_url }}).

**2. Subpalabras en la RAM.** El controlador no aplica la máscara de bytes y envía direcciones no alineadas. Explica `i06`, `f10`, `sb` y `sh`.
Véase [Bus SPI multidrop]({{ '/development/spi-multidrop/' | relative_url }}).

**3. `ecall` y `ebreak`.** La prueba ISA espera que sean instrucciones nulas, pero el Quark las ejecuta como `RDCYCLE`. No es un defecto del núcleo, sino una expectativa de la prueba que no coincide con el diseño (véase [CPU]({{ '/development/cpu/' | relative_url }})).
</div>

La **aceptación** es lo único que corre el CI. Con estos resultados, el flujo `test` es probable que falle (hay pruebas de UART entre los requisitos y la suite tarda más de diez minutos), pero esto no se ha comprobado ejecutándolo.

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
