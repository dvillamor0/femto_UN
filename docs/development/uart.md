---
title: "UART"
permalink: /development/uart/
lead: "Cómo está hecha la UART tras la refactorización de la rama main: registros, transmisor y receptor por contadores, y qué velocidad sale con el reloj de 25 MHz."
---

## Estructura {#estructura}

| Módulo | Archivo | Papel |
|---|---|---|
| `peripheral_uart` | `src/perip_uart.v` | Interfaz con el bus de la CPU: decodificación de registros, retención de datos y LED |
| `uart` | `src/uart.v` | Núcleo 8N1: un contador por sentido, sin sobremuestreo |

`femto.v` instancia el periférico con `clk_freq = 25000000` y `baud = 115200`. El *reset* de la UART es **activo en alto** (`rst = !resetn`).

<div class="callout nota" markdown="1">
**Esta página describe la UART nueva.** El núcleo `uart.v` se reescribió en el *commit* `0b692c7` («refactor uart»): el antiguo generador `enable16` con sobremuestreo ×16 ya no existe, y con él desaparecen los problemas de velocidad y de bit de parada que describían versiones anteriores de esta documentación. El periférico `perip_uart.v` no cambió.
</div>

## Interfaz con la CPU {#interfaz}

`peripheral_uart` solo decodifica dos direcciones (`addr[4:0]`) y solo cuando `cs = 1`:

| `addr` | Lectura (`d_out`) | Escritura |
|---|---|---|
| `0x08` | `{24'b0, rx_data}` | Se guarda en `d_in_uart`, que alimenta a `tx_data` |
| `0x10` | `{22'b0, tx_busy, rx_avail, rx_error, 7'b0}` (bits 9, 8 y 7) | Se guarda en `uart_ctrl` |

Del registro `uart_ctrl` se usan tres bits:

| Bit | Nombre | Efecto |
|---|---|---|
| 0 | `rx_ack` | Mientras vale 1, limpia `rx_avail` y `rx_error` (el dato `rx_data` se conserva hasta la siguiente recepción) |
| 2 | LED | Se copia a la salida `LEDS` |
| 3 | `tx_wr` | Con el transmisor libre, inicia una transmisión |

Dos detalles importantes de esta interfaz:

- `tx_wr` y `rx_ack` son **niveles**, porque salen directamente de bits de `uart_ctrl`. El comentario de `uart.v` pide un pulso de un ciclo, pero la CPU no puede darlo: si `tx_wr` sigue en 1 cuando el transmisor vuelve a quedar libre, retransmite el mismo byte. Hay que bajarlo después de usarlo.
- El LED comparte registro con las señales de control: escribir `0x0` en el control apaga el LED.

## Velocidad {#baudios}

El núcleo cuenta ciclos de reloj directamente. El número de ciclos por bit se calcula en tiempo de síntesis, **redondeando al entero más próximo**:

```verilog
localparam integer CLKS_PER_BIT = (freq_hz + baud/2) / baud;
localparam integer HALF_BIT     = CLKS_PER_BIT / 2;
```

Con los parámetros del diseño:

> (25 000 000 + 57 600) / 115 200 = 217,5 → **217 ciclos por bit**

| Reloj | Ciclos por bit | Baudios reales | Desvío respecto a 115 200 |
|---|---|---|---|
| **25 MHz** (diseño) | 217 | **115 207** | **+0,006 %** |
| 24 MHz (con el mismo divisor 217) | 217 | 110 599 | −3,99 % |

Los ciclos por bit dependen del parámetro `freq_hz`, no del reloj real: si la placa funciona a otra frecuencia, el divisor no se adapta. Con el reloj nominal de 25 MHz el error es despreciable, y un carácter completo (10 bits) dura 2 170 ciclos. Son cálculos directos sobre el RTL, no resultados de simulación.

<div class="callout nota" markdown="1">
**Cambio respecto a versiones anteriores de esta documentación.** El diseño anterior daba 192 ciclos por bit (≈130 208 baudios, +13 %) y obligaba a abrir la terminal a 130208. Con el núcleo actual basta con 115200.
</div>

## Transmisor {#tx}

Una trama es: bit de inicio (0), 8 bits de datos (LSB primero), bit de parada (1). Cada bit dura `CLKS_PER_BIT` ciclos.

La máquina tiene cuatro estados (`IDLE`, `START`, `DATA`, `STOP`):

- En `IDLE`, si `tx_wr = 1`, copia `tx_data` a `tx_shift` y pasa a `START`.
- En `START`, `DATA` y `STOP` cuenta ciclos hasta `CLKS_PER_BIT − 1`; en `DATA` desplaza `tx_shift` a la derecha en cada bit y, tras el bit 7, pasa a `STOP`.
- `uart_txd` vale 0 en `START`, `tx_shift[0]` en `DATA` y 1 en el resto.
- `tx_busy` es `tx_state != IDLE`, de modo que sube **un ciclo después** de aceptar `tx_wr`. Mientras vale 1, el software no debe escribir un byte nuevo.

## Receptor {#rx}

Otra máquina de cuatro estados:

- En `IDLE`, un nivel bajo en `uart_rxd` pasa a `START`.
- En `START` espera `HALF_BIT` ciclos (unos 108) y vuelve a mirar la línea: si sigue baja, es un bit de inicio válido y pasa a `DATA`; si no, descarta el pulso.
- En `DATA` muestrea un bit cada `CLKS_PER_BIT` ciclos, es decir, hacia la mitad de cada bit, y los almacena LSB primero en `rx_shift`.
- En `STOP` espera otro bit completo y evalúa la línea **en la mitad del bit de parada**: si vale 1 guarda `rx_shift` en `rx_data` y activa `rx_avail`; si vale 0 activa `rx_error`. Después vuelve a `IDLE` sin esperar más, de modo que puede reconocer enseguida el inicio de una trama consecutiva.
- `rx_ack` limpia `rx_avail` y `rx_error`.

<div class="callout analisis" markdown="1">
**Dos observaciones sobre el receptor** (lectura del RTL, sin simularlo): no hay sincronizador de dos registros en `uart_rxd`, que es una entrada asíncrona; y el margen de muestreo es de medio bit, sin filtrado, por lo que un pulso de ruido de más de la mitad de un bit se aceptaría como inicio.
</div>

## Qué asumen las pruebas {#pruebas}

El banco de pruebas (`test/lib/soc.py` y `spimodels.py`) y varias pruebas funcionales y de extremo a extremo siguen usando **208 ciclos por bit**, un valor de la UART anterior; el RTL actual usa 217. No coinciden, aunque la diferencia es pequeña:

- **Monitor de transmisión.** Detecta el flanco de bajada, espera 1,5 bits (312 ciclos) y muestrea cada 208. Contra bits de 217 ciclos, las ocho muestras de datos y la de parada caen dentro de su bit; la más ajustada es la de parada (23 ciclos del borde).
- **Envío por RXD.** Los emisores de las pruebas usan 208 ciclos por bit contra un receptor de 217: el bit 7 se muestrea con unos 28 ciclos de margen y la muestra de parada con unos 19.

Es un cálculo sobre las fórmulas, no un resultado: los resultados guardados en `test/results/` son anteriores a la refactorización, de modo que hay que repetir la suite para saber cómo queda. Lo que sí es seguro es que `test_unit_uart.py` y otras pruebas conservan el supuesto de 208 ciclos por bit de la UART anterior y que `UART_CYCLES_PER_BIT` debería pasar a 217. Véase [Limitaciones conocidas]({{ '/development/limitaciones/' | relative_url }}#l10).

<div class="callout aviso" markdown="1">
La prueba de aceptación `REQ-05a` mide la velocidad suponiendo un reloj de **24 MHz**. Con el divisor actual (217 ciclos) eso equivale a 110 599 baudios, un −3,99 %, fuera del ±3 % que pide el requisito: por cálculo, esa prueba no debería pasar mientras el reloj de referencia sea 24 MHz y `freq_hz` siga en 25 MHz. La prueba `REQ-06c` (27 MHz) se eliminó en el mismo cambio.
</div>
