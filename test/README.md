# Suite de verificación de femto_UN

Pruebas cocotb + Icarus Verilog para el SoC `tt_um_femto` (CPU `femtorv32_quark.v`, controlador `MappedSPIMultidrop.v`, UART y decodificador de `femto.v`).
**No modifica el RTL.** Contexto general en el [README raíz](../README.md); informe completo en `../Informe_Verificacion_femto_UN.pdf`.

## Requisitos

- Icarus Verilog 12 (también se busca en `~/opt/iverilog-12/bin`).
- Python 3.11+ y `pip install -r requirements.txt` (cocotb 2.0.0, pytest 8.4.2).
- Opcional: `riscv64-unknown-elf-gcc` para `firmware/`.
- Las fuentes se leen de `../src` (variable `SRC`).

## Uso

```bash
make                # = make acceptance (lo que corre el CI)
make unit           # unit-quark + unit-multidrop + unit-uart
make integration    # 13 pruebas del SoC
make integration-isa  # 40 pruebas, una por instrucción
make functional     # 15
make e2e            # 6 (lento: ~8 min)
make acceptance     # 11 (lento: >10 min)
make all            # todo + report
make report         # tabla por nivel, results/<perfil>/summary.json
make clean          # borra sim_build, __pycache__ y results
make dbg MOD=<modulo_python>   # depuración sobre el SoC
```

`MEM_PROFILE` (o `PROFILE`) elige el directorio de resultados (`standard` por defecto). `make` termina con éxito aunque fallen pruebas
(el macro `RUN` usa `|| true`): revisa `results/<perfil>/<nivel>.xml` o `make report`. Ejecuta los objetivos en orden, no en paralelo, porque
comparten `sim_build/` y `results/`.

## Niveles y archivos

| Nivel | Archivo | Pruebas | Objetivo |
|---|---|---|---|
| Unit | `unit/test_unit_quark.py` | 20 | ISA completa contra el ISS de `lib/rvlib.py`, latencias (ALU=3, load/store=4, shift=s+4 ciclos), aleatorio diferencial con y sin estados de espera |
| Unit | `unit/test_unit_multidrop.py` | 20 | Protocolos QSPI `0xEB` y SPI `0x03/0x02`, tiempos de SCK, fases del bus, prioridades, reset en medio de una transacción, tráfico aleatorio |
| Unit | `unit/test_unit_uart.py` | 9 | Trama 8N1, baud, `tx_busy`, recepción, error de trama, tramas seguidas, mapa de registros y LED |
| Integración | `integration/test_integration.py` | 13 | Primer fetch, mapa de direcciones, RAM de 31 y 32 bits, subpalabras, handshake busy, UART, alias de direcciones no mapeadas |
| Integración | `integration/test_integration_isa.py` | 40 | Una prueba por instrucción; compara la traza de PC y los registros con el ISS |
| Funcional | `functional/test_functional.py` | 15 | Programas RV32I sobre el SoC (f01–f15) |
| End-to-End | `e2e/test_e2e.py` | 6 | Firmware: hola mundo, Fibonacci, eco, LED, reinicio, autotest ISA |
| Aceptación | `acceptance/test_acceptance.py` | 11 | REQ-01 a REQ-08 (ver abajo) |

Los números entre paréntesis del Quark: la prueba `test_auipc_addr_width_limitation` documenta que AUIPC y las direcciones de load/store se truncan a 24 bits.

## Requisitos de aceptación

| ID | Criterio |
|---|---|
| REQ-01 | Banner `OK` en ≤ 50 000 ciclos tras el reset |
| REQ-02 | Autotest RV32I: 10/10 grupos P |
| REQ-03 | 8 palabras de 32 bits íntegras en la RAM SPI |
| REQ-04 | ≤ 240 ciclos por instrucción (RDCYCLE sobre 100 instrucciones ALU) |
| REQ-05a/b | Baud TX dentro de ±3 % de 115200 con 24 y 25 MHz |
| REQ-06a/b/c | RX desde un PC a 115200: con pausa, sin pausa y con reloj de 27 MHz |
| REQ-07 | 3 estados iniciales aleatorios dan siempre el mismo banner |
| REQ-08 | Arranque con flash W25Q y RAM 23LC estándar |

## Carpetas

- `lib/` — `rvlib.py` (ensamblador RV32I e ISS), `spimodels.py` (modelos de flash y RAM SPI, incl. `QspiFlashTarget`), `soc.py` (banco del SoC, `SocPins`, utilidades de reloj/UART/bus compartido), `fw.py` (prólogos y rutinas de firmware).
- `unit/`, `integration/`, `functional/`, `e2e/`, `acceptance/` — pruebas por nivel.
- `hw/` — emulador RTL `silicon_spi_mem.v` y su testbench. **Obsoleto**: asume los pines de flash y RAM separados del diseño anterior.
- `firmware/` — `crt0.S`, `link.ld`, `hello.c`, `Makefile` y `hello.bin` (imagen de flash en la dirección 0).
- `tools/` — `defects.py` (catálogo de defectos), `report.py` (resumen por nivel), `collect_flash.py` (obsoleto).
- `results/` — XML y `summary.json` por perfil, de una ejecución anterior.

## Resultados medidos (Icarus 12.0, cocotb 2.0.0, perfil `standard`)

| Nivel | Pasan | Fallan |
|---|---|---|
| Unit Quark | 20 / 20 | — |
| Unit Multidrop | 20 / 20 | — |
| Unit UART | 5 / 9 | `tx_frame_format`, `tx_baud_rate_vs_spec`, `rx_at_own_timebase`, `rx_from_ideal_115200_sender` |
| Integración | 11 / 13 | `i06`, `i08` |
| Integración ISA | 36 / 40 | `sb`, `sh`, `ecall`, `ebreak` |
| Funcional | 13 / 15 | `f10`, `f11` |
| E2E | 1 / 6 | todas salvo `e04` (LED) |
| Aceptación | no terminó en 15 min | sin XML |

Los archivos de `results/` incluidos en el repositorio corresponden a otra ejecución y difieren (p. ej. Unit UART 7/9 con fallos en `rx_framing_error` y
`rx_back_to_back_frames`; aceptación 0/11). Regenera con `make all` antes de citarlos.

Observaciones:

- Todo lo que necesita que el chip transmita por UART falla; lo que solo usa el LED pasa.
- Los accesos SB/SH/LB/LH a la RAM fallan en integración y funcional.
- `ecall` y `ebreak` fallan en la prueba ISA: el catálogo documenta que el Quark los ejecuta como `RDCYCLE`, no como NOP.

## Problemas conocidos de la infraestructura

- `integration` e `integration-isa` escriben ambos `results/<perfil>/integration.xml`; el segundo sobrescribe al primero.
- `make flashdbg` usa `MappedSPIFlash.v`, que ya no está en `src/`; `tools/collect_flash.py` importa `test_unit_spiflash`, que ya no existe.
- `tools/defects.py` conserva entradas de `MappedSPIRAM`/`MappedSPIFlash` y de los defectos de silicio anteriores (DEF-F*, DEF-S*), que ya no aplican al controlador Multidrop.
- `make hw` y `hwdbg` no aplican al diseño actual.

## Firmware de ejemplo

```bash
cd firmware && make     # hello.bin: imagen de flash en 0x0 (rv32i, ilp32, sin M)
```

Reglas del firmware: inicializar todos los registros (arrancan indeterminados), no depender de la pila en RAM para valores de 32 bits sin verificarlo,
y para la UART escribir el dato, luego `ctrl = 0x8` (tx_wr), luego `ctrl = 0x0`, y esperar a que `tx_busy` (bit 9 del estado) baje.
