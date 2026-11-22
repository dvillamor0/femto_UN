# Macro OpenRAM del banco de registros (sky130_sram_32x32_1rw1r)

32 palabras x 32 bits, puerto 0 lectura/escritura + puerto 1 solo lectura
("dual access" de OpenRAM): rs1 y rs2 se leen a la vez.

Archivos que debe haber en esta carpeta (los referencian `src/config.json`
y `info.yaml`):

| Archivo | Origen | Estado en este commit |
|---|---|---|
| `sky130_sram_32x32_1rw1r.v` | modelo funcional (simulación) | **modelo de sustitución escrito a mano** |
| `sky130_sram_32x32_1rw1r.lef` | OpenRAM | falta: generar con `open_ram/sram_32x32_1rw1r_config.py` |
| `sky130_sram_32x32_1rw1r.gds` | OpenRAM | falta |
| `sky130_sram_32x32_1rw1r_TT_1p8V_25C.lib` | OpenRAM | falta |

El blackbox para Yosys está en `src/sky130_sram_32x32_1rw1r_bb.v`.

Al generar la macro, copiar aquí el `.v`, `.lef`, `.gds` y `.lib` producidos (el `.v`
de OpenRAM reemplaza al modelo de sustitución) y comprobar que los pines del LEF
coinciden con el blackbox. Si OpenRAM genera columna de reserva para la celda
dual-port aparecerán `spare_wen0` y buses de 33 bits: habría que ajustar blackbox,
wrapper y modelo.
