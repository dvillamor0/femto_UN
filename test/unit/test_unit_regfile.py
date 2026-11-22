# SPDX-License-Identifier: Apache-2.0
"""
Pruebas cocotb del banco de registros sobre SRAM 1RW1R (src/femto_regfile_sram.v +
modelo de la macro sky130_sram_32x32_1rw1r). Comprueba datos, direcciones (grupos
0-15 / 16-31), independencia entre registros y el protocolo de latencia del núcleo:

    ciclo N   : rd_en=1, rd_addr1 = A, rd_addr2 = B   (la macro muestrea A y B en el
                                                        flanco que cierra N)
    ciclo N+1 : rd_en=0                               (en el flanco que cierra N+1 se
                                                        capturan rd_data1 y rd_data2)

Los dos operandos salen a la vez (un solo ciclo de lectura). Todas las entradas
cambian tras el flanco de bajada.
"""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer

CLK_NS = 40


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    dut.rd_en.value = 0
    dut.wr_en.value = 0
    dut.rd_addr1.value = 0
    dut.rd_addr2.value = 0
    dut.wr_addr.value = 0
    dut.wr_data.value = 0
    await FallingEdge(dut.clk)


async def rf_write(dut, addr, data):
    await FallingEdge(dut.clk)
    dut.rd_en.value = 0
    dut.wr_en.value = 1
    dut.wr_addr.value = addr
    dut.wr_data.value = data
    await FallingEdge(dut.clk)      # el flanco de subida intermedio muestrea la escritura
    dut.wr_en.value = 0


async def rf_read2(dut, a, b):
    """Lee a (puerto 1 -> rd_data1) y b (puerto 0 -> rd_data2) a la vez, como el núcleo."""
    await FallingEdge(dut.clk)
    dut.wr_en.value = 0
    dut.rd_en.value = 1
    dut.rd_addr1.value = a
    dut.rd_addr2.value = b
    await FallingEdge(dut.clk)      # el flanco de subida intermedio muestrea las direcciones
    dut.rd_en.value = 0
    await RisingEdge(dut.clk)       # captura (READ_REGS)
    return dut.rd_data1.value, dut.rd_data2.value


def to_int(v):
    return int(v)


@cocotb.test()
async def test_write_read_same_register(dut):
    await start(dut)
    await rf_write(dut, 1, 0x12345678)
    da, db = await rf_read2(dut, 1, 1)
    assert to_int(da) == 0x12345678 and to_int(db) == 0x12345678


@cocotb.test()
async def test_independent_registers(dut):
    await start(dut)
    await rf_write(dut, 1, 0xAAAA5555)
    await rf_write(dut, 2, 0x0F0F0F0F)
    da, db = await rf_read2(dut, 1, 2)
    assert to_int(da) == 0xAAAA5555 and to_int(db) == 0x0F0F0F0F
    da, db = await rf_read2(dut, 2, 1)         # orden inverso
    assert to_int(da) == 0x0F0F0F0F and to_int(db) == 0xAAAA5555


@cocotb.test()
async def test_both_groups_and_last_register(dut):
    """Direcciones 15/16 (cambio de grupo) y 31 (última): sin solapes entre ellas."""
    await start(dut)
    vals = {15: 0x0000000F, 16: 0x00000010, 31: 0xDEADBEEF}
    for a, v in vals.items():
        await rf_write(dut, a, v)
    da, db = await rf_read2(dut, 15, 16)
    assert (to_int(da), to_int(db)) == (vals[15], vals[16])
    da, db = await rf_read2(dut, 31, 15)
    assert (to_int(da), to_int(db)) == (vals[31], vals[15])


@cocotb.test()
async def test_full_sweep_no_aliasing(dut):
    await start(dut)
    rng = random.Random(7)
    ref = {a: rng.getrandbits(32) for a in range(1, 32)}
    for a, v in ref.items():
        await rf_write(dut, a, v)
    for a in range(1, 31):
        da, db = await rf_read2(dut, a, a + 1)
        assert to_int(da) == ref[a], f"x{a}: {to_int(da):08x} != {ref[a]:08x}"
        assert to_int(db) == ref[a + 1], f"x{a + 1}: {to_int(db):08x} != {ref[a + 1]:08x}"


@cocotb.test()
async def test_overwrite(dut):
    await start(dut)
    await rf_write(dut, 5, 0x11111111)
    await rf_write(dut, 5, 0x22222222)
    da, _ = await rf_read2(dut, 5, 5)
    assert to_int(da) == 0x22222222


@cocotb.test()
async def test_data_valid_only_in_capture_cycle(dut):
    """Documenta la latencia: fuera del ciclo de captura la salida de la macro no es valida (X)."""
    await start(dut)
    await rf_write(dut, 3, 0xCAFEF00D)
    await rf_read2(dut, 3, 3)
    await Timer(3, unit="ns")       # > T_HOLD del modelo OpenRAM tras el flanco de subida
    assert "x" in str(dut.rd_data1.value).lower() and "x" in str(dut.rd_data2.value).lower(), \
        "las salidas deberian ser X sin lectura en curso"
