---
title: "Simulación y firmware"
permalink: /user/simulacion/
lead: "Cómo ejecutar la suite de verificación, cómo está construida una prueba y cómo compilar un programa en C para la flash."
---

## Preparar el entorno {#entorno}

Desde la raíz del repositorio:

```bash
sudo apt-get install iverilog
python3 -m venv .venv && . .venv/bin/activate
pip install -r test/requirements.txt
make version          # confirma iverilog y vvp
```

El `Makefile` de la raíz delega en `test/`, así que `make acceptance` y `make -C test acceptance` son equivalentes.

## Ejecutar las pruebas {#ejecutar}

```bash
cd test
make acceptance        # lo predeterminado, y lo único que corre el CI
make unit              # unit-quark, unit-multidrop y unit-uart
make integration       # 13 pruebas del SoC completo
make integration-isa   # una prueba por instrucción RV32I (40)
make functional        # 15 programas RV32I sobre el SoC
make e2e               # 6 pruebas con firmware real
make all               # todo, seguido de la tabla resumen
make report            # resumen por nivel desde results/<perfil>/*.xml
make clean             # borra sim_build, __pycache__ y results
```

Cada objetivo escribe `results/standard/<nivel>.xml`. Ejecútalos **uno tras otro, no en paralelo**: comparten `sim_build/` y `results/`.

<div class="callout aviso" markdown="1">
`make` termina con éxito aunque fallen pruebas, porque la macro `RUN` usa `|| true`. Comprueba el resultado con
`grep "<failure" results/standard/acceptance.xml` o con `make report`.
</div>

### Cuánto tarda

Las pruebas del SoC completo simulan millones de ciclos porque cada instrucción necesita más de cien ciclos de reloj para llegar desde la flash.
Según el README del repositorio, en un contenedor de pruebas:

| Objetivo | Tiempo aproximado |
|---|---|
| `unit`, `functional`, `integration-isa` | de unos segundos a decenas de segundos |
| `e2e` | cerca de 8 minutos (`test_e06_isa_selftest` por sí sola, unos 5) |
| `acceptance` | más de 10 minutos |

## Cómo está construida una prueba {#anatomia}

Las pruebas de nivel SoC no usan un `.v` de banco de pruebas: **cocotb** maneja los pines de `tt_um_femto` directamente y hace de placa.
La biblioteca de `test/lib/` aporta las piezas:

| Archivo | Contenido |
|---|---|
| `rvlib.py` | Ensamblador RV32I en Python (`R`, `I`, `L`, `S`, `B`, `JAL`, …), clase `Prog` y un simulador de referencia (ISS) |
| `spimodels.py` | Modelos de flash QSPI (`QspiFlashTarget`) y de RAM SPI (`SpiTarget`), monitor de UART |
| `soc.py` | Banco del SoC: reloj, *reset*, pines, `boot()` y utilidades de UART |
| `fw.py` | Prólogos y rutinas de firmware reutilizables, entre ellas el autotest de ISA |

Una prueba extremo a extremo completa cabe en unas pocas líneas:

```python
@cocotb.test()
async def test_e01_hello_world(dut):
    p = new_prog(); prologue(p); uart_puts(p, "Hello, RISC-V!\n"); uart_wait_idle(p); halt_loop(p)
    soc = await boot(dut, p)                       # carga el programa en el modelo de flash y hace reset
    used = await soc.run_until_uart("Hello, RISC-V!\n", 400000)
    assert used is not None, f"salida UART incompleta: {soc.uart.text()!r}"
```

El programa se ensambla en Python, se coloca en el modelo de flash y el monitor de UART decodifica lo que sale por `uo[7]`. Las pruebas pueden iniciar los registros y el contador de ciclos
con valores aleatorios para imitar el silicio real (es lo que comprueba el requisito REQ-07).

<div class="callout analisis" markdown="1">
El monitor de UART de `test/lib/soc.py` asume **208 ciclos por bit** (`UART_CYCLES_PER_BIT = 208`), mientras que `femto.v` configura la UART a 25 MHz, lo que da **192**.
Por eso fallan todas las pruebas que dependen de que el chip transmita por UART. Detalle en [UART]({{ '/development/uart/' | relative_url }}).
</div>

## Compilar firmware en C {#firmware}

```bash
cd test/firmware
make            # hello.elf → hello.bin (imagen de flash para la dirección 0)
make dis        # desensamblado con objdump
make clean
```

Los archivos clave:

| Archivo | Papel |
|---|---|
| `crt0.S` | Arranque: un `nop` en la dirección 0, pone a cero `x1` y `x3`–`x31`, fija `sp = 0x1FFF0` (final de la RAM) y llama a `main` |
| `link.ld` | `.text` y `.rodata` en una flash de 64 KiB desde `0x0`; **descarta** `.data`, `.bss`, `.sdata` y `.sbss` |
| `hello.c` | Ejemplo: texto por UART, Fibonacci, tabla en RAM, primos y LED |
| `Makefile` | `-march=rv32i -mabi=ilp32 -O2 -ffreestanding -nostdlib`, enlazado con `-lgcc` |

Que `link.ld` descarte `.data` y `.bss` significa que **no hay variables globales inicializadas ni con valor cero**: el estado debe vivir en registros, en la pila
o en direcciones de RAM que tú manejes explícitamente.

### Un programa mínimo {#programa-minimo}

```c
#include <stdint.h>
#define UART_DATA (*(volatile uint32_t *)0x400008)
#define UART_CTRL (*(volatile uint32_t *)0x400010)

static void putc_(char c) {
    while (UART_CTRL & 0x200) ;     /* espera a que tx_busy (bit 9) baje */
    UART_DATA = (uint32_t)c;
    UART_CTRL = 0x8;                /* tx_wr = 1 */
    UART_CTRL = 0x0;                /* hay que bajarlo: es un nivel, no un pulso */
}

int main(void) {
    for (const char *s = "hola\n"; *s; s++) putc_(*s);
    UART_CTRL = 0x4;                /* enciende el LED */
    for (;;) ;
}
```

Para probarlo, sustituye el cuerpo de `main` en `hello.c` (o añade tu `.c` a la regla de `hello.elf` en el `Makefile`) y ejecuta `make`.

<div class="callout nota" markdown="1">
Escribir `UART_CTRL = 0x0` apaga también el LED, porque comparten registro. Si quieres que el LED siga encendido mientras transmites, usa `0xC` y luego `0x4`.
</div>

### Salida esperada de `hello.c` {#salida-esperada}

```text
C on femto_UN
fib(10)=37
ram31sum=011D
primes<50=0F
```

Es la salida documentada en el informe de verificación; el LED queda encendido al terminar. Los valores están en hexadecimal: `0x37` es 55, `0x011D` es 285 y `0x0F` es 15.

## Interpretar los resultados {#resultados}

```bash
grep -c "<failure" results/standard/*.xml      # fallos por archivo
cat results/standard/summary.json | head       # una entrada por prueba, con estado y tiempo
```

En la página de [Verificación]({{ '/development/verificacion/' | relative_url }}) están las cifras medidas, los requisitos de aceptación y los problemas conocidos
de la propia infraestructura de pruebas.
