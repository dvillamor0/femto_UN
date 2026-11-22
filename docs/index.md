---
title: "femto_UN"
permalink: /
home: true
eyebrow: "Tiny Tapeout · sky130A"
lead: "Un microcontrolador RISC-V sin memoria interna. Ejecuta el código desde una flash QSPI externa, guarda sus datos en una RAM SPI y se comunica por UART."
---

<div class="specs">
<div class="spec"><b>RV32I</b><span>CPU FemtoRV32 Quark, sin extensiones M ni C</span></div>
<div class="spec"><b>25 MHz</b><span>reloj nominal (también el de la FPGA de prueba)</span></div>
<div class="spec"><b>4×2</b><span>tiles de Tiny Tapeout en sky130A</span></div>
<div class="spec"><b>QSPI + SPI</b><span>flash y RAM comparten un único bus de 4 líneas</span></div>
<div class="spec"><b>UART 8N1</b><span>más un LED controlado por software</span></div>
<div class="spec"><b>10 pines</b><span>usados de los 24 disponibles del proyecto</span></div>
</div>

## Qué es {#que-es}

**femto_UN** es la adaptación de [FemtoRV32 *Quark*](https://github.com/BrunoLevy/learn-fpga), el núcleo RV32I de Bruno Levy, a un
proyecto de [Tiny Tapeout](https://tinytapeout.com) de la Universidad Nacional de Colombia. El chip no incluye memoria
de programa ni de datos: todo pasa por un único controlador SPI que atiende dos dispositivos externos.

<figure class="figure">
<img src="{{ '/assets/img/soc-bloques.svg' | relative_url }}" alt="Diagrama de bloques: la CPU Quark, un decodificador de direcciones, el controlador SPI multidrop con la flash y la RAM externas, y la UART con el USB-serial y el LED.">
<figcaption>Figura 1. Bloques de <code>tt_um_femto</code>. Todo lo que está a la derecha del recuadro es hardware externo.</figcaption>
</figure>

- El **código** vive en la flash y se lee en modo *Quad I/O* (`0xEB`), 32 bits por acceso.
- Los **datos y la pila** viven en la RAM SPI, a partir de la dirección `0x0001_0000`.
- La **consola** es la UART (`0x0040_0000`); un bit de su registro de control enciende el LED.

## Cómo está organizada esta documentación {#organizacion}

<div class="cards">
<a class="card" href="{{ '/tools/' | relative_url }}"><small>Primeros pasos</small><strong>Herramientas</strong><span>Qué instalar para simular, compilar firmware, sintetizar y programar.</span></a>
<a class="card" href="{{ '/user/introduccion/' | relative_url }}"><small>Primeros pasos</small><strong>Introducción</strong><span>Estructura del repositorio, mapa de memoria, registros y pines.</span></a>
<a class="card" href="{{ '/user/simulacion/' | relative_url }}"><small>Primeros pasos</small><strong>Simulación y firmware</strong><span>Ejecutar la suite de pruebas y compilar un programa en C.</span></a>
<a class="card" href="{{ '/user/hardware/' | relative_url }}"><small>Primeros pasos</small><strong>Prueba en hardware</strong><span>Conexiones, preparación de la flash y lectura por el puerto serie.</span></a>
<a class="card" href="{{ '/development/spi-multidrop/' | relative_url }}"><small>Diseño</small><strong>Bus SPI multidrop</strong><span>El controlador único de flash y RAM, fase por fase.</span></a>
<a class="card" href="{{ '/development/verificacion/' | relative_url }}"><small>Calidad</small><strong>Verificación</strong><span>Niveles de prueba, requisitos de aceptación y resultados medidos.</span></a>
</div>

Si buscas algo concreto:

| Quiero… | Ve a |
|---|---|
| Saber qué dirección usar para la UART o la RAM | [Introducción]({{ '/user/introduccion/' | relative_url }}) |
| Ejecutar las pruebas o compilar `hello.c` | [Simulación y firmware]({{ '/user/simulacion/' | relative_url }}) |
| Conectar flash, RAM y dongle serie | [Prueba en hardware]({{ '/user/hardware/' | relative_url }}) |
| Entender cómo se lee una instrucción de la flash | [Bus SPI multidrop]({{ '/development/spi-multidrop/' | relative_url }}) |
| Sintetizar para la Colorlight i9 | [Prototipo en FPGA]({{ '/development/fpga/' | relative_url }}) |
| Generar el GDS con LibreLane | [Flujo ASIC]({{ '/development/asic/' | relative_url }}) |
| Saber qué no funciona todavía | [Limitaciones conocidas]({{ '/development/limitaciones/' | relative_url }}) |

## Estado actual {#estado}

<div class="callout aviso" markdown="1">
**Lee esto antes de usar la UART.** Con `clk_freq = 25000000` el generador de baudios de `uart.v` produce **192 ciclos por bit**, es decir
unos **130 208 baudios** y no 115 200. Las pruebas que dependen de la UART esperan 208 ciclos por bit y por eso fallan. El análisis completo está en
[UART]({{ '/development/uart/' | relative_url }}) y la lista de pendientes en [Limitaciones conocidas]({{ '/development/limitaciones/' | relative_url }}).
</div>

- El núcleo **Quark** y el **controlador multidrop** pasan sus 20 pruebas unitarias cada uno.
- La RAM solo admite accesos de palabra completa y alineados (`lw`/`sw`); los accesos de byte y media palabra fallan.
- El flujo ASIC y el de FPGA están automatizados con `make` (véase [Flujo ASIC]({{ '/development/asic/' | relative_url }}) y [Prototipo en FPGA]({{ '/development/fpga/' | relative_url }})).

## Créditos {#creditos}

FemtoRV32 es obra de Bruno Levy (con Matthias Koch). El proyecto femto_UN fue adaptado por la Universidad Nacional de Colombia;
el autor registrado en `info.yaml` es Carlos Camargo Bareño. Licencia Apache-2.0.
