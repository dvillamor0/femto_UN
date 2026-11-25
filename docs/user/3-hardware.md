---
title: "Prueba en hardware"
permalink: /user/hardware/
lead: "De la imagen binaria a la primera línea de texto en la terminal. Sirve tanto para el chip de Tiny Tapeout como para la FPGA de prototipo."
---

## Qué necesitas {#material}

- Una **flash SPI con modo Quad** (familia W25Q o equivalente) con la imagen del programa.
- Una **RAM SPI con direccionamiento de 3 bytes** (familia 23LC1024 o similar). El controlador envía comando, un byte `0x00` y 16 bits de dirección; las RAM de 2 bytes de dirección no sirven.
- Un **dongle USB-serie** a 3,3 V.
- Un **LED** con su resistencia (opcional).
- Un programador de flash externo, o el propio que traiga la placa.

<div class="callout aviso" markdown="1">
La flash debe tener activado el bit **QE** (*Quad Enable*) para que IO2 e IO3 funcionen como líneas de datos. En muchas flashes de la familia W25Q es un bit no volátil
que se programa una sola vez; comprueba el valor de fábrica de tu referencia en su hoja de datos.
</div>

## Conexiones {#conexiones}

Flash y RAM comparten reloj y líneas de datos; solo los selectores de chip son independientes.

| Señal | Pin del chip | Flash | RAM |
|---|---|---|---|
| SCK | `uo[0]` | CLK | SCK |
| CS flash | `uo[1]` | CS# | — |
| CS RAM | `uo[2]` | — | CS# |
| IO0 | `uio[0]` | DI (IO0) | SI |
| IO1 | `uio[1]` | DO (IO1) | SO |
| IO2 | `uio[2]` | WP# (IO2) | — |
| IO3 | `uio[3]` | HOLD# (IO3) | HOLD# (opcional) |
| TXD | `uo[7]` | — | — |
| RXD | `ui[2]` | — | — |
| LEDS | `uo[6]` | — | — |

Notas de cableado:

- Cruza la UART: `TXD` del chip va al **RX** del dongle y `RXD` del chip al **TX** del dongle, con tierra común.
- Durante una transacción de RAM el maestro mantiene IO2 e IO3 en 1 (WP# y HOLD# inactivos), de modo que unir IO3 al HOLD# de la RAM es seguro.
- Verifica la numeración de pines de tu encapsulado en la hoja de datos de cada memoria antes de soldar.

## Preparar la flash {#flash}

1. Compila el programa: `make -C test/firmware` produce `hello.bin`.
2. Grábalo en la flash **a partir del *offset* 0**, sin cabeceras. El controlador reordena los bytes de cada palabra, así que la imagen es la misma que genera `objcopy`.
3. Mantén la imagen por debajo de 64 KiB: a partir de `0x0001_0000` el decodificador apunta a la RAM.

## Arrancar y leer la consola {#arranque}

1. Alimenta el sistema y mantén `rst_n` en bajo unos ciclos; suéltalo.
2. Abre el puerto serie del dongle (por ejemplo `picocom -b 115200 /dev/ttyUSB0`).
3. Deberías ver:

```text
C on femto_UN
fib(10)=37
ram31sum=011D
primes<50=0F
```

y el LED encendido al final. Esa salida es la que figura en el informe de verificación; no se ha reproducido en hardware con este RTL.

<div class="callout nota" markdown="1">
**Velocidad del puerto serie.** Con el reloj de 25 MHz, la UART actual sale a **115 207 baudios** (217 ciclos por bit), así que la terminal se abre a 115200. El divisor se calcula para 25 MHz: si la placa usa otro reloj, la velocidad cambia en proporción (véase [UART]({{ '/development/uart/' | relative_url }}#baudios)).
</div>

## Si no aparece nada {#diagnostico}

Recorre la cadena de fuera hacia dentro con un analizador lógico o un osciloscopio:

| Compruebe | Qué debe verse |
|---|---|
| Reloj y `rst_n` | Reloj de 25 MHz; `rst_n` sube después de unos ciclos |
| `uo[1]` (CS flash) | Baja poco después del *reset*, antes del primer pulso de SCK |
| `uo[0]` (SCK) | Ráfagas de 28 pulsos a un cuarto del reloj (6,25 MHz con 25 MHz) |
| `uio[0]` | Los 8 primeros bits son `0xEB` (`1110 1011`) |
| Datos de la flash | Un valor distinto de `0xFFFF_FFFF` (una flash sin programar devuelve todo unos) |
| `uo[7]` (TXD) | En reposo está en alto; baja con cada bit de inicio |

Si la flash responde pero la CPU no avanza, revisa que la RAM esté conectada: las instrucciones de carga y almacenamiento esperan a que termine la transacción SPI de la RAM.

## Con la FPGA Colorlight i9 {#fpga}

La FPGA **no tiene memoria**: la flash y la RAM también son externas y se cablean a los pines indicados en `config/colorlight_i9.lpf`.

```bash
make fpga-bit     # síntesis, colocación y rutado → build/fpga/top_fpga.bit
make fpga-prog    # carga en SRAM (volátil)
make fpga-flash   # graba en la flash de la placa (persistente)
```

Los detalles del envoltorio y de los pines están en [Prototipo en FPGA]({{ '/development/fpga/' | relative_url }}).
