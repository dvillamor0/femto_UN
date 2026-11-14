# Verificación del silicio femto_UN (RTL = commit f15fccd)

Suite cocotb + Icarus en 5 niveles (Unit, Integration, Functional, End-to-End, Acceptance) para
`femtorv32_quark.v`, `MappedSPIFlash.v`, `MappedSPIRAM.v` (+ UART y el SoC completo `tt_um_femto`).
**No modifica el RTL.** Informe completo: `Informe_Verificacion_femto_UN.pdf`.

## Requisitos
`iverilog`, `cocotb>=2.0` (`pip install cocotb`), opcional `riscv64-unknown-elf-gcc` para `firmware/`.
Las fuentes se leen de `../src` (colocar esta carpeta `verif/` en la raíz del repo, en el commit f15fccd).

## Uso
```
make unit          # Quark (20) + SPI RAM (12) + SPI Flash (12) + SPI Multidrop (16) + UART (9)
make integration   # 13        make functional  # 15      make e2e  # 6      make acceptance  # 11
make hw            # co-simulación del chip con el emulador RTL silicon_spi_mem.v (5)
make report        # tabla por nivel (results/<perfil>/summary.json)
MEM_PROFILE=standard       make all   # memorias comerciales (por defecto)
MEM_PROFILE=silicon_aware  make all   # emulador de memoria (modelo Python)
```

## Resultados (esta versión del silicio)
| Perfil de memoria | Pasan | Notas |
|---|---|---|
| standard (flash/RAM comerciales) | 32 / 98 | 0/45 a nivel SoC: la CPU no arranca (DEF-F1, DEF-F2, DEF-R1) |
| silicon_aware (emulador) | 74 / 98 | los 24 fallos son defectos intrínsecos (DEF-S2/S3, DEF-U1/U2, DEF-R1) |
| HW co-sim (emulador RTL) | 5 / 5 | incluye firmware C compilado con GCC |

## Cómo hacer funcionar el RISC-V (resumen; detalle en el PDF, sección 6)
1. Sustituir flash+RAM por `hw/silicon_spi_mem.v` (FPGA/CPLD, **mismo reloj** que el chip).
2. Firmware: R1 `nop` en dirección 0 · R2 inicializar registros · R3 código/constantes en flash ·
   R4 RAM sólo `lw/sw` · R5 valores de 31 bits + máscara `& 0x7FFFFFFF` · R6 sin pila/recursión ·
   R7 UART: dato, `ctrl=8`, `ctrl=0`, esperar `tx_busy` · R8 reloj ≈24 MHz (115200 baud = f/208).
3. `cd firmware && make` → `hello.bin` (imagen de la flash en la dirección 0).

## Carpetas
`lib/` ensamblador RV32I, ISS, modelos SPI, banco SoC · `unit/ integration/ functional/ e2e/ acceptance/` pruebas ·
`hw/` emulador RTL + co-simulación · `firmware/` crt0, linker, ejemplo C · `tools/` catálogo de defectos e informe ·
`future/` propuesta de MappedSPIRAM corregido (NO aplicada al silicio).

## Cambio: flash + RAM -> MappedSPIMultidrop (controlador único)
`femto.v` ya no instancia `MappedSPIFlash`/`MappedSPIRAM`: instancia solo `MappedSPIMultidrop` (un único archivo, que reúne
la antigua `MappedQSPIFlash` y el top multi-drop; estructura: entrada combinacional / control secuencial / salida combinacional).
* **flash**: únicamente Quad SPI, Fast Read Quad I/O `0xEB` (8 opcode + 6 dirección + 2 modo + 4 dummy + 8 datos = 28 ciclos de SCK).
* **RAM**: únicamente SPI estándar, `0x03` lectura / `0x02` escritura (+ `0x00` + dirección de 16 bits + 32 bits = 64 ciclos de SCK).
* Pines: `uo[0]=SCK`, `uo[1]=CS_N flash`, `uo[2]=CS_N RAM`, `uio[3:0]=IO0..IO3` (IO0=MOSI, IO1=MISO).
* Pruebas: `unit/test_unit_multidrop.py` (20, nuevas) con el modelo `QspiFlashTarget` de `lib/spimodels.py`; `lib/soc.py` y
  `SocPins` adaptados al bus compartido. Los perfiles `standard`/`silicon_aware` ya no aplican al SoC (no hay defectos de silicio de flash/RAM).
* `make hw` (emulador `silicon_spi_mem.v`) asume los pines antiguos y ya no aplica. Los unit de `MappedSPIFlash`/`MappedSPIRAM`
  se conservan como referencia del módulo antiguo (los archivos siguen en `src/` pero ya no están en `info.yaml`).
