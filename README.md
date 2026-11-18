![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# femto_UN — SoC RISC-V (femtoRV32 Quark) para Tiny Tapeout

Implementación de [FemtoRV32 *Quark*](https://github.com/BrunoLevy/learn-fpga) (RV32I) de Bruno Levy, adaptada por la
Universidad Nacional de Colombia como proyecto [Tiny Tapeout](https://tinytapeout.com) (sky130A, 4x2 tiles).
El SoC ejecuta código desde una **flash QSPI externa**, usa una **RAM SPI externa** como memoria de datos y se comunica por **UART**.

- Módulo superior: `tt_um_femto` (`src/femto.v`)
- Documentación del datasheet: [docs/info.md](docs/info.md)
- Informe de verificación: [Informe_Verificacion_femto_UN.pdf](Informe_Verificacion_femto_UN.pdf)
- Guía detallada de la suite de pruebas: [test/README.md](test/README.md)

## Contenido

1. [Arquitectura](#arquitectura)
2. [Mapa de memoria y periféricos](#mapa-de-memoria-y-periféricos)
3. [Pines](#pines)
4. [Estructura del repositorio](#estructura-del-repositorio)
5. [Pruebas (verificación)](#pruebas-verificación)
6. [Escribir firmware](#escribir-firmware)
7. [Síntesis ASIC (LibreLane)](#síntesis-asic-librelane)
8. [Prototipo en FPGA (Colorlight i9)](#prototipo-en-fpga-colorlight-i9)
9. [Integración continua](#integración-continua)
10. [Créditos y licencia](#créditos-y-licencia)

## Arquitectura

| Bloque | Archivo | Descripción |
|---|---|---|
| CPU | `src/femtorv32_quark.v` | RV32I mínimo, sin M/C. `ADDR_WIDTH=24`. ECALL/EBREAK/SYSTEM se ejecutan como `RDCYCLE`; sin FENCE; accesos alineados. |
| Memorias externas | `src/MappedSPIMultidrop.v` | Controlador único para flash y RAM sobre un bus compartido (SCK e IO0..IO3). |
| UART | `src/perip_uart.v`, `src/uart.v` | 8N1, parámetros `clk_freq=25000000`, `baud=115200` (definidos en `femto.v`). |
| Integración | `src/femto.v` | Decodificador de direcciones, multiplexor de lectura y envoltorio `tt_um_femto`. |

**Controlador `MappedSPIMultidrop`.** Un único archivo reemplaza a los antiguos `MappedSPIFlash` y `MappedSPIRAM`:

- **Flash:** solo Quad SPI, *Fast Read Quad I/O* `0xEB` (8 opcode + 6 dirección + 2 modo + 4 dummy + 8 datos = 28 ciclos de SCK). Semiperiodo `FLASH_DIV = 2` ciclos de reloj.
- **RAM:** solo SPI estándar, `0x03` lectura / `0x02` escritura, más `0x00` y dirección de 16 bits y 32 bits de datos (64 ciclos de SCK). Semiperiodo `RAM_DIV = 5` ciclos.
- Prioridades: flash sobre RAM; escritura sobre lectura de RAM. Las banderas busy detienen a la CPU mientras dura la transacción.

Los archivos `acc.v`, `bram.v`, `comp.v`, `control_mult.v`, `lsr.v`, `mult*.v`, `perip_mult.v`, `rsr.v` y `project.v` están en `src/` pero **no** forman parte del diseño (ver `source_files` en `info.yaml`).

## Mapa de memoria y periféricos

El decodificador usa `mem_address[31:16]`:

| Rango | Destino | Notas |
|---|---|---|
| `0x0000_0000` – `0x0000_FFFF` | Flash (código y constantes) | Se leen todos los anchos (`lb/lh/lw/lbu/lhu`). Escribir aquí no genera tráfico SPI. |
| `0x0001_0000` – `0x0001_FFFF` | RAM SPI (datos) | Direccionada por palabra de 16 bits. |
| `0x0040_0000` – `0x0040_FFFF` | UART | Ver registros abajo. |
| Otras | Alias a la flash | Direcciones sin mapear. |

Registros de la UART (base `0x0040_0000`):

| Offset | Lectura | Escritura |
|---|---|---|
| `0x08` | `rx_data[7:0]` | Dato a transmitir (`tx_data`) |
| `0x10` | Estado: bit 9 `tx_busy`, bit 8 `rx_avail`, bit 7 `rx_error` | Control: bit 0 `rx_ack`, bit 2 LED (`LEDS`), bit 3 `tx_wr` |

`tx_wr` es un nivel, no un pulso: se escribe el dato, luego `ctrl = 0x8`, luego `ctrl = 0x0`, y se espera a que `tx_busy` baje.

## Pines

Definidos en `info.yaml`. Reloj nominal 25 MHz.

| Pin | Señal | Pin | Señal |
|---|---|---|---|
| `ui[2]` | RXD | `uo[0]` | `spi_sck` |
| `uo[1]` | `spi_cs_flash_n` | `uo[2]` | `spi_cs_ram_n` |
| `uo[6]` | LEDS | `uo[7]` | TXD |
| `uio[0]` | IO0 (MOSI) | `uio[1]` | IO1 (MISO) |
| `uio[2]` | IO2 | `uio[3]` | IO3 |

Los demás pines no se usan.

## Estructura del repositorio

```
src/          RTL (femto.v, femtorv32_quark.v, MappedSPIMultidrop.v, perip_uart.v, uart.v, ...)
test/         Suite de verificación cocotb + Icarus (ver test/README.md)
config/       Wrapper y pines para la FPGA Colorlight i9 (top_fpga.v, colorlight_i9.lpf)
docs/         info.md (datasheet de Tiny Tapeout)
tt/           Herramientas de soporte de Tiny Tapeout
.github/      Flujos de GitHub Actions (test, gds, docs, fpga)
Makefile      Endurecimiento ASIC (podman), pruebas y flujo FPGA
tt_um_femto.v Netlist a nivel de compuertas sky130 (generada; NO sintetizable en FPGA)
```

## Pruebas (verificación)

La suite usa **cocotb 2.0 + Icarus Verilog** y no modifica el RTL. Se organiza en cinco niveles:

| Nivel | Qué verifica | Archivos | Pruebas |
|---|---|---|---|
| Unit | Quark vs. modelo ISS en Python, controlador Multidrop con modelos de flash/RAM, UART | `test/unit/` | 20 + 20 + 9 |
| Integración | SoC completo: decodificador, handshake busy, UART, una prueba por instrucción RV32I | `test/integration/` | 13 + 40 (ISA) |
| Funcional | Programas RV32I sobre el SoC (ALU, saltos, pila en RAM, UART, LED) | `test/functional/` | 15 |
| End-to-End | Firmware real: hola mundo, Fibonacci, eco, LED, reinicio, autotest ISA | `test/e2e/` | 6 |
| Aceptación | Requisitos REQ-01 a REQ-08 con criterios cuantitativos | `test/acceptance/` | 11 |

### Requisitos

- Icarus Verilog 12 (`sudo apt-get install iverilog`). El Makefile también busca en `~/opt/iverilog-12/bin`.
- Python 3.11+ y `pip install -r test/requirements.txt` (cocotb 2.0.0, pytest).
- Opcional: `riscv64-unknown-elf-gcc` para compilar el firmware de `test/firmware/`.

### Ejecución

Desde la raíz del repositorio (el `Makefile` raíz delega en `test/`) o directamente desde `test/`:

```bash
cd test
make acceptance        # por defecto, y lo único que corre el CI
make unit              # unit-quark, unit-multidrop, unit-uart
make integration       # 13 pruebas del SoC
make integration-isa   # una prueba por instrucción (40)
make functional
make e2e
make all               # todo + tabla resumen
make report            # tabla por nivel desde results/<perfil>/*.xml
make clean
```

Cada objetivo escribe `results/standard/<nivel>.xml`. `make` devuelve éxito aunque una prueba falle, así que revisa el XML
(`grep "<failure" results/standard/acceptance.xml`) o la tabla de `make report`.

**Tiempos.** Las pruebas del SoC completo simulan millones de ciclos: en un contenedor de pruebas, `functional` e `integration-isa` tardan
unos segundos a decenas de segundos, `e2e` cerca de 8 minutos (`test_e06_isa_selftest` por sí sola unos 5) y `acceptance` más de 10 minutos.

### Requisitos de aceptación

| ID | Criterio |
|---|---|
| REQ-01 | Banner `OK` en ≤ 50 000 ciclos tras el reset |
| REQ-02 | Autotest RV32I: 10/10 grupos en P |
| REQ-03 | Palabras de 32 bits íntegras en la RAM SPI |
| REQ-04 | ≤ 240 ciclos por instrucción (≥ 100 kIPS a 24 MHz) |
| REQ-05 | UART TX a 115200 baud ±3 % (24 y 25 MHz; 27 MHz es la variante 05b) |
| REQ-06 | UART RX desde un PC a 115200 ±3 %; tramas consecutivas sin error |
| REQ-07 | Arranque correcto con 3 estados iniciales aleatorios |
| REQ-08 | Arranque con flash y RAM comerciales estándar |

### Resultados medidos

Ejecución en Icarus 12.0 y cocotb 2.0.0, perfil `standard`:

| Nivel | Pasan | Fallan |
|---|---|---|
| Unit Quark | 20 / 20 | — |
| Unit Multidrop | 20 / 20 | — |
| Unit UART | 5 / 9 | `tx_frame_format`, `tx_baud_rate_vs_spec`, `rx_at_own_timebase`, `rx_from_ideal_115200_sender` |
| Integración | 11 / 13 | `i06` (SB/SH/LB/LH sobre RAM), `i08` (ruta de escritura UART) |
| Integración ISA | 36 / 40 | `sb`, `sh`, `ecall`, `ebreak` |
| Funcional | 13 / 15 | `f10` (acceso a subpalabras en RAM), `f11` (transmisión UART) |
| E2E | 1 / 6 | `e01` (hola mundo), `e02` (Fibonacci), `e03` (eco), `e05` (reinicio), `e06` (autotest ISA); solo pasa `e04` (LED) |
| Aceptación | no terminó en 15 min | Sin XML en esta ejecución |

Notas importantes:

- Los archivos `test/results/` versionados en el repositorio son de una corrida anterior y **no coinciden del todo** con estos números
  (por ejemplo, para la UART muestran 7/9 con otros fallos). Vuelve a ejecutar la suite antes de citarlos.
- Los fallos de la UART apuntan a incompatibilidades entre las pruebas y la UART actual (parámetros del reloj y divisor); falta determinar si
  el defecto está en el RTL o en las pruebas. Ver el catálogo de defectos en `test/tools/defects.py` (DEF-U1, DEF-U2).
- Todas las pruebas que dependen de que el chip transmita por UART (`unit_uart` TX, `i08`, `f11`, `e01`, `e02`, `e05`, `e06`) fallan; la que solo usa el LED (`e04`) pasa. Es el primer sitio donde buscar.
- Las pruebas de acceso a subpalabras en RAM (`SB/SH/LB/LH`) fallan en integración y funcional de forma consistente.
- Los resultados de aceptación deben verificarse localmente: es justo lo que ejecuta el CI.

## Escribir firmware

El código se almacena en la flash a partir de la dirección 0. El ejemplo de `test/firmware/` usa:

- `crt0.S`, `link.ld` (FLASH de 64 KB desde `0x0`) y `hello.c`.
- Compilación: `cd test/firmware && make` produce `hello.bin` (`-march=rv32i -mabi=ilp32`).
- Sin extensión M: no hay multiplicación ni división por hardware.
- Los registros arrancan con valores indeterminados; `crt0` debe inicializarlos antes de usar la pila.
- La RAM de datos empieza en `0x10000`.

Programa la imagen `hello.bin` en la flash externa y abre la UART a 115200 baud, 8N1.

## Síntesis ASIC (LibreLane)

El `Makefile` raíz usa `podman` y la imagen `localhost/femto-librelane:2.4.2`, con el PDK en `~/.volare` (`PDK=sky130A`):

```bash
make user-config   # genera la configuración de usuario
make harden        # síntesis, place & route y GDS
make submission    # crea tt_submission y copia tt_um_femto.v a la raíz
make clean
```

## Prototipo en FPGA (Colorlight i9)

Placa Lattice ECP5 LFE5U-45F-6BG381C con reloj de 25 MHz. Herramientas: `yosys`, `nextpnr-ecp5`, `ecppack` (prjtrellis), `openFPGALoader`.

```bash
make fpga-bit     # sintetiza, place & route y genera build/fpga/top_fpga.bit
make fpga-prog    # carga en SRAM (volátil)
make fpga-flash   # graba en la flash SPI de la placa (persistente)
make fpga-clean
```

Se sintetiza el RTL de `src/` con el wrapper `config/top_fpga.v`; los pines están en `config/colorlight_i9.lpf`. **No** se usa `tt_um_femto.v` de la raíz
porque es una netlist de compuertas sky130. El Makefile pasa `--ignore-loops` a nextpnr por un lazo combinacional entre `MappedSPIMultidrop` y la CPU.

## Integración continua

| Flujo | Qué hace |
|---|---|
| `test` | Instala iverilog y las dependencias, corre `make acceptance` y falla si el XML contiene `<failure` |
| `gds` | Genera el GDS con Tiny Tapeout, ejecuta precheck y la prueba a nivel de compuertas |
| `docs` | Construye el datasheet a partir de `docs/info.md` |
| `fpga` | Bitstream de ICE40UP5K; desactivado por defecto (`branches: none`) |

## Créditos y licencia

- FemtoRV32 por Bruno Levy.
- Autor del proyecto: Carlos Camargo Bareño (Universidad Nacional de Colombia).
- Licencia Apache-2.0, ver [LICENSE](LICENSE).
- Más información sobre Tiny Tapeout: [FAQ](https://tinytapeout.com/faq/), [lecciones de diseño digital](https://tinytapeout.com/digital_design/).
