---
title: "Herramientas"
permalink: /tools/
lead: "Todo lo que hace falta instalar, agrupado por tarea. No necesitas todo: para leer el RTL y correr las pruebas bastan Icarus Verilog y Python."
---

## Mapa rápido {#mapa}

| Tarea | Necesitas | Aparece en |
|---|---|---|
| Simular y verificar | Icarus Verilog 12, Python 3.11+, cocotb 2.0.0, pytest | `test/` |
| Compilar firmware | Un compilador `riscv64-unknown-elf-gcc` | `test/firmware/` |
| Prototipo en FPGA | Yosys, nextpnr-ecp5, `ecppack` (Project Trellis), openFPGALoader | `make fpga-*` |
| Generar el GDS | Podman, imagen de LibreLane, PDK sky130A, herramientas de Tiny Tapeout | `make harden` |
| Ver esta documentación en local | Ruby y Bundler (opcional) | `docs/` |

## Simulación {#simulacion}

La suite usa **cocotb sobre Icarus Verilog** y no modifica el RTL.

```bash
sudo apt-get install iverilog          # Icarus Verilog (el CI usa la versión 12 de Ubuntu 24.04)

python3 -m venv .venv && . .venv/bin/activate
pip install -r test/requirements.txt   # cocotb 2.0.0, pytest 8.4.2 y dependencias
```

El `Makefile` también busca Icarus en `~/opt/iverilog-12/bin`, por si lo compilaste a mano. Para comprobar qué se está usando:

```bash
make version      # imprime la ruta y la versión de iverilog y vvp
```

<div class="callout nota" markdown="1">
Las pruebas de aceptación y las de extremo a extremo simulan millones de ciclos. Cuenta con **decenas de minutos** para la
suite completa; los detalles de tiempos están en [Simulación y firmware]({{ '/user/simulacion/' | relative_url }}).
</div>

Para inspeccionar formas de onda puedes abrir los volcados que genere la simulación con [GTKWave](https://gtkwave.sourceforge.net/); no es obligatorio.

## Firmware {#firmware}

El firmware se compila para `rv32i` con ABI `ilp32`. Cualquier cadena de herramientas con prefijo `riscv64-unknown-elf-` sirve:

```bash
sudo apt-get install gcc-riscv64-unknown-elf   # nombre del paquete en Debian/Ubuntu
make -C test/firmware CROSS=riscv64-unknown-elf-
```

La variable `CROSS` permite usar otro prefijo. Como el núcleo no tiene la extensión M, las multiplicaciones y divisiones en C se resuelven con funciones de `libgcc`
(`-lgcc` ya está en el `Makefile`).

## FPGA {#fpga}

Para la placa **Colorlight i9** (Lattice ECP5 LFE5U-45F) se usa el flujo de código abierto:

| Herramienta | Paso |
|---|---|
| `yosys` | síntesis (`synth_ecp5`) |
| `nextpnr-ecp5` | colocación y rutado |
| `ecppack` (prjtrellis) | generación del *bitstream* |
| `openFPGALoader` | carga en SRAM o en la flash de la placa |

Una forma cómoda de obtenerlas todas es la distribución [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build).

## ASIC {#asic}

El endurecimiento se ejecuta dentro de un contenedor para no instalar LibreLane en el sistema:

| Elemento | Valor por defecto en el `Makefile` |
|---|---|
| Motor de contenedores | `podman` |
| Imagen | `localhost/femto-librelane:2.4.2` |
| PDK | `sky130A` en `PDK_ROOT = ~/.volare` |
| Herramienta de Tiny Tapeout | `tt/tt_tool.py` (submódulo `tt/`) |

Clona el repositorio con submódulos para que `tt/` no quede vacío:

```bash
git clone --recurse-submodules https://github.com/dvillamor0/femto_UN.git
```

## Integración continua {#ci}

Los flujos de `.github/workflows/` se ejecutan en cada *push*:

| Flujo | Qué hace |
|---|---|
| `test` | Instala Icarus y las dependencias, ejecuta `make acceptance` y falla si el XML contiene `<failure` |
| `gds` | Genera el GDS con Tiny Tapeout, ejecuta *precheck*, la prueba a nivel de compuertas y el visor |
| `docs` | Construye el *datasheet* de Tiny Tapeout a partir de `docs/info.md` |
| `fpga` | *Bitstream* para ICE40UP5K; desactivado por defecto (`branches: none`) |

## Ver esta documentación en local {#docs-local}

El sitio es Jekyll estándar de GitHub Pages, sin complementos externos. Desde la carpeta `docs/`:

```bash
bundle install
bundle exec jekyll serve --baseurl ""
```

Luego abre `http://127.0.0.1:4000/`. Si no quieres instalar Ruby, basta con subir los cambios a la rama `gh_pages` y esperar a que GitHub Pages los publique.
