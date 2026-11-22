---
title: "Flujo ASIC"
permalink: /development/asic/
lead: "De src/ a un GDS para Tiny Tapeout con LibreLane dentro de un contenedor, y qué hace cada flujo de GitHub Actions."
---

## Datos del proyecto {#proyecto}

Salen de `info.yaml`:

| Campo | Valor |
|---|---|
| Título | UNAL's RISCV |
| Descripción | Implementación de FemtoRV de Bruno Levy |
| Lenguaje | Verilog |
| Módulo superior | `tt_um_femto` |
| Tamaño | 4×2 tiles (un tile mide unos 167×108 µm) |
| Reloj | `clock_hz: 0` (sin frecuencia fija declarada); nominal de 25 MHz |
| Fuentes | `femto.v`, `MappedSPIMultidrop.v`, `perip_uart.v`, `uart.v`, `femtorv32_quark.v` |
| Versión de `info.yaml` | 6 |

Las fuentes deben estar en `src/` y listarse una por una. Cualquier archivo nuevo del diseño tiene que añadirse a `source_files`, y también a `SOC_SRC` en `test/Makefile` y a `FPGA_SRC` en el `Makefile` raíz.

## Configuración de síntesis {#config}

`src/config.json` es la configuración predeterminada de Tiny Tapeout para LibreLane. Los valores que importan para este diseño:

| Variable | Valor | Para qué |
|---|---|---|
| `CLOCK_PERIOD` | 25 (ns) | Restricción de temporización de la síntesis, equivalente a 40 MHz |
| `PL_TARGET_DENSITY_PCT` | 70 | Densidad objetivo del emplazamiento; súbela si falla con el error GPL-0302 |
| `PL_RESIZER_HOLD_SLACK_MARGIN` | 0,1 | Margen de *hold* en emplazamiento |
| `GRT_RESIZER_HOLD_SLACK_MARGIN` | 0,05 | Margen de *hold* en rutado global |
| `RUN_LINTER` | 1 | Ejecuta el linter (no se recomienda desactivarlo) |
| `RUN_CTS` | 1 | Síntesis del árbol de reloj |

El archivo marca como intocable todo lo que está bajo «DO NOT CHANGE ANYTHING BELOW THIS POINT». La restricción de 25 ns es independiente del reloj nominal de 25 MHz de la placa (40 ns): da margen frente al nominal.

## Endurecimiento con `make` {#harden}

El `Makefile` ejecuta cada paso dentro de `podman`, montando el proyecto en `/work` y el PDK en `/pdk` en modo de solo lectura:

```bash
make user-config   # genera la configuración de usuario
make harden        # síntesis, colocación y rutado, y GDS
make submission    # crea tt_submission y copia tt_um_femto.v a la raíz
make clean         # borra runs/ y tt-submission/
```

`make all` encadena los tres primeros. Variables útiles:

| Variable | Valor por defecto |
|---|---|
| `PDK` | `sky130A` |
| `PDK_ROOT` | `~/.volare` |
| `IMAGE` | `localhost/femto-librelane:2.4.2` |

<div class="callout aviso" markdown="1">
`make submission` sobrescribe `tt_um_femto.v` en la raíz con la *netlist* de compuertas. Ese archivo de unos 2,8 MB no es RTL: no lo edites a mano ni lo uses en la FPGA.
</div>

## Los flujos de GitHub Actions {#ci}

| Flujo | Etapas | Qué comprueba |
|---|---|---|
| `gds` | `gds` → `precheck`, `gl_test` y `viewer` | Genera el GDS con `tt-gds-action`, pasa el *precheck* de Tiny Tapeout, repite una prueba a nivel de compuertas y publica un visor |
| `docs` | `docs` | Construye el *datasheet* con `docs/info.md` |
| `test` | `test` | Instala Icarus, ejecuta `make acceptance` y falla si el XML trae `<failure` |
| `fpga` | `fpga` | *Bitstream* para ICE40UP5K; desactivado por defecto |

Todas las acciones apuntan a la versión `ttsky25b` de `tt-gds-action`.

## El datasheet: `docs/info.md` {#datasheet}

La acción `docs` espera el archivo `docs/info.md` con tres secciones en inglés (*How it works*, *How to test*, *External hardware*). En esta carpeta ya hay uno,
y está **excluido de Jekyll** (`exclude` en `_config.yml`) para que no se publique como página de este sitio.

## Archivos auxiliares del diseño {#auxiliares}

- `src/sky130_vsdinv.lef`: macro LEF de un inversor (pines `A` e `Y`, 1,38 × 2,72 µm).
- `src/lint.sh`: ejecuta `verilator --lint-only -DSIM --timing -Wall` sobre todos los `.v` de `src/`.
- `src/config.json`: configuración de LibreLane descrita arriba.
