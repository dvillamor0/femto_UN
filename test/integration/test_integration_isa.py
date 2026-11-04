# SPDX-License-Identifier: Apache-2.0
"""
INTEGRACIÓN POR INSTRUCCIÓN  (tt_um_femto completo, RTL f15fccd)

Una prueba por cada instrucción del Quark (RV32I + RDCYCLE):
  LUI AUIPC | JAL JALR | BEQ BNE BLT BGE BLTU BGEU | LB LH LW LBU LHU | SB SH SW |
  ADDI SLTI SLTIU XORI ORI ANDI SLLI SRLI SRAI | ADD SUB SLL SLT SLTU XOR SRL SRA OR AND |
  RDCYCLE (+ ECALL / EBREAK, que el Quark ejecuta como NOP)

"Integración" = la instrucción recorre TODO el camino real: se busca en la SPI Flash a través de
MappedSPIFlash, se ejecuta en el núcleo, y si accede a datos pasa por el decodificador hacia la flash
o hacia la SPI RAM. Cada prueba comprueba, contra el ISS de referencia (rvlib.ISS):
  1. la traza de direcciones de búsqueda de instrucciones que ve el bus (todas con cs = flash) es
     idéntica a la del ISS  -> saltos y branches correctos de extremo a extremo;
  2. los registros resultantes coinciden con el ISS;
  3. los accesos de datos (loads/stores) se enrutan al periférico correcto.
Los programas empiezan con un NOP (regla R1: la instrucción de la dirección 0 se pierde, DEF-R1).
"""
import cocotb
from cocotb.triggers import FallingEdge

from rvlib import *            # noqa: F401,F403
from soc import *              # noqa: F401,F403
from spimodels import geti

DATA = 0x2000                                       # constantes en la flash
DATA_BYTES = bytes([0x01, 0x82, 0xFF, 0x7F, 0x80, 0x00, 0xFE, 0xCA, 0x78, 0x56, 0x34, 0x92])
RAMB = 0x10000                                      # SPI RAM
CS_FLASH, CS_RAM, CS_UART = 0b0000001, 0b1000000, 0b0100000


class BusMonitor:
    """Registra cada acceso de la CPU: tipo, dirección, cs[6:0], estado de la CPU."""

    def __init__(self, dut):
        self.dut, self.events, self.cycle = dut, [], 0

    async def run(self):
        d = self.dut.femto0
        while True:
            await FallingEdge(self.dut.clk)
            self.cycle += 1
            rs, wm = geti(d.mem_rstrb, 0), geti(d.mem_wmask, 0)
            if rs or wm:
                self.events.append(dict(kind="W" if wm else "R", addr=geti(d.mem_address), cs=geti(d.cs),
                                        wmask=wm, cyc=self.cycle, state=geti(d.CPU.state)))


def reference(p, halt, extra):
    """Ejecuta el programa en el ISS (memoria plana little-endian) y devuelve el ISS."""
    mem = bytearray(MEM_SIZE)
    for a, w in p.words.items():
        mem[a:a + 4] = w.to_bytes(4, "little")
    for a, d in (extra or {}).items():
        mem[a:a + len(d)] = d
    iss = ISS(mem)
    iss.run(halt)
    return iss


async def run_case(dut, p, halt, regs=(), extra=None, mask=None, max_cycles=900_000):
    mon = BusMonitor(dut)
    cocotb.start_soon(mon.run())
    soc = await boot(dut, p, flash_extra=extra)
    await soc.run_to_halt(halt, max_cycles)
    iss = reference(p, halt, extra)
    # 1) búsqueda de instrucciones: siempre de la flash y con la misma traza que el ISS
    fetch = [e for e in mon.events if e["state"] == 1]
    off = [hex(e["addr"]) for e in fetch if e["cs"] != CS_FLASH]
    assert not off, f"búsqueda de instrucciones fuera de la flash: {off[:4]}"
    hw = []
    for e in fetch:
        hw.append(e["addr"])
        if e["addr"] == halt:
            break
    if hw != iss.trace:
        i = next((k for k, (a, b) in enumerate(zip(hw, iss.trace)) if a != b), min(len(hw), len(iss.trace)))
        raise AssertionError(f"traza de PC distinta en el paso {i}: bus={[hex(x) for x in hw[i:i+3]]} "
                             f"ISS={[hex(x) for x in iss.trace[i:i+3]]}")
    # 2) registros contra el ISS
    bad = []
    for r in regs:
        exp, got = iss.x[r], soc.reg(r)
        if mask is not None:
            exp, got = exp & mask, (got & mask if got is not None else None)
        if got != exp:
            bad.append(f"x{r}=0x{(got or 0):08x} esp 0x{exp:08x}")
    assert not bad, "; ".join(bad)
    return soc, mon, iss


def data_events(mon):
    """Accesos de datos (todo lo que no es FETCH), sin el load fantasma de la dirección 0 (DEF-R1)."""
    return [e for e in mon.events if e["state"] != 1 and not (e["kind"] == "R" and e["addr"] == 0)]


_registered = []


def isa_test(name, doc):
    def deco(fn):
        fn.__name__ = name
        fn.__qualname__ = name
        fn.__doc__ = doc
        globals()[name] = cocotb.test()(fn)
        _registered.append(name)
        return fn
    return deco


# ============================================================================ constantes y saltos
@isa_test("test_isa_lui", "LUI: carga inmediata superior (incl. 0 y bit 31).")
async def _lui(dut):
    p = new_prog(); p.emit(LUI(5, 0xABCDE), LUI(6, 0x80000), LUI(7, 0), LUI(8, 0xFFFFF)); h = halt_loop(p)
    await run_case(dut, p, h, regs=[5, 6, 7, 8])


@isa_test("test_isa_auipc", "AUIPC: PC + imm<<12 (truncado a 24 bits en el Quark).")
async def _auipc(dut):
    p = new_prog(); p.emit(AUIPC(5, 0x00001), AUIPC(6, 0x000FF), AUIPC(7, 0), AUIPC(8, 0x0A5A5)); h = halt_loop(p)
    await run_case(dut, p, h, regs=[5, 6, 7, 8])


@isa_test("test_isa_jal", "JAL: enlace PC+4, salto adelante; las instrucciones saltadas no se buscan en la flash; bucle hacia atrás.")
async def _jal(dut):
    p = new_prog()
    p.emit(JAL(5, 12), I("addi", 6, 0, 0x7AD), I("addi", 7, 0, 0x7AD), I("addi", 8, 0, 5))   # enlace + salto de 2 instrucciones
    p.emit(JAL(0, 12))                                                                        # rd = x0: no escribe, salta 2
    p.emit(I("addi", 9, 0, 0x7AD), I("addi", 10, 0, 0x7AD))
    p.emit(I("addi", 12, 0, 3))
    p.emit(I("addi", 12, 12, -1), B("bne", 12, 0, -4))                                        # bucle hacia atrás (3 vueltas)
    p.emit(JAL(13, 8), I("addi", 14, 0, 0x7AD), I("addi", 15, 0, 1))
    h = halt_loop(p)
    soc, mon, iss = await run_case(dut, p, h, regs=[5, 8, 12, 13, 15])
    for r in (6, 7, 9, 10, 14):
        assert soc.reg(r) != 0x7AD, f"x{r}: se ejecutó una instrucción saltada"


@isa_test("test_isa_jalr", "JALR: destino = (rs1+imm)&~1 (bit 0 forzado a 0), enlace PC+4, rd==rs1.")
async def _jalr(dut):
    p = new_prog()
    p.emit(AUIPC(7, 0), JALR(5, 7, 13), I("addi", 6, 0, 0x7AD), I("addi", 8, 0, 9))     # destino impar
    p.emit(AUIPC(9, 0), JALR(9, 9, 12), I("addi", 10, 0, 0x7AD), I("addi", 11, 0, 4))    # rd == rs1
    p.emit(AUIPC(12, 0), I("addi", 12, 12, 20), JALR(0, 12, -4), I("addi", 13, 0, 0x7AD), I("addi", 14, 0, 8))
    h = halt_loop(p)
    soc, mon, iss = await run_case(dut, p, h, regs=[5, 8, 9, 11, 14])
    for r in (6, 10, 13):
        assert soc.reg(r) != 0x7AD, f"x{r}: JALR no saltó la instrucción intermedia"


# ============================================================================ branches
BR_CASES = {"beq": ((5, 5), (5, 6)), "bne": ((5, 6), (7, 7)), "blt": ((0xFFFFFFFF, 1), (1, 0xFFFFFFFF)),
            "bge": ((1, 0xFFFFFFFF), (0xFFFFFFFF, 1)), "bltu": ((1, 0xFFFFFFFF), (0xFFFFFFFF, 1)),
            "bgeu": ((0xFFFFFFFF, 1), (1, 0xFFFFFFFF))}


def _mk_branch(op):
    @isa_test(f"test_isa_{op}", f"{op.upper()}: tomado, no tomado y salto hacia atrás (bucle de 3 vueltas); la traza en la flash lo refleja.")
    async def _t(dut):
        p = new_prog(); regs = []
        for k, (a, b) in enumerate(BR_CASES[op]):                  # hacia adelante: una vez tomado y otra no
            d = 10 + k
            p.emit(li(1, a), li(2, b), I("addi", d, 0, 1), B(op, 1, 2, 8), I("addi", d, 0, 0)); regs.append(d)
        p.emit(I("addi", 14, 0, 0))                                # hacia atrás: 3 iteraciones con la misma instrucción
        if op in ("bne", "blt", "bltu"):
            p.emit(li(3, 0), li(4, 3)); lp = p.pc
            p.emit(I("addi", 14, 14, 1), I("addi", 3, 3, 1)); p.emit(B(op, 3, 4, lp - p.pc))
        elif op in ("bge", "bgeu"):
            p.emit(li(3, 3), li(4, 1)); lp = p.pc
            p.emit(I("addi", 14, 14, 1), I("addi", 3, 3, -1)); p.emit(B(op, 3, 4, lp - p.pc))
        else:                                                      # beq: x6 == 1 mientras x3 < 3
            p.emit(li(3, 0), li(7, 1)); lp = p.pc
            p.emit(I("addi", 14, 14, 1), I("addi", 3, 3, 1), I("sltiu", 6, 3, 3)); p.emit(B(op, 6, 7, lp - p.pc))
        regs.append(14)
        h = halt_loop(p)
        soc, mon, iss = await run_case(dut, p, h, regs=regs)
        assert soc.reg(14) == 3, f"el bucle hacia atrás dio {soc.reg(14)} vueltas (esperado 3)"
    return _t


for _op in BR_CASES:
    _mk_branch(_op)


# ============================================================================ loads (desde flash)
def _mk_load(op, size, offs, base_off=0):
    @isa_test(f"test_isa_{op}", f"{op.upper()}: lee de la SPI Flash (datos constantes) con todos los desplazamientos y signo.")
    async def _t(dut):
        p = new_prog(); p.emit(li(1, DATA)); regs = []
        for k, off in enumerate(offs):
            p.emit(L(op, 10 + k, 1, off)); regs.append(10 + k)
        p.emit(li(2, DATA + 8), L(op, 20, 2, -size)); regs.append(20)      # offset negativo
        h = halt_loop(p)
        soc, mon, iss = await run_case(dut, p, h, regs=regs, extra={DATA: DATA_BYTES})
        acc = data_events(mon)
        assert acc and all(e["cs"] == CS_FLASH for e in acc), f"accesos de datos no enrutados a la flash: {[(hex(e['addr']), e['cs']) for e in acc]}"
        assert {e["addr"] & ~3 for e in acc} >= {DATA, DATA + 4}, "no se vieron los accesos esperados en el bus"
    return _t


_mk_load("lb", 1, [0, 1, 2, 3, 4, 7])
_mk_load("lbu", 1, [0, 1, 2, 3, 4, 7])
_mk_load("lh", 2, [0, 2, 4, 6, 8, 10])
_mk_load("lhu", 2, [0, 2, 4, 6, 8, 10])
_mk_load("lw", 4, [0, 4, 8])


# ============================================================================ stores (a la SPI RAM)
@isa_test("test_isa_sw", "SW: escribe una palabra en la SPI RAM (enrutada por cs[6]); la RAM externa la recibe y lw la devuelve.")
async def _sw(dut):
    p = new_prog(); p.emit(li(1, RAMB + 0x100), li(2, 0x12345678), S("sw", 2, 1, 0), li(3, 0x2AAAAAAA), S("sw", 3, 1, 4),
                           L("lw", 10, 1, 0), L("lw", 11, 1, 4), li(4, RAMB + 0x108), li(5, 0x00000001), S("sw", 5, 4, -4), L("lw", 12, 1, 4))
    h = halt_loop(p)
    soc, mon, iss = await run_case(dut, p, h, regs=[10, 11, 12], mask=0x7FFFFFFF, max_cycles=2_000_000)
    ws = [e for e in mon.events if e["kind"] == "W"]
    assert len(ws) >= 3 and all(e["cs"] == CS_RAM for e in ws), f"escrituras no enrutadas a la SPI RAM: {[(hex(e['addr']), e['cs']) for e in ws]}"
    assert soc.ram.get_word_be(0x100) == 0x12345678 and soc.ram.get_word_be(0x104) == 0x00000001, \
        f"contenido de la RAM externa: 0x{soc.ram.get_word_be(0x100):08x} 0x{soc.ram.get_word_be(0x104):08x}"


@isa_test("test_isa_sb", "SB: escribe sólo el byte indicado en la SPI RAM (carril de byte según mem_wmask).")
async def _sb(dut):
    p = new_prog(); p.emit(li(1, RAMB + 0x200), li(2, 0x11223344), S("sw", 2, 1, 0), li(3, 0xAA), S("sb", 3, 1, 1), L("lw", 10, 1, 0),
                           li(3, 0x55), S("sb", 3, 1, 3), L("lw", 11, 1, 0), li(3, 0x77), S("sb", 3, 1, 0), L("lw", 12, 1, 0))
    h = halt_loop(p)
    await run_case(dut, p, h, regs=[10, 11, 12], mask=0x7FFFFFFF, max_cycles=3_000_000)


@isa_test("test_isa_sh", "SH: escribe sólo el halfword indicado en la SPI RAM (carril según mem_wmask).")
async def _sh(dut):
    p = new_prog(); p.emit(li(1, RAMB + 0x300), li(2, 0x11223344), S("sw", 2, 1, 0), li(3, 0xBEEF), S("sh", 3, 1, 0), L("lw", 10, 1, 0),
                           li(3, 0x7ACE), S("sh", 3, 1, 2), L("lw", 11, 1, 0))
    h = halt_loop(p)
    await run_case(dut, p, h, regs=[10, 11], mask=0x7FFFFFFF, max_cycles=3_000_000)


# ============================================================================ ALU registro-registro
R_PAIRS = {
    "add": [(0x7FFFFFFF, 1), (0x80000000, 0xFFFFFFFF), (5, 7)],
    "sub": [(0, 1), (0x80000000, 1), (100, 58)],
    "sll": [(1, 31), (0xFFFFFFFF, (0xABC << 5) | 4), (0x80000001, 0)],
    "slt": [(0xFFFFFFFF, 1), (1, 0xFFFFFFFF), (5, 5)],
    "sltu": [(0xFFFFFFFF, 1), (1, 0xFFFFFFFF), (5, 5)],
    "xor": [(0xAAAAAAAA, 0x55555555), (0xFFFFFFFF, 0xFFFFFFFF), (0x12345678, 0)],
    "srl": [(0x80000000, 31), (0xF0F0F0F0, 4), (0xDEADBEEF, (0x1 << 5) | 3)],
    "sra": [(0x80000000, 31), (0xF0F0F0F0, 4), (0x7FFFFFFF, (0x7 << 5) | 3)],
    "or": [(0xAAAA0000, 0x00005555), (0, 0), (0x80000000, 1)],
    "and": [(0xFFFF0000, 0x0F0F0F0F), (0xFFFFFFFF, 0x80000001), (0x12345678, 0)],
}


def _mk_r(op):
    @isa_test(f"test_isa_{op}", f"{op.upper()}: operación registro-registro con operandos límite y rd == rs1.")
    async def _t(dut):
        p = new_prog(); regs = []
        for k, (a, b) in enumerate(R_PAIRS[op]):
            p.emit(li(1, a), li(2, b), R(op, 10 + k, 1, 2)); regs.append(10 + k)
        a, b = R_PAIRS[op][0]
        p.emit(li(1, a), li(2, b), R(op, 1, 1, 2)); regs.append(1)               # rd == rs1
        h = halt_loop(p)
        await run_case(dut, p, h, regs=regs)
    return _t


for _op in R_PAIRS:
    _mk_r(_op)

# ============================================================================ ALU inmediato
I_PAIRS = {
    "addi": [(0x7FFFFFFF, 1), (0, -1), (100, -2048)],
    "slti": [(0xFFFFFFFF, 0), (5, 6), (0x80000000, -1)],
    "sltiu": [(0xFFFFFFFF, -1), (1, 2), (0, -2048)],
    "xori": [(0xAAAAAAAA, 0x555), (0xFFFFFFFF, -1), (0x12345678, 0)],
    "ori": [(0x80000000, 0x7FF), (0, -2048), (0x0F0F0F0F, 0)],
    "andi": [(0xFFFFFFFF, 0x7FF), (0xFFFFFFFF, -1), (0x12345678, 0x0F0)],
}


def _mk_i(op):
    @isa_test(f"test_isa_{op}", f"{op.upper()}: operación con inmediato de 12 bits con signo extendido.")
    async def _t(dut):
        p = new_prog(); regs = []
        for k, (a, imm) in enumerate(I_PAIRS[op]):
            p.emit(li(1, a), I(op, 10 + k, 1, imm)); regs.append(10 + k)
        a, imm = I_PAIRS[op][0]
        p.emit(li(1, a), I(op, 1, 1, imm)); regs.append(1)
        h = halt_loop(p)
        await run_case(dut, p, h, regs=regs)
    return _t


for _op in I_PAIRS:
    _mk_i(_op)

# ============================================================================ desplazamientos con inmediato
SH_PAIRS = {"slli": [(0x80000001, 0), (0x80000001, 1), (0xDEADBEEF, 31), (1, 16)],
            "srli": [(0x80000001, 0), (0x80000001, 1), (0xDEADBEEF, 31), (0x80000000, 16)],
            "srai": [(0x80000001, 0), (0x80000001, 1), (0xDEADBEEF, 31), (0x80000000, 16)]}


def _mk_sh(op):
    @isa_test(f"test_isa_{op}", f"{op.upper()}: desplazamiento por inmediato (0..31); rellena con signo en SRAI.")
    async def _t(dut):
        p = new_prog(); regs = []
        for k, (a, s) in enumerate(SH_PAIRS[op]):
            p.emit(li(1, a), SH(op, 10 + k, 1, s)); regs.append(10 + k)
        h = halt_loop(p)
        await run_case(dut, p, h, regs=regs)
    return _t


for _op in SH_PAIRS:
    _mk_sh(_op)


# ============================================================================ sistema
@isa_test("test_isa_rdcycle", "RDCYCLE: contador de ciclos monótono; 10 instrucciones desde la flash cuestan ~198 ciclos cada una.")
async def _rdcycle(dut):
    p = new_prog(); p.emit(RDCYCLE(5))
    for _ in range(10):
        p.emit(I("addi", 7, 7, 1))
    p.emit(RDCYCLE(6), R("sub", 8, 6, 5), RDCYCLE(9), R("sub", 10, 9, 6)); h = halt_loop(p)
    soc = await boot(dut, p)
    await soc.run_to_halt(h, 300_000)
    d1, d2 = soc.reg(8), soc.reg(10)
    dut._log.info(f"RDCYCLE: Δ(11 instr)={d1}  Δ(2 instr)={d2}  -> {d1 / 11:.1f} ciclos/instrucción")
    assert d1 is not None and 180 * 11 <= d1 <= 215 * 11, f"Δcycles = {d1}"
    assert d2 is not None and 180 * 2 <= d2 <= 215 * 2, f"Δcycles = {d2}"
    assert soc.reg(6) != soc.reg(5) and soc.reg(9) != soc.reg(6)


@isa_test("test_isa_ecall", "ECALL: el Quark lo ejecuta como NOP (rd = x0); el flujo continúa sin alterar registros.")
async def _ecall(dut):
    p = new_prog(); p.emit(I("addi", 5, 0, 1), ECALL, I("addi", 5, 5, 1), ECALL, I("addi", 5, 5, 1)); h = halt_loop(p)
    await run_case(dut, p, h, regs=[5])


@isa_test("test_isa_ebreak", "EBREAK: el Quark lo ejecuta como NOP (rd = x0); el flujo continúa sin alterar registros.")
async def _ebreak(dut):
    p = new_prog(); p.emit(I("addi", 5, 0, 1), EBREAK, I("addi", 5, 5, 1), EBREAK, I("addi", 5, 5, 1)); h = halt_loop(p)
    await run_case(dut, p, h, regs=[5])
