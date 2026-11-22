# SPDX-License-Identifier: Apache-2.0
"""
PRUEBAS UNITARIAS de src/MappedSPIMultidrop.v  (controlador único: flash QSPI + RAM SPI en un bus compartido)

    flash : SOLO Quad SPI, Fast Read Quad I/O 0xEB
            8 ciclos opcode (IO0) | 6 dirección (IO3..IO0) | 2 modo (0x00, manejados) | 4 dummy | 8 datos  = 28 ciclos de SCK
    RAM   : SOLO SPI estándar (IO0 = MOSI, IO1 = MISO)
            lectura  0x03 | 0x00 | addr[15:0] | 32 bits recibidos      = 64 ciclos de SCK
            escritura 0x02 | 0x00 | addr[15:0] | 32 bits enviados      = 64 ciclos de SCK
    Comparten SCK e IO0..IO3; cada memoria tiene su CS_N.

Interfaz del DUT (todo opera en el flanco de BAJADA de `clk`):
    lado CPU flash : flash_rstrb  flash_word_address[19:0]  flash_rdata[31:0]  flash_rbusy
    lado CPU RAM   : ram_rd ram_wr  ram_word_address[15:0]  ram_wdata[31:0]  ram_rdata[31:0]  ram_rbusy ram_wbusy
    pines SPI      : spi_sck  spi_cs_flash_n  spi_cs_ram_n  spi_io_o[3:0]  spi_io_oe[3:0]  spi_io_i[3:0]
Parámetros: FLASH_DIV=2 (SCK flash = 4 ciclos de clk), RAM_DIV=5 (SCK RAM = 10 ciclos de clk).

Los esclavos son modelos de spimodels.py conectados al MISMO bus: QspiFlashTarget (0xEB) y SpiTarget (RAM estándar).
Un monitor del banco comprueba cada ciclo las invariantes del bus (exclusión mutua de CS_N, SCK sólo del dueño,
habilitaciones io_oe según la fase).
"""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, Edge, FallingEdge, RisingEdge
from cocotb.utils import get_sim_time

from spimodels import QspiFlashTarget, SpiTarget, geti, getm

SYS_NS = 20
FLASH_DIV = 2
RAM_DIV = 5
FLASH_SCK_PERIOD = 2 * FLASH_DIV
RAM_SCK_PERIOD = 2 * RAM_DIV
FLASH_CYCLES = 28
RAM_CYCLES = 64


class MdPins:
    """Pines de un esclavo sobre el bus compartido. 3er valor de read(): nibble (flash) o IO0 = MOSI (RAM)."""

    def __init__(self, bench, which):
        self.bench, self.dut, self.which = bench, bench.dut, which
        self.quad = which == "flash"
        self._cs = bench.dut.spi_cs_flash_n if self.quad else bench.dut.spi_cs_ram_n
        self.triggers = [Edge(bench.dut.spi_sck), Edge(self._cs), Edge(bench.dut.spi_io_o)]

    def read(self):
        io = getm(self.dut.spi_io_o) & 0xF
        return geti(self.dut.spi_sck, 0), geti(self._cs, 1), (io if self.quad else io & 1)

    def drive_miso(self, v):
        self.bench.drive(self.which, v)


class MdBench:
    def __init__(self, dut, miso_delay_ns=0.0):
        self.dut = dut
        self.drv = {"flash": 0, "ram": 0}
        self.flash = QspiFlashTarget(MdPins(self, "flash"), miso_delay_ns=miso_delay_ns, size=1 << 22)
        self.ram = SpiTarget(MdPins(self, "ram"), kind="ram", profile="standard",
                             miso_delay_ns=miso_delay_ns, size=1 << 16)
        self.violations = []
        self.oe_seen = {"flash": {}, "ram": set()}    # flash: {io_oe: [nº de subidas de SCK vistas]}
        self.sck_seen_by = {"flash": 0, "ram": 0, "idle": 0}

    def drive(self, who, v):
        self.drv[who] = v
        self.dut.spi_io_i.value = (self.drv["flash"] & 0xF) | ((self.drv["ram"] & 1) << 1)

    async def start(self, reset_cycles=6):
        d = self.dut
        cocotb.start_soon(Clock(d.clk, SYS_NS, unit="ns").start())
        d.reset.value = 0
        d.flash_rstrb.value = 0
        d.flash_word_address.value = 0
        d.ram_rd.value = 0
        d.ram_wr.value = 0
        d.ram_word_address.value = 0
        d.ram_wdata.value = 0
        d.spi_io_i.value = 0
        cocotb.start_soon(self.flash.run())
        cocotb.start_soon(self.ram.run())
        await ClockCycles(d.clk, reset_cycles)
        await FallingEdge(d.clk)
        d.reset.value = 1
        cocotb.start_soon(self._monitor())
        await ClockCycles(d.clk, 3)

    async def _monitor(self):
        """Invariantes del bus compartido, muestreadas cada ciclo (en el flanco de subida)."""
        d = self.dut
        while True:
            await RisingEdge(d.clk)
            if geti(d.reset) == 0:
                continue
            csf, csr = geti(d.spi_cs_flash_n), geti(d.spi_cs_ram_n)
            sck, oe = geti(d.spi_sck), geti(d.spi_io_oe)
            io_o = getm(d.spi_io_o)
            if None in (csf, csr, sck, oe):
                continue
            t = get_sim_time("ns")
            if csf == 0 and csr == 0:
                self.violations.append(f"{t}ns: ambos CS_N en 0 (conflicto en el bus)")
            who = "flash" if csf == 0 else "ram" if csr == 0 else "idle"
            if sck:
                self.sck_seen_by[who] += 1
                if who == "idle":
                    self.violations.append(f"{t}ns: SCK en 1 sin ningún CS_N activo")
            if who == "idle":
                if oe != 0b1100 or (io_o >> 2) != 0b11:
                    self.violations.append(f"{t}ns: bus en reposo mal: io_oe={oe:04b} io_o={io_o:04b} "
                                           "(esperado IO2/IO3 = 1 manejados, IO0/IO1 liberados)")
            elif who == "ram":
                self.oe_seen["ram"].add(oe)
                if oe != 0b1101 or (io_o >> 2) != 0b11:
                    self.violations.append(f"{t}ns: RAM: io_oe={oe:04b} io_o={io_o:04b} (esperado 1101 y IO2/IO3 = 1)")
            else:
                n = len(self.flash.cur["rises"]) if self.flash.cur else 0
                self.oe_seen["flash"].setdefault(oe, []).append(n)
                if oe not in (0b1101, 0b1111, 0b0000):
                    self.violations.append(f"{t}ns: flash: io_oe={oe:04b} inesperado")
                if oe == 0b1101 and (io_o >> 1) != 0b111:
                    self.violations.append(f"{t}ns: flash/opcode: IO2/IO3/IO1 deben ir en 1 (io_o={io_o:04b})")

    # ---- driver: hace de CPU (strobe de 1 ciclo y espera a que baje busy) ---------------
    async def _issue(self, strobes, vals, busy_sig, other_busy_sigs, max_cycles=6000):
        d = self.dut
        await RisingEdge(d.clk)
        for sig, v in vals.items():
            getattr(d, sig).value = v
        for s in strobes:
            getattr(d, s).value = 1
        await RisingEdge(d.clk)
        for s in strobes:
            getattr(d, s).value = 0
        info = {"busy_first_edge": geti(getattr(d, busy_sig)),
                "others_first_edge": [geti(getattr(d, o)) for o in other_busy_sigs]}
        n = 0
        while geti(getattr(d, busy_sig)) == 1:
            await RisingEdge(d.clk)
            n += 1
            assert n < max_cycles, f"timeout esperando fin de {busy_sig}"
        info["cycles"] = n
        info["cs_flash_after"] = geti(d.spi_cs_flash_n)
        info["cs_ram_after"] = geti(d.spi_cs_ram_n)
        return info

    async def flash_read(self, word_addr):
        info = await self._issue(["flash_rstrb"], {"flash_word_address": word_addr}, "flash_rbusy",
                                 ["ram_rbusy", "ram_wbusy"])
        info["rdata"] = geti(self.dut.flash_rdata)
        info["t"] = self.flash.transactions[-1] if self.flash.transactions else None
        return info

    async def ram_read(self, addr):
        info = await self._issue(["ram_rd"], {"ram_word_address": addr}, "ram_rbusy",
                                 ["flash_rbusy", "ram_wbusy"])
        info["rdata"] = geti(self.dut.ram_rdata)
        info["t"] = self.ram.transactions[-1] if self.ram.transactions else None
        return info

    async def ram_write(self, addr, wdata):
        info = await self._issue(["ram_wr"], {"ram_word_address": addr, "ram_wdata": wdata}, "ram_wbusy",
                                 ["flash_rbusy", "ram_rbusy"])
        info["t"] = self.ram.transactions[-1] if self.ram.transactions else None
        return info

    def put_flash_word(self, wa, v):
        self.flash.mem[4 * wa:4 * wa + 4] = v.to_bytes(4, "little")

    async def idle(self, n):
        await ClockCycles(self.dut.clk, n)

    def check_bus(self):
        assert not self.violations, "invariantes del bus violadas:\n  " + "\n  ".join(self.violations[:8])


async def make_bench(dut, **kw):
    b = MdBench(dut, **kw)
    await b.start()
    return b


# ==========================================================================
# PRUEBAS
# ==========================================================================
@cocotb.test()
async def test_reset_idle(dut):
    """Tras reset: ambos CS_N=1, busy=0, SCK=0, IO2/IO3 manejados en 1 e IO0/IO1 liberados; sin actividad SPI."""
    b = await make_bench(dut)
    for _ in range(300):
        await RisingEdge(dut.clk)
        assert geti(dut.spi_cs_flash_n) == 1 and geti(dut.spi_cs_ram_n) == 1
        assert geti(dut.flash_rbusy) == 0 and geti(dut.ram_rbusy) == 0 and geti(dut.ram_wbusy) == 0
        assert geti(dut.spi_sck) == 0
        assert geti(dut.spi_io_oe) == 0b1100, f"io_oe={geti(dut.spi_io_oe):04b}"
        assert (getm(dut.spi_io_o) >> 2) == 0b11
    assert not b.flash.transactions and not b.ram.transactions
    b.check_bus()


@cocotb.test()
async def test_flash_quad_read_protocol_and_data(dut):
    """Flash: opcode 0xEB, dirección de bytes 4*wa en 6 nibbles, byte de modo 0x00, 28 pulsos de SCK, dato LE exacto."""
    b = await make_bench(dut)
    wa = 0x0123
    b.put_flash_word(wa, 0xA1B2C3D4)
    r = await b.flash_read(wa)
    await b.idle(20)
    t = r["t"]
    dut._log.info(f"cmd=0x{t['cmd']:02x} addr=0x{t['addr']:06x} modo=0x{t['mode_val']:02x} pulsos={len(t['rises'])} "
                  f"rdata=0x{r['rdata']:08x} ciclos={r['cycles']}")
    assert r["busy_first_edge"] == 1, "flash_rbusy debe estar activo en el primer flanco tras flash_rstrb"
    assert r["others_first_edge"] == [0, 0], "la RAM no debe marcar busy durante una lectura de flash"
    assert t["cmd"] == 0xEB, f"opcode=0x{t['cmd']:02x}, esperado 0xEB (Fast Read Quad I/O)"
    assert t["addr"] == 4 * wa, f"dirección=0x{t['addr']:06x}, esperada 0x{4 * wa:06x}"
    assert t["mode_val"] == 0x00, f"byte de modo=0x{t['mode_val']:02x}"
    assert len(t["rises"]) == FLASH_CYCLES, f"pulsos de SCK={len(t['rises'])}, esperados {FLASH_CYCLES}"
    assert r["rdata"] == 0xA1B2C3D4, f"rdata=0x{r['rdata']:08x}"
    assert not b.ram.transactions, "la RAM no debe ver ninguna transacción"
    assert r["cs_flash_after"] == 1, "CS_N de la flash debe haber subido cuando baja flash_rbusy"
    b.check_bus()


@cocotb.test()
async def test_flash_byte_order_little_endian(dut):
    """La flash guarda bytes 01 02 03 04 (dirección creciente); flash_rdata debe ser 0x04030201."""
    b = await make_bench(dut)
    b.flash.mem[0:4] = bytes([1, 2, 3, 4])
    r = await b.flash_read(0)
    assert r["rdata"] == 0x04030201, f"rdata=0x{r['rdata']:08x}"
    b.check_bus()


@cocotb.test()
async def test_flash_address_range(dut):
    """Direcciones extremas de la flash (20 bits de palabra = 4 MiB) llegan completas y devuelven su dato."""
    b = await make_bench(dut)
    for wa in (0x00000, 0x00001, 0x80000, 0xFFFFF, 0x55555, 0xAAAAA):
        b.put_flash_word(wa, 0x13579BDF ^ wa)
    for wa in (0x00000, 0x00001, 0x80000, 0xFFFFF, 0x55555, 0xAAAAA):
        r = await b.flash_read(wa)
        assert r["t"]["addr"] == 4 * wa, f"wa=0x{wa:05x}: dirección vista 0x{r['t']['addr']:06x}"
        assert r["rdata"] == (0x13579BDF ^ wa), f"wa=0x{wa:05x}: 0x{r['rdata']:08x}"
    b.check_bus()


@cocotb.test()
async def test_flash_sck_period_and_duration(dut):
    """SCK de la flash = 2*FLASH_DIV = 4 ciclos de clk (50 % de ciclo de trabajo); 28 pulsos en total."""
    b = await make_bench(dut)
    b.put_flash_word(5, 0x11223344)
    r = await b.flash_read(5)
    await b.idle(20)
    t = b.flash.transactions[-1]
    periods = {round((r1 - r0) / SYS_NS) for r0, r1 in zip(t["rises"], t["rises"][1:])}
    assert periods == {FLASH_SCK_PERIOD}, f"periodos (ciclos) = {sorted(periods)}, esperado {FLASH_SCK_PERIOD}"
    ev = sorted([(x, "r") for x in t["rises"]] + [(x, "f") for x in t["falls"]])
    hi = {round((t1 - t0) / SYS_NS) for (t0, k0), (t1, k1) in zip(ev, ev[1:]) if k0 == "r" and k1 == "f"}
    lo = {round((t1 - t0) / SYS_NS) for (t0, k0), (t1, k1) in zip(ev, ev[1:]) if k0 == "f" and k1 == "r"}
    assert hi == lo == {FLASH_DIV}, f"SCK alto={sorted(hi)} bajo={sorted(lo)}"
    assert FLASH_CYCLES * FLASH_SCK_PERIOD - 2 <= r["cycles"] <= FLASH_CYCLES * FLASH_SCK_PERIOD + 6, r["cycles"]
    b.check_bus()


@cocotb.test()
async def test_flash_bus_phases(dut):
    """Habilitaciones de la flash por fase: opcode io_oe=1101, dirección+modo 1111, dummy+datos 0000 (bus liberado);
    el maestro nunca maneja el bus mientras la flash entrega datos."""
    b = await make_bench(dut)
    b.put_flash_word(3, 0x55AA55AA)
    await b.flash_read(3)
    await b.idle(10)
    seen = b.oe_seen["flash"]
    dut._log.info({format(k, '04b'): (min(v), max(v), len(v)) for k, v in seen.items()})
    assert set(seen) == {0b1101, 0b1111, 0b0000}, f"io_oe vistos {sorted(map(bin, seen))}"
    assert max(seen[0b1101]) <= 8, "opcode: 1 línea manejada sólo durante los 8 primeros pulsos"
    assert min(seen[0b1111]) >= 7 and max(seen[0b1111]) <= 17, "dirección+modo (4 líneas) = pulsos 9..16"
    assert min(seen[0b0000]) >= 15, "el bus sólo se libera tras la dirección y los 2 ciclos de modo"
    assert len(seen[0b0000]) >= 4 * (4 + 8) - 8, "dummy (4) + datos (8) ciclos de SCK con el bus liberado"
    b.check_bus()


@cocotb.test()
async def test_ram_read_protocol_and_data(dut):
    """RAM en SPI estándar: 0x03 + 0x00 + dirección de 16 bits, 64 pulsos, dato exacto, IO0=MOSI e IO1=MISO."""
    b = await make_bench(dut)
    b.ram.set_word_be(0x0120, 0xDEADBEEF)
    r = await b.ram_read(0x0120)
    await b.idle(20)
    t = r["t"]
    assert r["busy_first_edge"] == 1
    assert r["others_first_edge"] == [0, 0], "ni flash_rbusy ni ram_wbusy deben estar activos"
    assert t["cmd"] == 0x03 and t["addr"] == 0x0120, f"cmd=0x{t['cmd']:02x} addr=0x{t['addr']:06x}"
    assert len(t["rises"]) == RAM_CYCLES, f"pulsos={len(t['rises'])}"
    assert r["rdata"] == 0xDEADBEEF, f"rdata=0x{r['rdata']:08x}"
    assert not b.flash.transactions, "la flash no debe ver ninguna transacción"
    b.check_bus()


@cocotb.test()
async def test_ram_write_protocol_and_data(dut):
    """Escritura de RAM: 0x02 + 0x00 + dirección + 32 bits; se almacena en la RAM y la flash no se entera."""
    b = await make_bench(dut)
    r = await b.ram_write(0x0200, 0x12345678)
    await b.idle(20)
    t = r["t"]
    assert r["busy_first_edge"] == 1, "ram_wbusy debe estar activo en el primer flanco tras ram_wr"
    assert r["others_first_edge"] == [0, 0]
    assert t["cmd"] == 0x02 and t["addr"] == 0x0200
    assert len(t["rises"]) == RAM_CYCLES, f"pulsos={len(t['rises'])}"
    assert b.ram.get_word_be(0x0200) == 0x12345678, f"RAM[0x200]=0x{b.ram.get_word_be(0x200):08x}"
    assert not b.flash.transactions
    b.check_bus()


@cocotb.test()
async def test_ram_sck_period(dut):
    """SCK de la RAM = 2*RAM_DIV = 10 ciclos (distinto del de la flash en el mismo pin SCK), 50 % de ciclo de trabajo."""
    b = await make_bench(dut)
    await b.ram_read(0x10)
    await b.idle(20)
    t = b.ram.transactions[-1]
    periods = {round((r1 - r0) / SYS_NS) for r0, r1 in zip(t["rises"], t["rises"][1:])}
    assert periods == {RAM_SCK_PERIOD}, f"periodos (ciclos) = {sorted(periods)}, esperado {RAM_SCK_PERIOD}"
    b.check_bus()


@cocotb.test()
async def test_ram_write_then_read_roundtrip(dut):
    """Escribe varias palabras en la RAM y las lee de vuelta; cada escritura toca sólo su palabra."""
    b = await make_bench(dut)
    vals = {0x0000: 0x00000001, 0x0004: 0xFFFFFFFF, 0x0008: 0x80000000, 0x7FFC: 0xCAFEBABE, 0xFFFC: 0x0BADF00D}
    for a, v in vals.items():
        await b.ram_write(a, v)
    for a, v in vals.items():
        r = await b.ram_read(a)
        assert r["rdata"] == v, f"RAM[0x{a:04x}] leyó 0x{r['rdata']:08x}, esperado 0x{v:08x}"
    b.check_bus()


@cocotb.test()
async def test_alternating_flash_ram_traffic(dut):
    """Alterna flash / RAM sin huecos: cada transacción va a su memoria, con el dato correcto y sin interferencias."""
    b = await make_bench(dut)
    for i in range(6):
        b.put_flash_word(i, 0x10000000 + i * 0x01010101)
    for i in range(6):
        await b.ram_write(4 * i, 0xA0000000 + i)
        r = await b.flash_read(i)
        assert r["rdata"] == 0x10000000 + i * 0x01010101, f"flash[{i}] = 0x{r['rdata']:08x}"
        r = await b.ram_read(4 * i)
        assert r["rdata"] == 0xA0000000 + i, f"RAM[{4 * i}] = 0x{r['rdata']:08x}"
    assert len(b.flash.transactions) == 6 and len(b.ram.transactions) == 12
    assert all(t["cmd"] == 0xEB for t in b.flash.transactions)
    b.check_bus()


@cocotb.test()
async def test_random_mixed_traffic(dut):
    """Tráfico aleatorio flash/RAM-rd/RAM-wr con huecos aleatorios, contra un modelo en Python."""
    b = await make_bench(dut)
    rng = random.Random(20260513)
    flash_words = {}
    for wa in range(32):
        flash_words[wa] = rng.getrandbits(32)
        b.put_flash_word(wa, flash_words[wa])
    ram_model = {}
    for _ in range(60):
        k = rng.choice(["f", "r", "w"])
        if k == "f":
            wa = rng.randrange(32)
            r = await b.flash_read(wa)
            assert r["rdata"] == flash_words[wa], f"flash[{wa}] 0x{r['rdata']:08x} != 0x{flash_words[wa]:08x}"
        elif k == "w":
            a = rng.randrange(0, 0x400, 4)
            v = rng.getrandbits(32)
            await b.ram_write(a, v)
            ram_model[a] = v
        else:
            if not ram_model:
                continue
            a = rng.choice(sorted(ram_model))
            r = await b.ram_read(a)
            assert r["rdata"] == ram_model[a], f"RAM[0x{a:x}] 0x{r['rdata']:08x} != 0x{ram_model[a]:08x}"
        await b.idle(rng.randrange(0, 15))
    b.check_bus()


@cocotb.test()
async def test_shared_sck_never_moves_without_cs(dut):
    """SCK sólo se mueve mientras algún CS_N está activo, y cada memoria sólo ve pulsos de su propia transacción."""
    b = await make_bench(dut)
    b.put_flash_word(3, 0x55AA55AA)
    await b.flash_read(3)
    await b.ram_write(0x40, 0x0F0F0F0F)
    await b.ram_read(0x40)
    await b.idle(30)
    assert b.sck_seen_by["flash"] > 0 and b.sck_seen_by["ram"] > 0
    assert b.sck_seen_by["idle"] == 0, "SCK no debe moverse sin CS_N activo"
    assert [len(t["rises"]) for t in b.flash.transactions] == [FLASH_CYCLES]
    assert [len(t["rises"]) for t in b.ram.transactions] == [RAM_CYCLES, RAM_CYCLES]
    b.check_bus()


@cocotb.test()
async def test_flash_priority_over_ram(dut):
    """Si flash_rstrb y ram_wr llegan a la vez (no ocurre con una sola CPU) gana la flash; nunca se mezclan en el bus."""
    b = await make_bench(dut)
    b.put_flash_word(9, 0xFACEFEED)
    await RisingEdge(dut.clk)
    dut.flash_word_address.value = 9
    dut.ram_word_address.value = 0x80
    dut.ram_wdata.value = 0x77777777
    dut.flash_rstrb.value = 1
    dut.ram_wr.value = 1
    await RisingEdge(dut.clk)
    dut.flash_rstrb.value = 0
    dut.ram_wr.value = 0
    n = 0
    while geti(dut.flash_rbusy) == 1:
        await RisingEdge(dut.clk)
        n += 1
        assert n < 4000
    assert geti(dut.flash_rdata) == 0xFACEFEED
    await b.idle(40)
    assert len(b.flash.transactions) == 1
    assert not b.ram.transactions, "el pedido simultáneo de RAM se descarta (un solo maestro): no debe quedar a medias"
    b.check_bus()


@cocotb.test()
async def test_ram_write_priority_over_read(dut):
    """Si ram_rd y ram_wr coinciden, gana la escritura."""
    b = await make_bench(dut)
    await RisingEdge(dut.clk)
    dut.ram_word_address.value = 0x30
    dut.ram_wdata.value = 0x13579BDF
    dut.ram_rd.value = 1
    dut.ram_wr.value = 1
    await RisingEdge(dut.clk)
    dut.ram_rd.value = 0
    dut.ram_wr.value = 0
    n = 0
    while geti(dut.ram_wbusy) == 1 or geti(dut.ram_rbusy) == 1:
        await RisingEdge(dut.clk)
        n += 1
        assert n < 4000
    await b.idle(20)
    assert len(b.ram.transactions) == 1 and b.ram.transactions[0]["cmd"] == 0x02
    assert b.ram.get_word_be(0x30) == 0x13579BDF
    b.check_bus()


@cocotb.test()
async def test_busy_flags_exclusive(dut):
    """flash_rbusy / ram_rbusy / ram_wbusy nunca están activos a la vez y reflejan el tipo de transacción."""
    b = await make_bench(dut)
    seen = set()

    async def watch():
        while True:
            await RisingEdge(dut.clk)
            v = (geti(dut.flash_rbusy), geti(dut.ram_rbusy), geti(dut.ram_wbusy))
            if None not in v:
                assert sum(v) <= 1, f"busy simultáneos {v}"
                seen.add(v)

    cocotb.start_soon(watch())
    b.put_flash_word(1, 1)
    await b.flash_read(1)
    await b.ram_write(0, 5)
    await b.ram_read(0)
    await b.idle(10)
    assert {(1, 0, 0), (0, 1, 0), (0, 0, 1)} <= seen, f"vistos {seen}"
    b.check_bus()


@cocotb.test()
async def test_back_to_back_requests(dut):
    """Pedidos consecutivos (apenas baja busy) se atienden bien, también alternando flash y RAM."""
    b = await make_bench(dut)
    for i in range(4):
        b.put_flash_word(i, 0xC0DE0000 + i)
    for i in range(4):
        r = await b.flash_read(i)
        assert r["rdata"] == 0xC0DE0000 + i, f"lectura {i}: 0x{r['rdata']:08x}"
    await b.ram_write(0x8, 0x01020304)
    r = await b.ram_read(0x8)
    assert r["rdata"] == 0x01020304
    r = await b.flash_read(0)
    assert r["rdata"] == 0xC0DE0000
    b.check_bus()


@cocotb.test()
async def test_miso_output_delay_tolerance(dut):
    """Esclavos con retardo de salida tras el flanco de SCK (tV): el dato se sigue leyendo bien en ambos."""
    b = await make_bench(dut, miso_delay_ns=2.0)
    b.put_flash_word(7, 0x0BADCAFE)
    b.ram.set_word_be(0x50, 0x600DF00D)
    r = await b.flash_read(7)
    assert r["rdata"] == 0x0BADCAFE, f"flash 0x{r['rdata']:08x}"
    r = await b.ram_read(0x50)
    assert r["rdata"] == 0x600DF00D, f"RAM 0x{r['rdata']:08x}"
    b.check_bus()


@cocotb.test()
async def test_reset_during_flash_transaction(dut):
    """Reset a mitad de una lectura de flash: CS_N sube, busy baja, SCK=0 y la siguiente transacción (flash o RAM) funciona."""
    b = await make_bench(dut)
    b.put_flash_word(2, 0xABCD1234)
    await RisingEdge(dut.clk)
    dut.flash_word_address.value = 2
    dut.flash_rstrb.value = 1
    await RisingEdge(dut.clk)
    dut.flash_rstrb.value = 0
    await ClockCycles(dut.clk, 40)
    assert geti(dut.spi_cs_flash_n) == 0 and geti(dut.flash_rbusy) == 1, "la lectura debería estar en curso"
    await FallingEdge(dut.clk)
    dut.reset.value = 0
    await ClockCycles(dut.clk, 4)
    assert geti(dut.spi_cs_flash_n) == 1 and geti(dut.spi_cs_ram_n) == 1
    assert geti(dut.flash_rbusy) == 0 and geti(dut.spi_sck) == 0
    await FallingEdge(dut.clk)
    dut.reset.value = 1
    await ClockCycles(dut.clk, 4)
    r = await b.flash_read(2)
    assert r["rdata"] == 0xABCD1234, f"tras el reset: 0x{r['rdata']:08x}"
    await b.ram_write(0x20, 0xFEEDC0DE)
    assert b.ram.get_word_be(0x20) == 0xFEEDC0DE


@cocotb.test()
async def test_reset_during_ram_transaction(dut):
    """Reset a mitad de una lectura de RAM: el bus queda libre y la siguiente transacción funciona."""
    b = await make_bench(dut)
    b.ram.set_word_be(0x70, 0x0A0B0C0D)
    await RisingEdge(dut.clk)
    dut.ram_word_address.value = 0x70
    dut.ram_rd.value = 1
    await RisingEdge(dut.clk)
    dut.ram_rd.value = 0
    await ClockCycles(dut.clk, 60)
    assert geti(dut.spi_cs_ram_n) == 0 and geti(dut.ram_rbusy) == 1, "la lectura debería estar en curso"
    await FallingEdge(dut.clk)
    dut.reset.value = 0
    await ClockCycles(dut.clk, 4)
    assert geti(dut.spi_cs_flash_n) == 1 and geti(dut.spi_cs_ram_n) == 1
    assert geti(dut.ram_rbusy) == 0 and geti(dut.ram_wbusy) == 0 and geti(dut.spi_sck) == 0
    await FallingEdge(dut.clk)
    dut.reset.value = 1
    await ClockCycles(dut.clk, 4)
    r = await b.ram_read(0x70)
    assert r["rdata"] == 0x0A0B0C0D, f"tras el reset: 0x{r['rdata']:08x}"
