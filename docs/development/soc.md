---
title: "SoC e interconexión"
permalink: /development/soc/
lead: "Cómo se conectan la CPU, el controlador SPI y la UART dentro de femto.v, y cómo añadir un periférico nuevo."
---

## Dos módulos en un archivo {#modulos}

`src/femto.v` define dos módulos:

| Módulo | Papel |
|---|---|
| `tt_um_femto` | Envoltorio con la interfaz que exige Tiny Tapeout (`ui_in`, `uo_out`, `uio_*`, `ena`, `clk`, `rst_n`) |
| `femto` | El SoC propiamente dicho: CPU, decodificador, controlador SPI y UART |

`tt_um_femto` hace tres cosas:

- **Registra el *reset* en el flanco de bajada** (`always @(negedge clk) resetn <= rst_n`), de modo que llega estable a todos los bloques.
- **Reparte los pines** según `info.yaml` (véase [Introducción]({{ '/user/introduccion/' | relative_url }})). `uo_out[5:3]` se fijan a 0 y `uio[7:4]` quedan como entradas.
- **Agrupa las señales de datos** del bus SPI: `spi_io_o`, `spi_io_oe` y `spi_io_i` van directo a `uio_out[3:0]`, `uio_oe[3:0]` y `uio_in[3:0]`, sin `inout`.

## Decodificador de direcciones {#decodificador}

El selector `cs` tiene 7 bits en codificación *one-hot* y se calcula con `mem_address[31:16]`:

| `mem_address[31:16]` | `cs` | Destino |
|---|---|---|
| `0x0000` | `7'b0000001` (`cs[0]`) | Flash |
| `0x0001` | `7'b1000000` (`cs[6]`) | RAM SPI |
| `0x0040` | `7'b0100000` (`cs[5]`) | UART |
| cualquier otro | `7'b0000001` | Flash (alias) |

Esa última fila es la causa de que las direcciones sin mapear devuelvan datos de la flash en lugar de un error. La dirección que recibe la flash es `mem_address[21:2]`: veinte bits de palabra, 4 MiB.

<div class="callout nota" markdown="1">
**Nombres heredados.** En `femto.v`, la señal `RAM_rdata` transporta los datos de la **flash**, y `dpram_dout` los de la **RAM SPI**. Vienen de versiones anteriores del diseño; conviene tenerlo presente al leer el código.
</div>

## Multiplexor de lectura {#mux}

Un segundo bloque combinacional elige `mem_rdata` según `cs`:

```verilog
case (cs)
  7'b1000000: mem_rdata = dpram_dout;   // RAM SPI
  7'b0100000: mem_rdata = uart_dout;    // UART
  7'b0000001: mem_rdata = RAM_rdata;    // flash
  default:    mem_rdata = 32'h00000000;
endcase
```

## Protocolo de espera (*busy*) {#busy}

La CPU no conoce los tiempos del bus SPI; solo mira dos señales:

| Señal | Origen | Significado |
|---|---|---|
| `mem_rbusy` | `flash_rbusy` **OR** `ram_rbusy` | Hay una lectura en curso |
| `mem_wbusy` | `ram_wbusy` | Hay una escritura de RAM en curso |

El intercambio de una lectura de instrucción es:

1. En el estado `FETCH_INSTR` la CPU activa `mem_rstrb` durante un ciclo.
2. El controlador SPI muestrea ese *strobe* en el flanco de **bajada** del reloj y levanta `flash_rbusy` (`act_f`).
3. En `WAIT_INSTR` la CPU espera a que `mem_rbusy` baje y entonces captura `mem_rdata` en `instr`.

Como el controlador trabaja en el flanco de bajada y la CPU cambia de estado en el de subida, `busy` ya está en alto cuando la CPU lo mira por primera vez: no hay ventana en la que pueda
tomar un dato antiguo. Las cargas y almacenamientos de RAM siguen el mismo patrón en el estado `WAIT_ALU_OR_MEM`.

## Añadir un periférico {#nuevo-periferico}

`femto.v` deja comentadas las ranuras previstas: GPIO en `0x0041`, multiplicador en `0x0042`, divisor en `0x0043` y conversor binario a BCD en `0x0044`.
Para activar una de ellas, o crear la tuya:

1. Elige un prefijo libre de `mem_address[31:16]` y un bit libre de `cs` (hoy `cs[4:1]`).
2. Añade la línea al `case` del decodificador con ese bit.
3. Instancia el periférico con `.cs(cs[n])`, `.addr(mem_address[4:0])`, `.wr(wr)`, `.d_in(mem_wdata[7:0])` y su salida de lectura.
4. Añade su salida al multiplexor de lectura.
5. Los periféricos de E/S de este diseño responden de forma combinacional a la dirección, sin señal de ocupado, como hace `peripheral_uart`. Si el tuyo necesita hacer esperar a la CPU, súmalo a `mem_rbusy` o `mem_wbusy`.
6. Incluye el archivo en `source_files` de `info.yaml`, en `SOC_SRC` de `test/Makefile` y en `FPGA_SRC` del `Makefile` raíz.

<div class="callout aviso" markdown="1">
`peripheral_uart` solo mira `addr[4:0]` (sus registros están en `0x08` y `0x10`). Con `cs` ya filtrado por el decodificador no hay colisión entre periféricos, pero los registros de un periférico nuevo deben diferir dentro de esos cinco bits o necesitarán una decodificación más ancha.
</div>

## Modo `BENCH` {#bench}

Si se compila con `-DBENCH`, `femto.v` imprime en la consola del simulador cada escritura a la UART con `$write("%c", mem_wdata[7:0])`. Es una ayuda de depuración rápida,
con una salvedad: se dispara con **cualquier** escritura a la UART, incluidas las del registro de control, de modo que aparecerán también caracteres como `0x08` entre el texto.
