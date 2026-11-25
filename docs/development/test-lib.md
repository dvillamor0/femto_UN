---
title: "Librería test/lib"
permalink: /development/test-lib/
lead: "Referencia completa de las cuatro bibliotecas de apoyo de la suite: el ensamblador y el simulador de referencia, los modelos de memoria SPI, el banco de pruebas del SoC y las rutinas de firmware."
---

## Visión general {#vision}

Todas las pruebas de `test/` comparten cuatro módulos de Python que viven en `test/lib/`. No contienen pruebas: son las piezas con las que se escribe una.

<figure class="figure">
<img src="{{ '/assets/img/test-lib-arquitectura.svg' | relative_url }}" alt="Diagrama de dependencias: las pruebas unitarias importan rvlib o spimodels; las de integración, funcionales, extremo a extremo y de aceptación importan fw, que importa soc, que a su vez importa rvlib y spimodels.">
<figcaption>Figura 1. Dependencias entre los módulos de <code>test/lib</code> y quién importa a quién.</figcaption>
</figure>

| Módulo | Para qué sirve | Lo usan |
|---|---|---|
| `rvlib.py` | Ensamblador RV32I en Python (`R`, `I`, `L`, `S`, `B`, …), constructor de programas `Prog`, simulador de referencia `ISS`, funciones puras `alu` y `br_taken` y el generador de programas aleatorios | Quark (unit), integración, funcional, e2e, aceptación |
| `spimodels.py` | Esclavos SPI (`SpiTarget`, `QspiFlashTarget`), adaptadores de pines, `UartMonitor` y utilidades de lectura de señales (`geti`, `getm`) | Multidrop, UART y todas las pruebas de SoC |
| `soc.py` | Clase `Soc` (el chip completo con sus memorias y su monitor), `boot()`, constantes del mapa de memoria y rutinas de firmware básicas para la UART | Integración, funcional, e2e, aceptación |
| `fw.py` | `prologue`, `put_hex`, `put_char` y el autotest de ISA que usan las pruebas de aceptación y e2e | Integración, funcional, e2e, aceptación |

### Cómo se importan {#importar}

El `Makefile` de `test/` compone `PYTHONPATH` con `lib/` y con cada carpeta de pruebas, de modo que cualquier módulo se importa por su nombre. Las pruebas de SoC empiezan siempre igual:

```python
import cocotb
from cocotb.triggers import ClockCycles, FallingEdge

from rvlib import *            # ensamblador, Prog, ISS, alu, constantes
from soc import *              # Soc, boot, new_prog, uart_*, halt_loop, constantes
from fw import *               # prologue, put_hex, put_char, build_isa_selftest
from spimodels import geti
```

<div class="callout nota" markdown="1">
Las pruebas unitarias importan solo lo que necesitan (`from rvlib import *` en el Quark, `from spimodels import ...` en multidrop y UART). Fuera de `make`, si ejecutas un módulo a mano, tienes que exportar `PYTHONPATH` tú mismo.
</div>

### Dónde viven los datos {#mapas}

Dos mapas de memoria distintos conviven en la suite. Confundirlos es el error más fácil de cometer.

<figure class="figure">
<img src="{{ '/assets/img/test-mapas-memoria.svg' | relative_url }}" alt="A la izquierda el mapa plano de 256 KiB del banco unitario con código desde 0 y datos desde 0x20000; a la derecha el mapa del SoC con flash en 0x0000_0000, RAM en 0x0001_0000 y UART en 0x0040_0000.">
<figcaption>Figura 2. Banco unitario del Quark (izquierda) frente al SoC completo (derecha).</figcaption>
</figure>

## rvlib: ensamblador, ISS y generador {#rvlib}

### Constantes {#rvlib-const}

| Nombre | Valor | Significado |
|---|---|---|
| `ADDR_WIDTH`, `ADDR_MASK` | 24, `0xFFFFFF` | Ancho de dirección del núcleo; el ISS enmascara con él |
| `MEM_SIZE` | `0x40000` | Memoria plana del banco unitario (256 KiB) |
| `DATA_BASE`, `RES_BASE` | `0x20000` | Zona de datos y buffer de resultados **del banco unitario** |
| `CPU_CLK_NS` | 20 | Periodo del reloj del banco unitario |
| `R_OPS`, `I_OPS`, `SH_OPS`, `BR_OPS`, `LD_OPS`, `ST_OPS` | diccionarios | Nombre de instrucción → campos `funct3`/`funct7`; sirven también para iterar «todas las operaciones» |
| `CORNERS`, `IMM_CORNERS` | listas | Operandos límite (0, 1, `0x7FFFFFFF`, `0x80000000`, `0xFFFFFFFF`, …) |
| `ECALL`, `EBREAK`, `NOP` | palabras | `0x00000073`, `0x00100073` y `addi x0, x0, 0` |

### Codificadores de instrucciones {#rvlib-enc}

Cada función devuelve la **palabra de 32 bits** ya codificada. Los inmediatos se validan: si no caben, la función falla con un `AssertionError` que dice qué campo y qué rango.

| Función | Instrucciones | Argumentos |
|---|---|---|
| `R(op, rd, rs1, rs2)` | `add sub sll slt sltu xor srl sra or and` | tres registros |
| `I(op, rd, rs1, imm)` | `addi slti sltiu xori ori andi` | `imm` de −2048 a 2047 |
| `SH(op, rd, rs1, shamt)` | `slli srli srai` | `shamt` de 0 a 31 |
| `L(op, rd, rs1, imm)` | `lb lh lw lbu lhu` | `rd ← mem[rs1 + imm]` |
| `S(op, rs2, rs1, imm)` | `sb sh sw` | `mem[rs1 + imm] ← rs2` (**ojo**: primero el dato, luego la base) |
| `B(op, rs1, rs2, off)` | `beq bne blt bge bltu bgeu` | `off` en **bytes**, relativo a la propia instrucción |
| `LUI(rd, imm20)`, `AUIPC(rd, imm20)` | `lui`, `auipc` | `imm20` es el campo de 20 bits |
| `JAL(rd, off)`, `JALR(rd, rs1, imm)` | `jal`, `jalr` | `off` en bytes relativo al PC |
| `RDCYCLE(rd)` | `csrrs rd, cycle, x0` | lee el contador de ciclos |
| `li(rd, val)` | `lui` + `addi` | **devuelve una lista** de 1 o 2 palabras |

Hay que fijarse en dos detalles al escribir saltos. El desplazamiento se calcula con el contador del propio programa, por ejemplo `B("bne", 7, 0, lp - p.pc)` para volver a una etiqueta `lp = p.pc` guardada antes. Y `li` devuelve una lista, así que se pasa a `emit`, que sabe aplanarla.

<div class="callout aviso" markdown="1">
`rvlib` solo codifica RV32I y `RDCYCLE`. No hay codificadores para el resto de instrucciones de `SYSTEM` (`csrrw`, `csrrsi`, `mret`…); si una prueba las necesita, se escriben como palabras sueltas. Hay ejemplos en [Cómo crear tests]({{ '/development/crear-tests/' | relative_url }}#interrupciones).
</div>

### Prog: constructor de programas {#prog}

`Prog` es solo un diccionario `{dirección: palabra}` con un contador de posición.

| Miembro | Efecto |
|---|---|
| `Prog(base=0)` | Programa nuevo; el contador empieza en `base` |
| `p.pc` | Dirección donde irá la siguiente palabra |
| `p.org(addr)` | Salta a otra dirección (para colocar una rutina de interrupción o datos aparte) |
| `p.emit(*ws)` | Añade palabras; acepta enteros y listas (como las de `li`) |
| `p.init_results()` | `x31` ← `RES_BASE` y pone a 0 el contador de resultados |
| `p.store_result(rs)` | `sw rs` en la siguiente posición contigua del buffer de resultados |
| `p.halt()` | Emite `jal x0, 0` (bucle infinito) y devuelve su dirección |

`init_results` y `store_result` usan `RES_BASE = 0x20000`, que existe en la memoria plana del banco unitario pero **no** en el SoC (allí la RAM termina en `0x1FFFF`). En pruebas de SoC se guardan resultados con `li` + `sw` a `0x10000` o se imprimen por la UART.

### Modelo de referencia {#iss}

Funciones puras, para calcular el valor esperado sin escribirlo a mano:

```python
alu("sra", 0x80000000, 4)        # 0xF8000000  (acepta también addi, slli, srai…)
br_taken("bltu", 1, 0xFFFFFFFF)  # True
```

`alu(op, a, b)` conoce las diez operaciones de registro y traduce los nombres con inmediato (`addi` → `add`, `srai` → `sra`…). Para las comparaciones con inmediato, pasa el segundo operando ya extendido en signo (`sext(imm, 12)`).

`ISS(mem, pc=0)` es un simulador RV32I instrucción a instrucción:

| Miembro | Descripción |
|---|---|
| `x[0..31]`, `pc`, `mem` | Estado: registros, contador de programa y memoria (`bytearray`) |
| `trace` | Lista con el PC de cada instrucción ejecutada (incluye el halt) |
| `step()` | Ejecuta una instrucción |
| `run(halt_addr, max_steps=200000)` | Ejecuta hasta que el PC llega al halt; falla si no llega |

Su decodificación es independiente de la del ensamblador, de modo que un error de codificación no se cancela a sí mismo. Reproduce los detalles del núcleo: direcciones enmascaradas a `ADDR_WIDTH`, `AUIPC` truncado y `JALR` con el bit 0 a cero. **No** conoce las instrucciones `SYSTEM` (lanza `AssertionError` con «opcode no soportado»), ni interrupciones, ni la latencia de ningún bus.

### Programas aleatorios {#aleatorio}

`gen_random_program(rng, n_items)` devuelve `(Prog, halt_addr)`. Las reglas que respeta el generador son las que hacen que el ISS y el RTL puedan compararse:

- inicializa `x1`…`x30` con valores aleatorios o límite y `x31 = DATA_BASE + 0x200` como puntero de datos;
- los saltos son **solo hacia adelante**, de modo que el programa siempre termina;
- las cargas y almacenamientos usan `x31` con desplazamientos de ±0x200 alineados al tamaño de acceso;
- `x30` es temporal para `JALR` (se calcula con `AUIPC`) y `x31` no se sobrescribe nunca;
- mezcla aproximadamente 22 % de ALU de registros, 14 % de ALU con inmediato, 10 % de desplazamientos, 12 % de cargas, 12 % de almacenamientos, 10 % de saltos condicionales y algo de `JAL`/`JALR`.

<figure class="figure">
<img src="{{ '/assets/img/test-iss-diferencial.svg' | relative_url }}" alt="Una semilla genera un programa aleatorio que se ejecuta en el ISS y en el RTL; se comparan la traza de PC, los 32 registros y la memoria de datos.">
<figcaption>Figura 3. Flujo de la prueba aleatoria diferencial (<code>random_vs_iss</code> en <code>test_unit_quark.py</code>).</figcaption>
</figure>

## spimodels: memorias y monitor de UART {#spimodels}

### Lectura de señales {#spimodels-sig}

| Función | Comportamiento |
|---|---|
| `geti(sig, default=None)` | `int(sig.value)`; devuelve `default` si la señal tiene `X` o `Z` |
| `getm(sig, default=0)` | Como `geti`, pero trata los bits `X`/`Z` como 0; útil en buses parcialmente definidos |

Sin `geti`, una señal indefinida lanza una excepción en mitad de la corrutina de un monitor. Con ella, `None` se puede comprobar con `assert`.

### Adaptadores de pines {#spimodels-pins}

Un esclavo SPI no sabe de qué cables cuelga: se lo dice un objeto de pines con tres miembros (`triggers`, `read()` y `drive_miso(v)`).

| Clase | Dónde se usa | `read()` devuelve |
|---|---|---|
| `DirectPins(dut, sck, cs, mosi, miso)` | Un controlador SPI con señales sueltas | `(sck, cs, mosi)` |
| `SocPins(soc, which)` | El SoC completo (`which` = `"flash"` o `"ram"`) | `(sck, cs, io)`; para la flash `io` es el nibble IO3..IO0 y para la RAM solo IO0 |
| `MdPins(bench, which)` | `test_unit_multidrop.py`, sobre `MappedSPIMultidrop` | igual que `SocPins` |

`SocPins` lee `uo_out[0]` (SCK), `uo_out[1]` o `uo_out[2]` (CS_N de flash o RAM) y `uio_out[3:0]`. Para devolver datos llama a `soc.drive(which, v)`, que combina las dos fuentes sobre `uio_in`: la flash maneja el nibble entero y la RAM solo IO1 (MISO).

### SpiTarget {#spitarget}

Esclavo SPI de modo 0: muestrea MOSI en el flanco de **subida** de SCK y cambia MISO en el de **bajada**.

```python
ram = SpiTarget(pins, kind="ram", profile="standard", miso_delay_ns=0.0, size=1 << 16)
cocotb.start_soon(ram.run())
```

| Miembro | Descripción |
|---|---|
| `mem` | `bytearray` con el contenido |
| `transactions` | Lista de transacciones terminadas (diccionarios, abajo) |
| `cur` | Transacción en curso, o `None` |
| `set_word_be(a, v)` / `get_word_be(a)` | Palabra de 32 bits **big-endian** (tal como viaja por el bus) |
| `load_image(base, data)` | Copia bytes en `mem` |
| `run()` | Corrutina principal; hay que lanzarla con `cocotb.start_soon` |

Cada elemento de `transactions` es un diccionario con, entre otras, estas claves:

| Clave | Contenido |
|---|---|
| `cmd`, `addr` | Comando y dirección interpretados |
| `rises`, `falls` | Instantes (ns) de cada flanco de SCK; su longitud es el número de pulsos |
| `bits`, `rbits`, `wdata` | Bits vistos en MOSI, bits entregados y bytes escritos |
| `t_cs_fall`, `t_cs_rise`, `t_first_rise`, `t_last_rise` | Instantes para medir tiempos |
| `mosi_t` | Instantes de cada cambio de MOSI |

Con ellas se escriben comprobaciones sobre el **protocolo**, no solo sobre los datos: número de pulsos de SCK, periodo, comando, dirección, etc.

El perfil `profile="standard"` es el de una memoria comercial. El perfil `"silicon_aware"` es un emulador que compensaba defectos del silicio anterior; se conserva en la biblioteca, pero `Soc` ya no lo utiliza.

### QspiFlashTarget {#qspi}

Subclase de `SpiTarget` que **solo** entiende *Fast Read Quad I/O* (`0xEB`); ignora cualquier otro opcode. Constantes: `N_CMD = 8`, `N_ADDR = 6`, `N_MODE = 2`, `N_DUMMY = 4`, `N_DATA = 8`.

<figure class="figure">
<img src="{{ '/assets/img/test-modelos-spi-uart.svg' | relative_url }}" alt="Líneas de tiempo de QspiFlashTarget (opcode 8, dirección 6, modo 2, dummy 4, datos 8), de SpiTarget como RAM (comando 8, dirección 24, datos 32) y del muestreo 8N1 de UartMonitor.">
<figcaption>Figura 4. Qué reconoce y qué entrega cada modelo.</figcaption>
</figure>

### UartMonitor {#uartmonitor}

`UartMonitor(soc, bit=7, cycles_per_bit=208, clk_ns=20)` decodifica una línea 8N1 de `uo_out`:

| Miembro | Descripción |
|---|---|
| `bytes` | `bytearray` con lo recibido |
| `text()` | Lo recibido como cadena (`latin1`) |
| `errors` | Lista de mensajes; hoy solo «stop bit inválido» |
| `t_first_start`, `edges` | Instante del primer bit de inicio y de cada inicio |

Detecta el flanco de bajada, espera 1,5 bits y muestrea ocho datos, uno por periodo de bit, y después comprueba el bit de parada. Mide **tiempo**, no mira dentro de la UART: `cycles_per_bit` tiene que coincidir con lo que genera el RTL.

<div class="callout aviso" markdown="1">
`soc.py` fija `UART_CYCLES_PER_BIT = 208`, un valor de la UART anterior; la UART actual emite 217 ciclos por bit a 25 MHz. Por cálculo el monitor aún muestrea dentro de cada bit, pero con poco margen en el bit de parada (unos 23 ciclos). Es la limitación L10 de [Limitaciones conocidas]({{ '/development/limitaciones/' | relative_url }}).
</div>

## soc: el chip completo en el banco {#soc}

### Constantes {#soc-const}

| Nombre | Valor | Uso |
|---|---|---|
| `UART_BASE`, `UART_DATA`, `UART_CTRL` | `0x400000`, `+0x08`, `+0x10` | Direcciones de los registros de la UART |
| `RAM_BASE`, `RAM_TOP` | `0x10000`, `0x20000` | Rango de la RAM SPI; `RAM_TOP − 4` es el `sp` por omisión |
| `FLASH_SIZE` | `1 << 22` | Tamaño del modelo de flash (4 MiB) |
| `UART_CYCLES_PER_BIT` | 208 | Ver el aviso anterior (la UART actual usa 217) |
| `CLK_NS` | 20 | Periodo del reloj del SoC en la simulación, en ns |
| `FETCH_CYCLES_MIN/MAX` | 108 y 125 | Rango esperado de ciclos por *fetch* de flash (28 pulsos × 4 ciclos + sobrecarga) |

### La clase Soc {#soc-clase}

<figure class="figure">
<img src="{{ '/assets/img/test-clases.svg' | relative_url }}" alt="Diagrama de clases con Prog, ISS, Soc, SpiTarget, QspiFlashTarget, los adaptadores de pines y UartMonitor.">
<figcaption>Figura 5. Clases de <code>test/lib</code> y cómo se relacionan.</figcaption>
</figure>

`Soc(dut, profile=None, clk_ns=CLK_NS)` crea los esclavos y el monitor, pero **no arranca nada**: eso lo hace `start()`, normalmente a través de `boot()`.

| Miembro | Descripción |
|---|---|
| `flash`, `ram`, `uart` | `QspiFlashTarget` de 4 MiB, `SpiTarget` de 64 KiB y `UartMonitor` |
| `led_events` | Lista `(tiempo_ns, valor)` con cada cambio del LED (`uo_out[6]`) |
| `cpu` | Atajo a `dut.femto0.CPU` |
| `set_ui(bit, v)` | Cambia un bit de `ui_in` (RXD es el bit 2; la interrupción, el bit 3) |
| `drive(who, v)` | Pone el valor que entrega un esclavo sobre `uio_in` |
| `start(flash_image, ram_image, seed, hold_cycles=12, randomize_regs=True)` | Reloj, reset, carga de memorias, estado inicial aleatorio y arranque de los procesos |
| `run_cycles(n)` | Avanza `n` ciclos |
| `run_until(cond, max_cycles, step=200)` | Avanza hasta que `cond()` sea cierta; devuelve los ciclos usados o `None` si se agotó el tiempo |
| `run_until_uart(text, max_cycles)` | Atajo: espera a que `text` aparezca en lo recibido |
| `run_to_halt(halt_addr, max_cycles)` | Espera a que el PC llegue al halt y deja pasar 40 ciclos |
| `pc()`, `state()`, `reg(i)` | Visibilidad interna: PC, estado de la FSM y registro `xi` (`None` si tiene `X`) |
| `boot_check()` | Comprueba que la CPU leyó de la flash la instrucción de la dirección 4 |

<div class="callout nota" markdown="1">
**`reg(i)` lee la macro SRAM.** El banco de registros es ahora `regfile.u_sram.mem[i]` y `x0` no se almacena, por eso `reg(0)` devuelve siempre 0. En `start()` se rellenan esas 32 posiciones y el contador `cycles` con valores aleatorios (según `seed`): el silicio real también arranca con basura, así que **un programa no puede suponer ningún registro**.
</div>

### Codificación de la FSM que ven los asistentes {#soc-estados}

`state()` devuelve la FSM de cinco estados *one-hot* del Quark:

| Valor | Estado |
|---|---|
| 1 | `FETCH_INSTR` |
| 2 | `WAIT_INSTR` |
| 4 | `READ_REGS` |
| 8 | `EXECUTE` |
| 16 | `WAIT_ALU_OR_MEM` |

`run_to_halt` exige `pc() == halt_addr` y `state()` en 1, 2 o 4; es decir, que el halt se esté **buscando**, no ejecutando una carga o un desplazamiento pendiente. `boot_check` espera `state() == 4` con `pc() == 4`: en `READ_REGS` la instrucción ya está capturada. Los comentarios de `soc.py` aún llaman «EXECUTE» al valor 4 y «WAIT_ALU» al 8, pero el código es correcto con el RTL actual.

### Rutinas de firmware de `soc.py` {#soc-fw}

Escriben instrucciones en un `Prog`; **no ejecutan nada en Python**.

| Rutina | Efecto | Registros que usa |
|---|---|---|
| `new_prog()` | `Prog` con un `NOP` en la dirección 0 | — |
| `crt0(p, sp=RAM_TOP-4)` | Pone `x1`…`x31` a 0 y carga `sp` | todos |
| `uart_init_regs(p, base_reg=28)` | `x28 ← UART_BASE` | `x28` |
| `uart_putc(p, ch_reg)` | Espera `tx_busy = 0`, escribe el dato y da un pulso a `tx_wr` | `x28`, `x29`, `x30` |
| `uart_puts(p, text)` | Un `uart_putc` por cada carácter | `x27`, `x28`, `x29`, `x30` |
| `uart_wait_idle(p)` | Espera a que `tx_busy` baje | `x28`, `x29` |
| `halt_loop(p)` | Emite `jal x0, 0`; devuelve su dirección | — |
| `flash_image(prog)` | Convierte un `Prog` en bytes para la flash | — |

El `NOP` de `new_prog()` es **sacrificial**. Viene de un silicio anterior en el que la primera lectura tras el reset se perdía; se conserva y `boot_check()` verifica la instrucción de la dirección 4, de modo que el programa útil empieza ahí.

### boot() y BootFailure {#boot}

```python
soc = await boot(dut, prog, ram_image=None, seed=1, check=True, flash_extra=None)
```

| Parámetro | Efecto |
|---|---|
| `ram_image` | Bytes que se copian a `ram.mem` desde `0x10000` (índice 0 del modelo) |
| `seed` | Semilla del estado inicial aleatorio (registros y `cycles`) |
| `check` | Si es `True` (por defecto) llama a `boot_check()`; ponlo a `False` para probar justamente cómo arranca la CPU |
| `flash_extra` | `{dirección: bytes}` con datos constantes que se añaden a la flash |

Si `boot_check()` no ve la instrucción esperada lanza `BootFailure`, una subclase de `AssertionError`, con la primera instrucción leída, la esperada y el comando que vio la flash. Una prueba que falla con `BootFailure` no está mal escrita: el SoC **no arranca** con esa memoria.

## fw: rutinas de más alto nivel {#fw}

| Rutina | Descripción |
|---|---|
| `prologue(p, full_init=True)` | `crt0` completo (o solo `sp = 0x1FFFC` si `full_init=False`) más `x28 ← UART_BASE` |
| `put_char(p, "A")` | Imprime un carácter constante |
| `put_hex(p, src_reg, ndig=2)` | Imprime `ndig` dígitos hexadecimales en mayúsculas del registro `src_reg`; usa `x25`, `x26`, `x27`, `x29`, `x30` |
| `build_isa_selftest(banner="ISA ")` | Devuelve `(Prog, halt_addr, letras_esperadas)`: un firmware único que ejecuta 37 instrucciones en 10 grupos e imprime una letra por grupo |
| `ISA_GROUPS` | Los nombres de los diez grupos (ALU, desplazamientos, saltos, cargas y almacenamientos en flash y RAM…) |
| `FLASH_DATA`, `FLASH_DATA_BYTES` | Datos constantes que el autotest espera en `0x3000` de la flash |

### Convenciones de registros {#registros}

Si escribes firmware propio junto a estas rutinas, respeta quién usa qué:

| Registro | Dueño |
|---|---|
| `x2` | `sp` (lo fija `crt0`) |
| `x4` | Valor esperado dentro del autotest de ISA |
| `x25`–`x27` | Temporales de `put_hex` y carácter de `uart_puts` |
| `x28` | Base de la UART (`UART_BASE`) |
| `x29`, `x30` | Temporales de la UART; `x30` también es el temporal de `JALR` en los programas aleatorios |
| `x31` | Puntero de resultados (`init_results`), máscara de fallos en el autotest y puntero de datos en los aleatorios |

## Otras carpetas de `test/` {#otras}

| Carpeta | Contenido |
|---|---|
| `tools/report.py` | Agrega `results/<perfil>/*.xml` en `summary.json` y una tabla por nivel (`make report`) |
| `tools/defects.py` | Catálogo de defectos de un silicio anterior y qué prueba delataba cada uno; `report.py` lo usa para clasificar fallos |
| `tools/collect_flash.py` | Utilidad histórica: importa un módulo (`test_unit_spiflash`) que ya no existe en `unit/` |
| `hw/` | Co-simulación con un emulador RTL del silicio anterior; el propio `Makefile` indica que **no** aplica al diseño con multidrop |
| `firmware/` | Firmware en C (`hello.c`, `crt0.S`, `link.ld`) y su `Makefile`; produce `hello.bin` |

Para ver cómo se combinan todas estas piezas en una prueba nueva, sigue con [Cómo crear tests]({{ '/development/crear-tests/' | relative_url }}).
