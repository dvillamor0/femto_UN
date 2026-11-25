---
title: "Cómo crear tests"
permalink: /development/crear-tests/
lead: "Guía práctica para añadir pruebas a la suite: elegir el nivel, escribir el firmware o el estímulo, calcular lo esperado, registrar el archivo en el Makefile y depurar cuando falla."
---

Esta guía asume que ya puedes ejecutar `make -C test unit` (ver [Simulación y firmware]({{ '/user/simulacion/' | relative_url }})). Todas las funciones que aparecen aquí están descritas en [Librería test/lib]({{ '/development/test-lib/' | relative_url }}).

## 1. Elige el nivel {#nivel}

Cada nivel responde a una pregunta distinta y tiene un coste distinto. Empieza por el más pequeño que pueda detectar el fallo que te preocupa.

<figure class="figure">
<img src="{{ '/assets/img/test-niveles.svg' | relative_url }}" alt="Tabla gráfica con los ocho bancos de prueba: módulo bajo prueba, estímulo y oráculo y partes de test/lib que usa cada uno.">
<figcaption>Figura 1. Qué módulo se simula en cada nivel y con qué herramientas se estimula y se comprueba.</figcaption>
</figure>

| Quiero comprobar… | Nivel | Archivo donde añadirlo | Cuesta |
|---|---|---|---|
| Que una instrucción o una latencia del núcleo es correcta | Unit · Quark | `unit/test_unit_quark.py` | segundos |
| El protocolo SPI, sus tiempos o el reparto del bus | Unit · multidrop | `unit/test_unit_multidrop.py` | segundos |
| La trama de la UART o sus registros | Unit · UART | `unit/test_unit_uart.py` | segundos |
| El banco de registros SRAM | Unit · regfile | `unit/test_unit_regfile.py` | segundos |
| Cómo se conectan CPU, decodificador y periféricos | Integración | `integration/test_integration.py` | decenas de segundos |
| Que un programa corto da el resultado correcto en el SoC | Funcional | `functional/test_functional.py` | decenas de segundos |
| Lo que vería un usuario con terminal serie y analizador lógico | Extremo a extremo | `e2e/test_e2e.py` | minutos |
| Un requisito cuantitativo (ciclos, baudios, arranque) | Aceptación | `acceptance/test_acceptance.py` | minutos |

## 2. Esqueleto de una prueba {#esqueleto}

Una prueba es una corrutina `async` decorada con `@cocotb.test()` que recibe el DUT. La primera línea de su *docstring* es la descripción que aparece en los informes, así que debe decir qué se verifica y con qué criterio.

```python
import cocotb
from rvlib import *
from soc import *
from fw import *


@cocotb.test()
async def test_f99_mi_comprobacion(dut):
    """Qué se verifica, con qué datos y qué resultado se espera."""
    ...
```

Reglas que conviene seguir para que la suite siga siendo uniforme:

- **Nombre.** `test_<id>_<descripcion>`, con un identificador corto por archivo: `i01` en integración, `f01` en funcional, `e01` en e2e y `req01` en aceptación. Los archivos unitarios usan nombres descriptivos sin identificador.
- **Una pregunta por prueba.** Si necesitas varios casos de la misma pregunta, itera dentro de la prueba y pon en el mensaje del `assert` qué caso falló.
- **Mensajes que se bastan solos.** Los `assert` de la suite suelen incluir los valores obtenidos y esperados, en hexadecimal cuando son datos.
- **Sin dependencias entre pruebas.** Cada prueba arranca su propio reloj y su propio reset; no cuentes con el estado en que dejó el DUT la anterior.
- **Reloj.** En cocotb 2.0 el periodo se declara con `Clock(dut.clk, 20, unit="ns")`. Los bancos ya lo hacen por ti; solo lo escribes si montas uno nuevo.

## 3. Pruebas a nivel de SoC {#soc}

Son las más habituales. El patrón es siempre el mismo: construyes un firmware con el ensamblador de `rvlib`, lo cargas en la flash con `boot()` y esperas un resultado.

<figure class="figure">
<img src="{{ '/assets/img/test-flujo-soc.svg' | relative_url }}" alt="Pasos de una prueba de SoC: new_prog, prologue, firmware, halt_loop, boot y verificación; debajo el detalle interno de boot.">
<figcaption>Figura 2. Los seis pasos de una prueba de SoC y lo que hace <code>boot()</code> por dentro.</figcaption>
</figure>

### 3.1 Imprimir por la UART {#uart}

Es el formato más robusto porque no depende de ver señales internas: lo que se observa es lo mismo que vería un usuario.

```python
@cocotb.test()
async def test_e99_saludo_y_suma(dut):
    """2 + 3 calculado en el chip se imprime como 'SUM=05'."""
    p = new_prog()                       # NOP en la dirección 0
    prologue(p)                          # registros a 0, sp, x28 = UART_BASE
    p.emit(I("addi", 5, 0, 2), I("addi", 6, 0, 3), R("add", 7, 5, 6))
    for c in "SUM=":
        put_char(p, c)
    put_hex(p, 7, 2)                     # dos dígitos hex del valor de x7
    put_char(p, "\n")
    uart_wait_idle(p)                    # no pares antes de que salga el último bit
    halt_loop(p)

    soc = await boot(dut, p)
    used = await soc.run_until_uart("SUM=05\n", 600_000)
    assert used is not None, f"salida UART incompleta: {soc.uart.text()!r}"
    assert not soc.uart.errors
```

Puntos clave:

1. `run_until_uart(texto, max_ciclos)` devuelve el número de ciclos usados o `None`. Un `None` es un fallo y el mensaje debe mostrar lo que sí llegó (`soc.uart.text()`).
2. El tope de ciclos hay que **calcularlo**: cada instrucción desde flash cuesta unos 112 ciclos de SCK más la FSM, y cada carácter por la UART añade 10 bits × `UART_CYCLES_PER_BIT`. Un tope demasiado ajustado produce fallos intermitentes y uno enorme esconde bucles infinitos.
3. `uart_wait_idle` antes de `halt_loop` evita que el halt llegue mientras el último carácter aún se está transmitiendo.

### 3.2 Comprobar registros {#registros}

Para firmware que no necesita la UART, se espera a que el PC llegue al halt y se leen los registros. El valor esperado se calcula con `alu()` y `br_taken()`, no a mano.

```python
@cocotb.test()
async def test_f98_xor_y_sltu(dut):
    """XOR y SLTU con operandos límite."""
    a, b = 0x80000000, 0x7FFFFFFF
    p = new_prog()
    p.emit(li(1, a), li(2, b))
    p.emit(R("xor", 10, 1, 2), R("sltu", 11, 1, 2))
    h = halt_loop(p)                     # dirección del halt

    soc = await boot(dut, p)
    await soc.run_to_halt(h, 60_000)
    assert soc.reg(10) == alu("xor", a, b), f"xor: x10=0x{(soc.reg(10) or 0):08x}"
    assert soc.reg(11) == alu("sltu", a, b)
```

Dos precauciones: `soc.reg(i)` devuelve `None` si el registro tiene bits indefinidos (el `assert` con `==` ya lo detecta, pero un f-string con `:08x` fallaría; por eso los mensajes usan `(soc.reg(10) or 0)`), y los registros arrancan con **basura aleatoria**, de modo que el firmware debe inicializar todo lo que lea (`prologue` lo hace con `x1`…`x31`; sin él, no).

<div class="callout nota" markdown="1">
El archivo `functional/test_functional.py` ya tiene `run_prog(dut, p, h, exp, label)` y `expect_regs(soc, exp, label)`, que empaquetan exactamente este patrón con un mensaje de error agregado. Si añades pruebas a ese archivo, úsalos.
</div>

### 3.3 Datos en la RAM y en la flash {#memorias}

La RAM SPI solo admite **`lw`/`sw` alineados**; los accesos de byte o media palabra no están soportados. Escribe y lee palabras completas y comprueba desde Python el contenido del modelo:

```python
p = new_prog(); prologue(p)
p.emit(li(10, 0x10000), li(11, 0xCAFEBABE))
p.emit(S("sw", 11, 10, 0x20))            # RAM[0x10020] <- 0xCAFEBABE
h = halt_loop(p)
soc = await boot(dut, p)
await soc.run_to_halt(h, 120_000)
assert soc.ram.get_word_be(0x20) == 0xCAFEBABE
```

Dos cosas que sorprenden: el índice de `soc.ram.mem` empieza en 0 para la dirección `0x10000` del SoC (por eso es `0x20` y no `0x10020`), y el modelo guarda las palabras en el orden en que **viajan por el bus**, por lo que se leen con `get_word_be`.

Para partir de datos ya cargados:

```python
soc = await boot(dut, p,
                 ram_image=bytes.fromhex("DEADBEEF"),          # RAM[0x10000..]
                 flash_extra={0x3000: bytes([1, 2, 3, 4])})    # constantes en la flash
```

`flash_extra` añade bytes a la imagen de la flash sin tocar el programa. Elige direcciones que tu código no ocupe.

### 3.4 Entradas: RXD, LED y reset {#entradas}

Los pines de entrada se manejan con `soc.set_ui(bit, valor)`: RXD es el bit 2 y la petición de interrupción el bit 3. El LED se observa en `soc.led_events`, una lista de `(tiempo_ns, valor)`.

Un emisor serie mínimo, como el `pc_send` de la prueba de aceptación, es un bucle de bits con el periodo de bit que quieras:

```python
async def enviar_byte(soc, byte, ciclos_por_bit):
    for bit in [0] + [(byte >> i) & 1 for i in range(8)] + [1]:
        soc.set_ui(2, bit)
        await soc.run_cycles(ciclos_por_bit)
```

Y un reset a mitad de ejecución (como en `test_e*` de reinicio) se hace bajando `dut.rst_n` en el flanco de bajada del reloj durante varios ciclos y volviéndolo a subir.

### 3.5 Estados iniciales distintos {#semillas}

`boot()` rellena el banco de registros y el contador de ciclos con valores aleatorios a partir de `seed`. Para demostrar que un firmware no depende de ellos, repite la misma prueba con varias semillas y exige el mismo resultado (es lo que hace REQ-07):

```python
textos = set()
for seed in (1, 2, 3):
    soc = await boot(dut, p, seed=seed)
    await soc.run_until_uart("OK\n", 400_000)
    textos.add(soc.uart.text())
assert len(textos) == 1, textos
```

Aquí `boot()` se llama varias veces dentro de la misma prueba: cada llamada crea un `Soc` nuevo y vuelve a aplicar reset.

## 4. Comparar con el ISS en el SoC {#iss}

Si el firmware solo usa registros (sin UART, sin RAM), puedes dejar que el ISS calcule el resultado esperado de **cualquier** programa, sin escribir un valor a mano:

```python
mem = bytearray(MEM_SIZE)
for a, w in p.words.items():
    mem[a:a + 4] = w.to_bytes(4, "little")
iss = ISS(mem)
iss.run(h)                               # h = dirección del halt

soc = await boot(dut, p)
await soc.run_to_halt(h, 400_000)
for i in range(1, 32):
    assert soc.reg(i) == iss.x[i], f"x{i}: rtl={soc.reg(i)} iss=0x{iss.x[i]:08x}"
```

El ISS no conoce la UART ni la RAM SPI (ve una memoria plana) ni las instrucciones `SYSTEM`, así que no sirve para programas que las usen. Las pruebas de `integration/test_integration_isa.py` siguen esta idea, una por instrucción.

## 5. Pruebas unitarias {#unit}

### 5.1 El Quark con `CoreTB` {#quark}

El núcleo se prueba sin SoC: `CoreTB` (en `test_unit_quark.py`) le da una memoria plana de Python, con estados de espera opcionales, y entrega la traza de direcciones pedidas. Un programa de resultados directos:

```python
@cocotb.test()
async def test_mi_xor(dut):
    """XOR con operandos complementarios y límite."""
    tb = await make_tb(dut, rbusy_max=0, wbusy_max=0)
    p = Prog(); p.init_results()         # x31 apunta al buffer de resultados
    esperado = []
    for a, b in ((0xAAAAAAAA, 0x55555555), (0x80000000, 1)):
        p.emit(li(1, a), li(2, b), R("xor", 3, 1, 2))
        p.store_result(3)                # sw x3 -> siguiente palabra de RES_BASE
        esperado.append(alu("xor", a, b))
    h = p.halt()
    await tb.run(p, h)                   # reset, ejecuta hasta el halt, comprueba errores
    check_results(tb, p, esperado, "xor")
```

- `make_tb(dut, rbusy_max=N, wbusy_max=N, seed=1)` introduce de 0 a `N` ciclos de espera aleatorios en lecturas y escrituras, como los de una SPI real. Repite las pruebas sensibles con y sin esperas.
- Aquí **no** se usa `new_prog()`: no hay flash ni NOP sacrificial, el programa empieza en la dirección 0.
- `tb.run()` falla por *timeout* si el PC no llega al halt y muestra los últimos PC.
- `tb.regs()` devuelve los 32 registros del banco para comparar con el ISS, como en la prueba aleatoria (Figura 3 de [test/lib]({{ '/development/test-lib/' | relative_url }}#aleatorio)).

Para una comparación completa con el ISS, copia el cuerpo de `random_vs_iss` y cambia el generador por tu programa: compara traza de PC, registros y memoria de datos.

### 5.2 El controlador multidrop con `MdBench` {#multidrop}

`MdBench` hace de CPU (un pulso de estrobo y espera a que baje `busy`) y vigila el bus compartido en cada ciclo: dos CS_N a 0, SCK en reposo con CS_N alto o `io_oe` incorrecto quedan registrados y `check_bus()` los hace fallar.

```python
@cocotb.test()
async def test_mi_lectura_de_flash(dut):
    """Una lectura de flash devuelve la palabra cargada con el protocolo 0xEB."""
    b = await make_bench(dut)
    b.put_flash_word(0x40, 0x11223344)   # dirección de palabra
    r = await b.flash_read(0x40)
    t = r["t"]                           # transacción vista por el modelo
    assert t["cmd"] == 0xEB and t["addr"] == 4 * 0x40
    assert len(t["rises"]) == 28
    assert r["rdata"] == 0x11223344
    b.check_bus()                        # invariantes del bus
```

Operaciones disponibles: `flash_read(wa)`, `ram_read(addr)`, `ram_write(addr, wdata)`, `idle(n)`, `put_flash_word`. Cada una devuelve un diccionario con `cycles` (ciclos hasta el fin de `busy`), `rdata`, `busy_first_edge`, `others_first_edge` y la transacción `t`.

### 5.3 La UART {#uart-unit}

`test_unit_uart.py` instancia `peripheral_uart` con `clk_freq = 25 MHz` y `baud = 115200` (parámetros `-P` en el `Makefile`). Sus ayudantes:

| Ayudante | Qué hace |
|---|---|
| `setup(dut)` | Reloj de 20 ns, reset, entradas a reposo |
| `bus_write(dut, addr, val)` / `bus_read(dut, addr)` | Ciclo de bus de un periodo, como lo haría el decodificador |
| `send_byte(dut, val)` | Escribe el dato (`0x08`) y da el pulso `tx_wr` (`0x10`, bit 3) |
| `capture_frame(dut)` | Espera el bit de inicio y devuelve los flancos y los niveles de la línea durante 12 × 260 ciclos |
| `decode(levels, cpb)` | Muestrea en el centro de cada bit |
| `send_rx_frame(dut, val, cpb)` | Inyecta una trama 8N1 en `uart_rx` con el periodo de bit dado |

### 5.4 El banco de registros {#regfile}

`test_unit_regfile.py` respeta el protocolo de latencia del núcleo: en el ciclo N se activa `rd_en` con las dos direcciones; la macro las muestrea, y al cierre del ciclo N+1 se capturan los dos datos. Cambia las entradas **tras el flanco de bajada** y compara ambos puertos con un diccionario de Python.

## 6. Interrupciones y CSRs {#interrupciones}

El Quark tiene una línea de interrupción (`ui_in[3]` en el SoC), CSRs `mstatus`, `mtvec`, `mepc`, `mcause`, `cycle` y `cycleh`, y `MRET`. La biblioteca no los codifica, así que se escriben como palabras:

```python
def csrrw(rd, csr, rs1):    return (csr << 20) | (rs1 << 15) | (1 << 12) | (rd << 7) | 0x73
def csrrsi(rd, csr, zimm):  return (csr << 20) | (zimm << 15) | (6 << 12) | (rd << 7) | 0x73
MRET = 0x30200073
CSR_MSTATUS, CSR_MTVEC = 0x300, 0x305
```

Esquema de una prueba de interrupción en el SoC:

1. El programa carga en `mtvec` la dirección de la rutina (`csrrw x0, mtvec, rs1`) y activa `mstatus.MIE` (bit 3) con `csrrsi x0, mstatus, 8`.
2. Entra en un bucle que sigue haciendo algo observable (incrementar un registro, por ejemplo).
3. La rutina, colocada con `p.org(addr)`, deja una marca (imprime una letra o escribe un registro) y termina con `MRET`.
4. El test espera unos ciclos, activa `soc.set_ui(3, 1)`, y la vuelve a bajar. La petición se recuerda hasta que se acepta, así que no hace falta mantener el pulso.
5. Comprueba la marca y que el bucle principal **continuó** tras el `MRET`.

Lo que debes tener presente al escribirlas:

- La interrupción solo se acepta en el estado `EXECUTE`, con `mstatus.MIE = 1` y sin otra en curso (`mcause = 1`). Se acepta **después** de ejecutar la instrucción en curso; `mepc` guarda la dirección de la siguiente.
- Solo `mstatus` y `mtvec` se pueden escribir; `mepc`, `mcause` y `cycle` se leen.
- `MRET` es cualquier instrucción `SYSTEM` con `funct3 = 0`; por tanto, `ECALL` y `EBREAK` también actúan como `MRET`. Esto afecta a las pruebas antiguas que los trataban como `NOP`.
- El ISS no modela interrupciones: no sirve de oráculo en estas pruebas.

## 7. Registrar la prueba en el Makefile {#makefile}

Un archivo nuevo dentro de una carpeta existente se ejecuta con el objetivo de su nivel sin tocar nada. Un módulo nuevo necesita un objetivo propio:

```make
mi-prueba: ; $(call RUN,mi_prueba,tt_um_femto,test_mi_prueba,$(SOC_SRC),)
```

Los argumentos de `RUN` son, en orden: nombre del resultado, módulo superior de Verilog, módulo de Python (sin `.py`), fuentes y argumentos de compilación.

<figure class="figure">
<img src="{{ '/assets/img/test-make-flujo.svg' | relative_url }}" alt="Flujo de make: el objetivo invoca la macro RUN, que fija variables y llama a Makefile.sim; Icarus compila y cocotb ejecuta; el resultado es un XML que report.py resume.">
<figcaption>Figura 3. Del objetivo de <code>make</code> al XML de resultados.</figcaption>
</figure>

Lista de comprobación para un módulo nuevo:

1. Colócalo en la carpeta de su nivel: así ya está en `PYTHONPATH`.
2. Añade el objetivo y inclúyelo en `.PHONY` y en la lista de `all` (o en `unit`, si es unitario).
3. Usa un **nombre de resultado propio**. Si repites uno, el XML se sobrescribe: ocurre hoy con `integration` e `integration-isa`, que escriben en el mismo `integration.xml`.
4. Si quieres que aparezca en `make report`, añade su clave a `LEVELS` en `tools/defects.py`; esa lista aún menciona módulos que ya no existen (`unit_spiram`, `unit_spiflash`) y no incluye `unit_regfile`.
5. Si es unitario, usa el *toplevel* del módulo y solo las fuentes que necesite (para el Quark: `femtorv32_quark.v` más `$(RF_SRC)`, con `-DBENCH`).

Ejecutar:

```bash
make -C test mi-prueba                     # un objetivo
make -C test unit                          # un nivel
make -C test acceptance MEM_PROFILE=standard
```

## 8. Depurar una prueba que falla {#depurar}

1. **Lee el XML, no solo el terminal.** `make` termina con éxito aunque las pruebas fallen (la macro `RUN` acaba en `|| true`). Busca `<failure` en `test/results/<perfil>/<nombre>.xml` o ejecuta `make -C test report`.
2. **Reproduce en pequeño.** Ejecuta solo tu módulo con `make -C test dbg MOD=mi_prueba`; se compila con las fuentes completas del SoC.
3. **Filtra una prueba.** Variables de entorno de cocotb como `COCOTB_TEST_FILTER=nombre` limitan la ejecución a una prueba.
4. **Imprime con `dut._log.info(...)`**, que añade el tiempo de simulación. Para el SoC, `soc.pc()`, `soc.state()` y `soc.reg(i)` muestran el estado de la CPU.
5. **Mira el bus.** `soc.flash.transactions` y `soc.ram.transactions` guardan cada transacción con sus flancos de SCK; en integración, `BusMonitor` (en `test_integration.py`) registra cada acceso con dirección, selección de periférico, máscara y estado de la FSM.
6. **Descarta primero el arranque.** Un `BootFailure` o un `None` al esperar la UART significa casi siempre que el firmware no llegó a ejecutarse o que el monitor de UART no coincide con la velocidad real.

## 9. Errores frecuentes {#errores}

| Síntoma | Causa habitual |
|---|---|
| Registros o resultados con valores aleatorios | El firmware lee un registro sin inicializar; usa `prologue(p)` |
| `AssertionError: imm=... fuera de rango` | Inmediato de 12 bits fuera de −2048…2047; usa `li` |
| Salto que cae en el sitio equivocado | `off` está en **bytes** y relativo a la instrucción del salto; calcula `etiqueta - p.pc` justo antes de emitirlo |
| Texto UART truncado o con basura | Tope de ciclos corto, falta de `uart_wait_idle`, o `UART_CYCLES_PER_BIT` (208) demasiado lejos del real (217, limitación L10) |
| La RAM devuelve datos raros | Accesos de byte o media palabra a la RAM; solo `lw`/`sw` alineados |
| Lees `RAM[0x10000]` y no aparece nada | En el modelo es `soc.ram.mem[0]`, no `mem[0x10000]` |
| `ISS: opcode no soportado` | El programa usa `SYSTEM` (CSR, `ECALL`…); el ISS no los modela |
| Programa aleatorio escribe fuera de la RAM del SoC | `DATA_BASE = 0x20000` solo existe en el banco unitario |
| La prueba pasa sola y falla en el conjunto | Reutiliza estado de otra prueba (el DUT se reinicia en cada `boot`, pero no los objetos de Python globales) |

<div class="callout dato" markdown="1">
Antes de abrir una incidencia, comprueba si el fallo ya está catalogado: la lista de fallos esperados de cada nivel y su causa está en [Verificación]({{ '/development/verificacion/' | relative_url }}).
</div>
