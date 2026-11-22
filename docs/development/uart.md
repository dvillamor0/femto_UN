---
title: "UART"
permalink: /development/uart/
lead: "Cómo está hecha la UART (registros, transmisor y receptor), y por qué con el reloj de 25 MHz no sale a 115 200 baudios."
---

## Estructura {#estructura}

| Módulo | Archivo | Papel |
|---|---|---|
| `peripheral_uart` | `src/perip_uart.v` | Interfaz con el bus de la CPU: decodificación de registros, retención de datos y LED |
| `uart` | `src/uart.v` | Núcleo 8N1 con sobremuestreo ×16 |

`femto.v` instancia el periférico con `clk_freq = 25000000` y `baud = 115200`. El *reset* de la UART es **activo en alto** (`rst = !resetn`).

## Interfaz con la CPU {#interfaz}

`peripheral_uart` solo decodifica dos direcciones (`addr[4:0]`) y solo cuando `cs = 1`:

| `addr` | Lectura (`d_out`) | Escritura |
|---|---|---|
| `0x08` | `{24'b0, rx_data}` | Se guarda en `d_in_uart`, que alimenta a `tx_data` |
| `0x10` | `{22'b0, tx_busy, rx_avail, rx_error, 7'b0}` | Se guarda en `uart_ctrl` |

Del registro `uart_ctrl` se usan tres bits:

| Bit | Nombre | Efecto |
|---|---|---|
| 0 | `rx_ack` | Mientras vale 1, limpia `rx_avail`, `rx_error` y el registro de recepción |
| 2 | LED | Se copia a la salida `LEDS` |
| 3 | `tx_wr` | Mientras vale 1 y `tx_busy = 0`, inicia una transmisión |

Dos detalles importantes de esta interfaz:

- `tx_wr` y `rx_ack` son **niveles**. Hay que bajarlos después de usarlos; de lo contrario, `tx_wr` retransmite el mismo byte en cuanto `tx_busy` baja.
- El LED comparte registro con las señales de control: escribir `0x0` en el control apaga el LED.

## Generador de baudios {#baudios}

El núcleo divide el reloj para producir un pulso `enable16` a 16 veces la velocidad en baudios:

```verilog
parameter divisor = freq_hz/baud/16;                 // división entera
wire [15:0] divisor_trunc = divisor[15:0] - 1;

// reset:              enable16_counter <= divisor_trunc
// cada ciclo:         enable16_counter <= enable16_counter - 1
// si el contador es 0: enable16_counter <= divisor_trunc - 1     // recarga
```

La recarga es `divisor − 2`, de modo que el contador recorre `divisor − 1` valores y **`enable16` se repite cada `divisor − 1` ciclos de reloj**. Un bit dura 16 pulsos de `enable16`:

> ciclos por bit = 16 × (`divisor` − 1)

<div class="callout analisis" markdown="1">
**Resultado con los parámetros actuales.** Con `clk_freq = 25000000` y `baud = 115200`, `divisor = 13` y un bit dura **192 ciclos**. La velocidad real de transmisión es 25 000 000 / 192 ≈ **130 208 baudios** (+13 %).
Es un cálculo directo sobre el RTL, comprobado con un modelo del contador; no es una simulación del diseño completo.
</div>

| Reloj | `divisor` | Ciclos por bit | Baudios reales | Desvío respecto a 115 200 |
|---|---|---|---|---|
| 24 MHz | 13 | 192 | 125 000 | +8,5 % |
| **25 MHz** (diseño actual) | 13 | 192 | **130 208** | **+13,0 %** |
| 27 MHz | 14 | 208 | 129 808 | +12,7 % |

Ninguna de las tres combinaciones queda dentro del ±3 % que pide el requisito REQ-05.

### Por qué importa para las pruebas {#pruebas}

El banco de pruebas (`test/lib/soc.py`) define `UART_CYCLES_PER_BIT = 208`, un valor que corresponde a `divisor = 14`. Como `femto.v` produce 192, el monitor de UART de las pruebas no interpreta bien lo que transmite el chip. Es la explicación más probable de que fallen todas las pruebas que dependen de la salida serie:
`i08`, `f11`, `e01`, `e02`, `e03`, `e05`, `e06` y varias de `unit_uart` (`tx_frame_format`, `tx_baud_rate_vs_spec`, `rx_at_own_timebase`, `rx_from_ideal_115200_sender`). La única prueba de extremo a extremo que pasa es `e04`, que solo usa el LED.

En otras palabras, el desajuste es real en dos sitios: **el RTL no alcanza 115 200 baudios a 25 MHz**, y **las pruebas esperan un valor distinto del que el RTL produce**. Corregir una sola de las dos no basta.

### Opciones para resolverlo {#opciones}

Son alternativas de análisis, no cambios aplicados:

1. **Ajustar la recarga.** Recargar con `divisor_trunc` en lugar de `divisor_trunc − 1` hace que `enable16` se repita cada `divisor` ciclos. A 24 MHz, `divisor = 13` da 208 ciclos por bit: 115 385 baudios, un +0,16 %.
2. **Cambiar el reloj.** El proyecto asume 25 MHz por la FPGA y por el reloj del silicio; mover a 24 MHz solo es viable si la placa lo permite.
3. **Divisor fraccionario.** Para 25 MHz, ningún periodo entero de `enable16` queda dentro del ±3 %: 13 ciclos dan +4,3 % y 14 ciclos dan −3,1 %. Un acumulador de fase (divisor fraccionario) sería la solución general.
4. **Usar la terminal a 130 208 baudios** como solución provisional en el lado del PC.

Cualquiera de las opciones 1–3 obliga a actualizar `UART_CYCLES_PER_BIT` y las comprobaciones de las pruebas.

## Transmisor {#tx}

Una trama es: bit de inicio (0), 8 bits de datos (LSB primero), bit de parada (1).

- Al ver `tx_wr && !tx_busy`, copia `tx_data` a `txd_reg`, pone `tx_busy = 1` y reinicia los contadores.
- Con cada cuenta completa de 16 pulsos de `enable16`, avanza `tx_bitcount`: el 0 saca el bit de inicio; del 1 al 8, desplaza `txd_reg` bit a bit; el 9 saca el bit de parada y el 10 baja `tx_busy`.
- Mientras `tx_busy` vale 1, el software no debe escribir un nuevo byte.

## Receptor {#rx}

- La entrada pasa por **dos registros** (`uart_rxd1`, `uart_rxd2`) para sincronizarla con el reloj.
- Al detectar un nivel bajo en un pulso `enable16` con el receptor libre, carga `rx_count16 = 7` y empieza a contar; la primera muestra cae unos 9 pulsos después, hacia la mitad del bit de inicio, y las siguientes cada 16 pulsos.
- Se desplazan los bits al registro `rxd_reg`; al final `rx_data` recibe `rxd_reg[8:1]` y `rx_avail` pasa a 1.
- `rx_error` se activa si el bit de parada no es 1.

<div class="callout peligro" markdown="1">
**El bit de parada se evalúa un bit tarde.** El receptor comprueba el bit de parada cuando `rx_bitcount == 10`, un bit después de haberlo desplazado (`== 9` sería lo esperable).
Con una pausa de al menos un carácter entre tramas funciona; con tramas consecutivas sin pausa puede ver el bit de inicio siguiente y declarar `rx_error`, además de perder el byte.
Coincide con el defecto **DEF-U2** del catálogo de `test/tools/defects.py`.
</div>
