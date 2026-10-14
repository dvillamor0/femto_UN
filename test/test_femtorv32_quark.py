# SPDX-License-Identifier: Apache-2.0
"""
Pruebas cocotb del núcleo FemtoRV32 "Quark" (src/femtorv32_quark.v).

Cubre el ISA completo RV32I + RDCYCLE:
  LUI AUIPC | JAL JALR | BEQ BNE BLT BGE BLTU BGEU | LB LH LW LBU LHU |
  SB SH SW | ADDI SLTI SLTIU XORI ORI ANDI SLLI SRLI SRAI |
  ADD SUB SLL SLT SLTU XOR SRL SRA OR AND | RDCYCLE (SYSTEM)

Estrategia
----------
* Un mini-ensamblador RV32I en Python (sin toolchain RISC-V).
* Un modelo de memoria (cocotb) con las señales del núcleo:
  mem_addr / mem_rdata / mem_rstrb / mem_rbusy / mem_wdata / mem_wmask / mem_wbusy,
  con estados de espera aleatorios opcionales (como cuando se ejecuta desde SPI).
* Pruebas dirigidas con valores esperados calculados por funciones Python
  independientes del RTL (casos límite: 0, -1, INT_MIN, INT_MAX, ...).
* Pruebas aleatorias diferenciales contra un simulador de referencia (ISS) en
  Python: se comparan los 32 registros, la memoria de datos y la traza de PCs.

Notas sobre el núcleo (ver cabecera del .v):
* `reset` es activo en BAJO.
* ADDR_WIDTH=24 por defecto: PC, AUIPC y direcciones load/store se truncan a 24 bits.
  El ISS lo modela (ADDR_MASK).
* Sólo se soportan accesos alineados (half en múltiplos de 2, word en múltiplos de 4).
* El banco de registros se escribe en el flanco de BAJADA del reloj.

Ejecutar:   make -f Makefile.cpu
"""

import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

# --------------------------------------------------------------------------
# Parámetros del entorno
# --------------------------------------------------------------------------
ADDR_WIDTH = 24
ADDR_MASK = (1 << ADDR_WIDTH) - 1
MEM_SIZE = 0x40000          # 256 KiB de memoria simulada
DATA_BASE = 0x20000         # zona de datos / resultados
RES_BASE = DATA_BASE        # buffer de resultados de las pruebas dirigidas
MASK32 = 0xFFFFFFFF
CPU_CLK_NS = 20


def u32(x):
    return x & MASK32


def s32(x):
    x &= MASK32
    return x - (1 << 32) if x & 0x80000000 else x


def sext(x, bits):
    x &= (1 << bits) - 1
    return x - (1 << bits) if x >> (bits - 1) else x


# --------------------------------------------------------------------------
# Mini-ensamblador RV32I
# --------------------------------------------------------------------------
OP_LOAD, OP_ALUI, OP_AUIPC, OP_STORE = 0x03, 0x13, 0x17, 0x23
OP_ALU, OP_LUI, OP_BRANCH, OP_JALR, OP_JAL, OP_SYSTEM = 0x33, 0x37, 0x63, 0x67, 0x6F, 0x73

R_OPS = {  # nombre: (funct7, funct3)
    "add": (0x00, 0), "sub": (0x20, 0), "sll": (0x00, 1), "slt": (0x00, 2),
    "sltu": (0x00, 3), "xor": (0x00, 4), "srl": (0x00, 5), "sra": (0x20, 5),
    "or": (0x00, 6), "and": (0x00, 7),
}
I_OPS = {"addi": 0, "slti": 2, "sltiu": 3, "xori": 4, "ori": 6, "andi": 7}
SH_OPS = {"slli": (0x00, 1), "srli": (0x00, 5), "srai": (0x20, 5)}
BR_OPS = {"beq": 0, "bne": 1, "blt": 4, "bge": 5, "bltu": 6, "bgeu": 7}
LD_OPS = {"lb": 0, "lh": 1, "lw": 2, "lbu": 4, "lhu": 5}
ST_OPS = {"sb": 0, "sh": 1, "sw": 2}


def _chk(v, lo, hi, what):
    assert lo <= v <= hi, f"{what}={v} fuera de rango [{lo},{hi}]"


def R(op, rd, rs1, rs2):
    f7, f3 = R_OPS[op]
    return (f7 << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | OP_ALU


def I(op, rd, rs1, imm):
    _chk(imm, -2048, 2047, "imm")
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (I_OPS[op] << 12) | (rd << 7) | OP_ALUI


def SH(op, rd, rs1, shamt):
    _chk(shamt, 0, 31, "shamt")
    f7, f3 = SH_OPS[op]
    return (f7 << 25) | (shamt << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | OP_ALUI


def L(op, rd, rs1, imm):
    _chk(imm, -2048, 2047, "imm")
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (LD_OPS[op] << 12) | (rd << 7) | OP_LOAD


def S(op, rs2, rs1, imm):
    _chk(imm, -2048, 2047, "imm")
    return (((imm >> 5) & 0x7F) << 25) | (rs2 << 20) | (rs1 << 15) | (ST_OPS[op] << 12) \
        | ((imm & 0x1F) << 7) | OP_STORE


def B(op, rs1, rs2, off):
    _chk(off, -4096, 4094, "branch off")
    assert off % 2 == 0
    o = off & 0x1FFF
    return (((o >> 12) & 1) << 31) | (((o >> 5) & 0x3F) << 25) | (rs2 << 20) | (rs1 << 15) \
        | (BR_OPS[op] << 12) | (((o >> 1) & 0xF) << 8) | (((o >> 11) & 1) << 7) | OP_BRANCH


def LUI(rd, imm20):
    return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | OP_LUI


def AUIPC(rd, imm20):
    return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | OP_AUIPC


def JAL(rd, off):
    _chk(off, -(1 << 20), (1 << 20) - 2, "jal off")
    assert off % 2 == 0
    o = off & 0x1FFFFF
    return (((o >> 20) & 1) << 31) | (((o >> 1) & 0x3FF) << 21) | (((o >> 11) & 1) << 20) \
        | (((o >> 12) & 0xFF) << 12) | (rd << 7) | OP_JAL


def JALR(rd, rs1, imm):
    _chk(imm, -2048, 2047, "imm")
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (0 << 12) | (rd << 7) | OP_JALR


def RDCYCLE(rd):          # csrrs rd, cycle, x0
    return (0xC00 << 20) | (0 << 15) | (2 << 12) | (rd << 7) | OP_SYSTEM


ECALL = 0x00000073
EBREAK = 0x00100073
NOP = I("addi", 0, 0, 0)


def li(rd, val):
    """Carga inmediata de 32 bits (LUI+ADDI según haga falta)."""
    val = u32(val)
    lo = sext(val & 0xFFF, 12)
    hi = ((val - lo) >> 12) & 0xFFFFF
    if hi == 0:
        return [I("addi", rd, 0, lo)]
    if lo == 0:
        return [LUI(rd, hi)]
    return [LUI(rd, hi), I("addi", rd, rd, lo)]


class Prog:
    """Constructor de programas: dict {dirección: palabra}."""

    def __init__(self, base=0):
        self.words = {}
        self.pc = base
        self.n_res = 0

    def org(self, addr):
        self.pc = addr

    def emit(self, *ws):
        for w in ws:
            if isinstance(w, (list, tuple)):
                self.emit(*w)
            else:
                self.words[self.pc] = u32(w)
                self.pc += 4

    def init_results(self):
        """x31 apunta al buffer de resultados."""
        self.emit(li(31, RES_BASE))
        self.n_res = 0

    def store_result(self, rs):
        """sw rs -> siguiente posición del buffer de resultados (contiguo)."""
        off = (self.n_res % 256) * 4
        self.emit(S("sw", rs, 31, off))
        self.n_res += 1
        if self.n_res % 256 == 0:
            self.emit(I("addi", 31, 31, 1024))

    def halt(self):
        addr = self.pc
        self.emit(JAL(0, 0))     # bucle infinito: fin de programa
        return addr


# --------------------------------------------------------------------------
# Modelo de referencia (funciones puras + ISS)
# --------------------------------------------------------------------------
def alu(op, a, b):
    a, b = u32(a), u32(b)
    op = {"addi": "add", "slti": "slt", "sltiu": "sltu", "xori": "xor", "ori": "or",
          "andi": "and", "slli": "sll", "srli": "srl", "srai": "sra"}.get(op, op)
    if op == "add":
        r = a + b
    elif op == "sub":
        r = a - b
    elif op == "sll":
        r = a << (b & 31)
    elif op == "slt":
        r = int(s32(a) < s32(b))
    elif op == "sltu":
        r = int(a < b)
    elif op == "xor":
        r = a ^ b
    elif op == "srl":
        r = a >> (b & 31)
    elif op == "sra":
        r = s32(a) >> (b & 31)
    elif op == "or":
        r = a | b
    elif op == "and":
        r = a & b
    else:
        raise ValueError(op)
    return u32(r)


def br_taken(op, a, b):
    a, b = u32(a), u32(b)
    return {"beq": a == b, "bne": a != b, "blt": s32(a) < s32(b), "bge": s32(a) >= s32(b),
            "bltu": a < b, "bgeu": a >= b}[op]


_R_BY_F = {v: k for k, v in R_OPS.items()}
_I_BY_F3 = {v: k for k, v in I_OPS.items()}
_BR_BY_F3 = {v: k for k, v in BR_OPS.items()}


class ISS:
    """Simulador RV32I de referencia (decodificación independiente del ensamblador)."""

    def __init__(self, mem, pc=0):
        self.x = [0] * 32
        self.pc = pc
        self.mem = mem
        self.trace = []

    def _rd_mem(self, a, n, signed):
        a &= ADDR_MASK
        v = int.from_bytes(self.mem[a:a + n], "little")
        return sext(v, 8 * n) if signed else v

    def _wr_mem(self, a, n, v):
        a &= ADDR_MASK
        self.mem[a:a + n] = (v & ((1 << (8 * n)) - 1)).to_bytes(n, "little")

    def step(self):
        pc = self.pc
        self.trace.append(pc)
        ins = int.from_bytes(self.mem[pc:pc + 4], "little")
        op = ins & 0x7F
        rd, f3, rs1, rs2, f7 = (ins >> 7) & 31, (ins >> 12) & 7, (ins >> 15) & 31, (ins >> 20) & 31, ins >> 25
        a, b = self.x[rs1], self.x[rs2]
        iimm = sext(ins >> 20, 12)
        simm = sext(((ins >> 25) << 5) | ((ins >> 7) & 0x1F), 12)
        bimm = sext((((ins >> 31) & 1) << 12) | (((ins >> 7) & 1) << 11)
                    | (((ins >> 25) & 0x3F) << 5) | (((ins >> 8) & 0xF) << 1), 13)
        jimm = sext((((ins >> 31) & 1) << 20) | (((ins >> 12) & 0xFF) << 12)
                    | (((ins >> 20) & 1) << 11) | (((ins >> 21) & 0x3FF) << 1), 21)
        uimm = ins & 0xFFFFF000
        nxt = (pc + 4) & ADDR_MASK
        wr = None
        if op == OP_LUI:
            wr = uimm
        elif op == OP_AUIPC:
            wr = (pc + uimm) & ADDR_MASK          # el núcleo trunca a ADDR_WIDTH
        elif op == OP_JAL:
            wr, nxt = nxt, (pc + jimm) & ADDR_MASK
        elif op == OP_JALR:
            wr, nxt = nxt, ((a + iimm) & ADDR_MASK) & ~1
        elif op == OP_BRANCH:
            if br_taken(_BR_BY_F3[f3], a, b):
                nxt = (pc + bimm) & ADDR_MASK
        elif op == OP_LOAD:
            addr = a + iimm
            wr = {0: lambda: self._rd_mem(addr, 1, True), 1: lambda: self._rd_mem(addr, 2, True),
                  2: lambda: self._rd_mem(addr, 4, False), 4: lambda: self._rd_mem(addr, 1, False),
                  5: lambda: self._rd_mem(addr, 2, False)}[f3]()
        elif op == OP_STORE:
            self._wr_mem(a + simm, {0: 1, 1: 2, 2: 4}[f3], b)
        elif op == OP_ALUI:
            if f3 in (1, 5):
                name = {(0, 1): "slli", (0, 5): "srli", (0x20, 5): "srai"}[(f7, f3)]
                wr = alu(name, a, rs2)
            else:
                wr = alu(_I_BY_F3[f3], a, iimm)
        elif op == OP_ALU:
            wr = alu(_R_BY_F[(f7, f3)], a, b)
        else:
            raise AssertionError(f"ISS: opcode no soportado {ins:08x} @ {pc:x}")
        if wr is not None and rd != 0:
            self.x[rd] = u32(wr)
        self.pc = nxt

    def run(self, halt_addr, max_steps=200000):
        for _ in range(max_steps):
            if self.pc == halt_addr:
                self.trace.append(self.pc)
                return
            self.step()
        raise AssertionError("ISS: no llegó al halt")


# --------------------------------------------------------------------------
# Banco de pruebas: reloj, reset, modelo de memoria
# --------------------------------------------------------------------------
def geti(sig, default=None):
    try:
        return int(sig.value)
    except ValueError:      # X / Z
        return default


class CoreTB:
    def __init__(self, dut, rbusy_max=0, wbusy_max=0, seed=1):
        self.dut = dut
        self.rbusy_max = rbusy_max
        self.wbusy_max = wbusy_max
        self.rng = random.Random(seed)
        self.mem = bytearray(MEM_SIZE)
        self.fetch_trace = []
        self.halt_addr = None
        self.halted = False
        self.errors = []

    # -- memoria ---------------------------------------------------------
    def load_prog(self, prog):
        for addr, w in prog.words.items():
            self.mem[addr:addr + 4] = w.to_bytes(4, "little")

    def rd32(self, addr):
        return int.from_bytes(self.mem[addr:addr + 4], "little")

    def wr32(self, addr, v):
        self.mem[addr:addr + 4] = u32(v).to_bytes(4, "little")

    # -- arranque ---------------------------------------------------------
    async def start(self):
        dut = self.dut
        cocotb.start_soon(Clock(dut.clk, CPU_CLK_NS, unit="ns").start())
        dut.reset.value = 0
        dut.mem_rdata.value = 0
        dut.mem_rbusy.value = 0
        dut.mem_wbusy.value = 0
        # 'cycles' y x4/x31 no se inicializan en el RTL (sólo con -DBENCH): los dejamos a 0
        for sig_name in ("cycles",):
            try:
                getattr(dut, sig_name).value = 0
            except Exception:
                pass
        for i in range(32):
            try:
                dut.registerFile[i].value = 0
            except Exception:
                break
        cocotb.start_soon(self._mem_model())

    async def do_reset(self, cycles=5):
        self.halted = False
        self.fetch_trace.clear()
        self.dut.reset.value = 0
        await ClockCycles(self.dut.clk, cycles)
        await FallingEdge(self.dut.clk)
        self.dut.reset.value = 1

    # -- modelo de memoria (muestrea en el flanco de bajada) ----------------
    async def _mem_model(self):
        dut = self.dut
        rcnt = wcnt = 0
        garbage = 0xDEADBEEF
        while True:
            await FallingEdge(dut.clk)
            if geti(dut.reset) != 1:
                rcnt = wcnt = 0
                dut.mem_rbusy.value = 0
                dut.mem_wbusy.value = 0
                continue
            addr = geti(dut.mem_addr)
            rstrb = geti(dut.mem_rstrb, 0)
            wmask = geti(dut.mem_wmask, 0)

            # ---- escritura (wmask dura exactamente 1 ciclo) ----
            if wmask:
                if addr is None:
                    self.errors.append("escritura con mem_addr indefinido")
                else:
                    base = addr & ~3 & ADDR_MASK
                    wdata = geti(dut.mem_wdata)
                    if wdata is None:
                        self.errors.append("mem_wdata indefinido durante escritura")
                        wdata = 0
                    for lane in range(4):
                        if wmask & (1 << lane):
                            self.mem[base + lane] = (wdata >> (8 * lane)) & 0xFF
                k = self.rng.randint(0, self.wbusy_max)
                wcnt = k + 1 if k else 0
            elif wcnt > 0:
                wcnt -= 1
            dut.mem_wbusy.value = 1 if wcnt > 0 else 0

            # ---- lectura ----
            if rstrb:
                k = self.rng.randint(0, self.rbusy_max)
                rcnt = k + 1 if k else 0
                if geti(dut.state) == 1 and addr is not None:      # FETCH_INSTR
                    self.fetch_trace.append(addr)
                    if addr == self.halt_addr:
                        self.halted = True
            elif rcnt > 0:
                rcnt -= 1
            dut.mem_rbusy.value = 1 if rcnt > 0 else 0
            if rcnt > 1:
                dut.mem_rdata.value = garbage          # dato no válido mientras hay espera
            elif addr is not None:
                dut.mem_rdata.value = self.rd32(addr & ~3 & ADDR_MASK) if (addr & ADDR_MASK) < MEM_SIZE else 0
            else:
                dut.mem_rdata.value = 0

    # -- ejecución ---------------------------------------------------------
    async def run(self, prog, halt_addr, max_cycles=400000, settle=10):
        self.load_prog(prog)
        self.halt_addr = halt_addr
        await self.do_reset()
        for _ in range(max_cycles):
            await RisingEdge(self.dut.clk)
            if self.halted:
                break
        else:
            raise AssertionError(f"timeout: no se llegó al halt (0x{halt_addr:x}); "
                                 f"últimos PCs: {[hex(x) for x in self.fetch_trace[-6:]]}")
        await ClockCycles(self.dut.clk, settle)
        assert not self.errors, self.errors

    def regs(self):
        out = []
        for i in range(32):
            v = geti(self.dut.registerFile[i])
            out.append(v)
        return out


async def make_tb(dut, **kw):
    tb = CoreTB(dut, **kw)
    await tb.start()
    return tb


def check_results(tb, prog, expected, label):
    bad = []
    for i, exp in enumerate(expected):
        got = tb.rd32(RES_BASE + 4 * i)
        if got != u32(exp):
            bad.append((i, got, u32(exp)))
    assert not bad, (f"{label}: {len(bad)}/{len(expected)} resultados incorrectos; primeros: "
                     + ", ".join(f"#{i}: got=0x{g:08x} exp=0x{e:08x}" for i, g, e in bad[:6]))


# Valores de operandos "difíciles"
CORNERS = [0, 1, 2, 0x7FFFFFFF, 0x80000000, 0x80000001, 0xFFFFFFFF, 0xFFFFFFFE,
           0x0000FFFF, 0xFFFF0000, 0x12345678, 0xDEADBEEF, 0x55555555, 0xAAAAAAAA]
IMM_CORNERS = [0, 1, -1, 2, -2, 2047, -2048, 0x7FF, 0x555, -0x556, 0x123, -0x321]


# ==========================================================================
# PRUEBAS DIRIGIDAS
# ==========================================================================
@cocotb.test()
async def test_reset_and_first_fetch(dut):
    """Tras reset el primer acceso debe ser una lectura de RESET_ADDR (0); sin escrituras."""
    tb = await make_tb(dut)
    p = Prog()
    p.emit(I("addi", 1, 0, 5))
    h = p.halt()
    tb.load_prog(p)
    tb.halt_addr = h
    await tb.do_reset()
    await ClockCycles(dut.clk, 40)
    assert tb.fetch_trace[0] == 0, f"primer fetch en 0x{tb.fetch_trace[0]:x}"
    assert tb.fetch_trace[:3] == [0, 4, 4] or tb.fetch_trace[:2] == [0, 4], tb.fetch_trace[:4]
    assert geti(dut.mem_wmask) == 0
    assert geti(dut.registerFile[1]) == 5


@cocotb.test()
async def test_lui_auipc(dut):
    tb = await make_tb(dut)
    p = Prog()
    p.init_results()
    exp = []
    for imm in (0, 1, 0x12345, 0x7FFFF, 0x80000, 0xFFFFF, 0xABCDE):
        p.emit(LUI(1, imm))
        p.store_result(1)
        exp.append(imm << 12)
    # AUIPC (valores dentro de ADDR_WIDTH=24 bits => 24 bits significativos)
    for imm in (0, 1, 0x00FFF, 0x0A5A5, 0x000FF):
        pc = p.pc
        p.emit(AUIPC(2, imm))
        p.store_result(2)
        exp.append((pc + (imm << 12)) & ADDR_MASK)
    # destino x0 se ignora
    p.emit(LUI(0, 0xFFFFF), AUIPC(0, 0x1234))
    p.emit(R("add", 3, 0, 0))
    p.store_result(3)
    exp.append(0)
    h = p.halt()
    await tb.run(p, h)
    check_results(tb, p, exp, "lui/auipc")


@cocotb.test()
async def test_auipc_addr_width_limitation(dut):
    """DOCUMENTA una limitación: AUIPC devuelve PC+imm truncado a ADDR_WIDTH (24) bits.
    En RV32I estricto el resultado completo tendría 32 bits. Sólo informa (no falla)."""
    tb = await make_tb(dut)
    p = Prog()
    p.init_results()
    pc = p.pc
    p.emit(AUIPC(1, 0x12345))
    p.store_result(1)
    h = p.halt()
    await tb.run(p, h)
    got = tb.rd32(RES_BASE)
    strict = u32(pc + (0x12345 << 12))
    if got != strict:
        dut._log.warning(f"AUIPC truncado a {ADDR_WIDTH} bits: got=0x{got:08x} RV32I-estricto=0x{strict:08x} "
                         "(esperado por diseño del Quark)")
    assert got == (strict & ADDR_MASK)


@cocotb.test()
async def test_alu_reg_all_ops(dut):
    """ADD SUB SLL SLT SLTU XOR SRL SRA OR AND con operandos límite (valores esperados Python)."""
    tb = await make_tb(dut)
    p = Prog()
    p.init_results()
    exp = []
    vals = CORNERS[:11]
    for op in R_OPS:
        for a in vals:
            for b in vals:
                p.emit(li(1, a), li(2, b), R(op, 3, 1, 2))
                p.store_result(3)
                exp.append(alu(op, a, b))
    h = p.halt()
    await tb.run(p, h, max_cycles=2_000_000)
    check_results(tb, p, exp, "alu reg-reg")
    # valores literales independientes del modelo Python
    lit = {("sub", 0, 1): 0xFFFFFFFF, ("slt", 0x80000000, 1): 1, ("sltu", 0x80000000, 1): 0,
           ("sra", 0x80000000, 31): 0xFFFFFFFF, ("srl", 0x80000000, 31): 1,
           ("add", 0x7FFFFFFF, 1): 0x80000000}
    for (op, a, b), v in lit.items():
        assert alu(op, a, b) == v


@cocotb.test()
async def test_alu_imm_all_ops(dut):
    """ADDI SLTI SLTIU XORI ORI ANDI con inmediatos límite (signo extendido)."""
    tb = await make_tb(dut)
    p = Prog()
    p.init_results()
    exp = []
    for op in I_OPS:
        for a in CORNERS:
            for imm in IMM_CORNERS:
                p.emit(li(1, a), I(op, 3, 1, imm))
                p.store_result(3)
                exp.append(alu(op, a, sext(imm, 12)))
    h = p.halt()
    await tb.run(p, h, max_cycles=2_000_000)
    check_results(tb, p, exp, "alu imm")


@cocotb.test()
async def test_shifts_all_amounts(dut):
    """SLL/SRL/SRA y SLLI/SRLI/SRAI con los 32 desplazamientos (el reg-reg usa sólo rs2[4:0])."""
    tb = await make_tb(dut)
    p = Prog()
    p.init_results()
    exp = []
    vals = [0x80000001, 0x7FFFFFFF, 0xDEADBEEF, 0x00000001]
    for a in vals:
        for s in range(32):
            for op in ("slli", "srli", "srai"):
                p.emit(li(1, a), SH(op, 3, 1, s))
                p.store_result(3)
                exp.append(alu(op, a, s))
            garbage = (0xABCD << 5) | s                # bits altos de rs2 deben ignorarse
            for op in ("sll", "srl", "sra"):
                p.emit(li(1, a), li(2, garbage), R(op, 3, 1, 2))
                p.store_result(3)
                exp.append(alu(op, a, garbage))
    h = p.halt()
    await tb.run(p, h, max_cycles=3_000_000)
    check_results(tb, p, exp, "shifts")


@cocotb.test()
async def test_shift_rd_equals_rs(dut):
    """Desplazamientos con rd==rs1 y rd==rs2 (el ALU usa un registro interno)."""
    tb = await make_tb(dut)
    p = Prog()
    p.init_results()
    p.emit(li(1, 0x80000000), SH("srai", 1, 1, 4))
    p.store_result(1)
    p.emit(li(2, 3), li(3, 0xF0), R("sll", 2, 3, 2))
    p.store_result(2)
    p.emit(li(4, 5), R("srl", 4, 4, 4))     # x4 >> 5 = 0
    p.store_result(4)
    h = p.halt()
    await tb.run(p, h)
    check_results(tb, p, [0xF8000000, 0xF0 << 3, 0], "shift rd==rs")


@cocotb.test()
async def test_branches_all(dut):
    """BEQ BNE BLT BGE BLTU BGEU: tomada/no tomada, saltos hacia adelante."""
    tb = await make_tb(dut)
    p = Prog()
    p.init_results()
    exp = []
    vals = CORNERS[:10]
    for op in BR_OPS:
        for a in vals:
            for b in vals:
                # x3=1; b<op> a,b,+8 -> salta sobre 'addi x3,x0,0'; resultado 1 si se tomó
                p.emit(li(1, a), li(2, b), I("addi", 3, 0, 1), B(op, 1, 2, 8), I("addi", 3, 0, 0))
                p.store_result(3)
                exp.append(int(br_taken(op, a, b)))
    h = p.halt()
    await tb.run(p, h, max_cycles=2_000_000)
    check_results(tb, p, exp, "branches")


@cocotb.test()
async def test_branch_backward_loops(dut):
    """Saltos hacia atrás (bucle suma 1..20 con BNE, y cuenta atrás con BGE/BLT)."""
    tb = await make_tb(dut)
    p = Prog()
    p.init_results()
    # sum = 0; i = 20; do { sum += i; i--; } while (i != 0)
    p.emit(I("addi", 1, 0, 0), I("addi", 2, 0, 20))
    p.emit(R("add", 1, 1, 2), I("addi", 2, 2, -1), B("bne", 2, 0, -8))
    p.store_result(1)
    # i=10; while (i >= 0) { i--; } -> -1 ; BGE hacia atrás
    p.emit(I("addi", 3, 0, 10))
    p.emit(I("addi", 3, 3, -1), B("bge", 3, 0, -4))
    p.store_result(3)
    # BLTU hacia atrás: i=0; do { i++ } while (i <u 7)
    p.emit(I("addi", 4, 0, 0), I("addi", 5, 0, 7))
    p.emit(I("addi", 4, 4, 1), B("bltu", 4, 5, -4))
    p.store_result(4)
    # offset largo hacia atrás/adelante (~2 KiB)
    p.emit(I("addi", 6, 0, 0), JAL(0, 4 * 400))          # salta 400 palabras de NOP
    skip_start = p.pc
    for _ in range(399):
        p.emit(I("addi", 6, 0, 0x7A))                    # no deben ejecutarse
    p.emit(I("addi", 6, 6, 1))
    p.store_result(6)
    h = p.halt()
    await tb.run(p, h)
    check_results(tb, p, [210, 0xFFFFFFFF, 7, 1], "loops")


@cocotb.test()
async def test_branch_far_offsets(dut):
    """Offsets extremos de B-type (+4092 adelante, -4096 atrás) y J-type largo."""
    tb = await make_tb(dut)
    p = Prog()
    p.init_results()
    p.emit(I("addi", 1, 0, 1))
    bpc = p.pc
    p.emit(B("beq", 1, 1, 4092))                          # máximo salto hacia adelante
    p.emit(I("addi", 3, 0, 0x7AD))                        # no debe ejecutarse
    p.org(bpc + 4092)
    p.emit(I("addi", 4, 0, 0x2A))
    p.store_result(4)
    X = 0x6000
    p.emit(JAL(0, X - p.pc))                              # JAL largo hacia adelante
    p.org(X)
    p.emit(B("beq", 0, 0, -4096))                         # máximo salto hacia atrás
    p.emit(I("addi", 3, 0, 0x7AD))                        # no debe ejecutarse (X+4)
    p.org(X - 4096)
    p.emit(I("addi", 7, 0, 0x33))
    p.store_result(7)
    p.store_result(3)                                     # x3 debe seguir en 0 si nada se saltó mal
    h = p.halt()
    await tb.run(p, h)
    check_results(tb, p, [0x2A, 0x33, 0], "far offsets")


@cocotb.test()
async def test_jal(dut):
    """JAL: enlace = PC+4, saltos adelante/atrás, llamada+retorno, rd=x0 no escribe."""
    tb = await make_tb(dut)
    p = Prog()
    p.init_results()
    p.emit(I("addi", 6, 0, 0))
    # A) adelante con enlace; las 2 instrucciones intermedias se saltan
    a_pc = p.pc
    p.emit(JAL(5, 12))
    p.emit(I("addi", 6, 0, 0x7AD), I("addi", 6, 0, 0x7AD))
    p.store_result(5)                                     # enlace = a_pc+4
    p.store_result(6)                                     # sigue en 0
    # B) llamada a subrutina y retorno con JALR
    c = p.pc
    p.emit(JAL(1, 8))                                     # -> func (c+8)
    p.emit(JAL(0, 12))                                    # tras el retorno: -> done (c+16)
    p.emit(I("addi", 7, 0, 0x55))                         # func
    p.emit(JALR(0, 1, 0))                                 # ret -> c+4
    p.store_result(7)                                     # done
    p.store_result(1)                                     # x1 = c+4
    # C) salto hacia atrás
    d = p.pc
    p.emit(JAL(0, 12))                                    # -> jumper (d+12)
    p.emit(I("addi", 8, 0, 0x66))                         # back  (d+4)
    p.emit(JAL(0, 8))                                     # -> after (d+16)
    p.emit(JAL(0, -8))                                    # jumper: -> back (d+4)
    p.store_result(8)                                     # after
    # D) rd = x0: x0 sigue valiendo 0
    p.emit(JAL(0, 4), R("add", 11, 0, 0))
    p.store_result(11)
    h = p.halt()
    await tb.run(p, h)
    check_results(tb, p, [a_pc + 4, 0, 0x55, c + 4, 0x66, 0], "jal")


@cocotb.test()
async def test_jalr(dut):
    """JALR: bit0 del destino se fuerza a 0, imm negativo/positivo, rd==rs1, rd=x0, enlace=PC+4."""
    tb = await make_tb(dut)
    p = Prog()
    p.init_results()
    T1, T2, T3 = 0x1000, 0x1100, 0x1200
    p.emit(I("addi", 7, 0, 0))
    # a) destino impar
    p.emit(li(5, T1 | 1))
    j = p.pc
    p.emit(JALR(6, 5, 0))
    link_a = j + 4
    p.emit(I("addi", 7, 0, 0x7AD))                        # no debe ejecutarse
    p.org(T1)
    p.store_result(6)
    p.store_result(7)
    # b) imm negativo y rd == rs1
    p.emit(li(9, T2 + 0x40))
    j = p.pc
    p.emit(JALR(9, 9, -0x40))
    link_b = j + 4
    p.emit(I("addi", 7, 0, 0x7AD))                        # no debe ejecutarse
    p.org(T2)
    p.store_result(9)
    # c) rd = x0, imm positivo grande
    p.emit(li(10, T3 - 0x7F0))
    p.emit(JALR(0, 10, 0x7F0))
    p.emit(I("addi", 7, 0, 0x7AD))                        # no debe ejecutarse
    p.org(T3)
    p.emit(R("add", 11, 0, 0))
    p.store_result(11)
    p.store_result(7)
    h = p.halt()
    await tb.run(p, h)
    check_results(tb, p, [link_a, 0, link_b, 0, 0], "jalr")


@cocotb.test()
async def test_load_store_all_widths(dut):
    """LB LBU LH LHU LW / SB SH SW en todos los desplazamientos, con extensión de signo."""
    tb = await make_tb(dut)
    base = DATA_BASE + 0x4000
    pattern = [0x80FF7F01, 0x01028384, 0xFFFF0000, 0x00007FFF]
    for i, w in enumerate(pattern):
        tb.wr32(base + 4 * i, w)
    mem0 = bytes(tb.mem[base:base + 16])
    p = Prog()
    p.init_results()
    p.emit(li(1, base))
    exp = []
    for op, size in (("lb", 1), ("lbu", 1), ("lh", 2), ("lhu", 2), ("lw", 4)):
        for off in range(0, 16, size):
            p.emit(L(op, 3, 1, off))
            p.store_result(3)
            raw = int.from_bytes(mem0[off:off + size], "little")
            exp.append(u32(sext(raw, 8 * size)) if op in ("lb", "lh") else raw)
    # offsets negativos
    p.emit(li(2, base + 16))
    for op, off, size in (("lw", -16, 4), ("lh", -14, 2), ("lbu", -13, 1), ("lb", -1, 1)):
        p.emit(L(op, 3, 2, off))
        p.store_result(3)
        a = 16 + off
        raw = int.from_bytes(mem0[a:a + size], "little")
        exp.append(u32(sext(raw, 8 * size)) if op in ("lb", "lh") else raw)
    # rd == rs1 (la dirección no debe verse afectada por escrituras intermedias)
    p.emit(li(4, base + 4))
    p.emit(L("lw", 4, 4, 0))
    p.store_result(4)
    exp.append(int.from_bytes(mem0[4:8], "little"))
    # carga a x0 no cambia x0
    p.emit(L("lw", 0, 1, 0), R("add", 5, 0, 0))
    p.store_result(5)
    exp.append(0)
    h = p.halt()
    await tb.run(p, h, max_cycles=1_000_000)
    check_results(tb, p, exp, "loads")


@cocotb.test()
async def test_store_widths_and_lanes(dut):
    """SB/SH/SW escriben sólo los bytes correctos (wmask + replicación de mem_wdata)."""
    tb = await make_tb(dut)
    base = DATA_BASE + 0x8000
    for i in range(8):
        tb.wr32(base + 4 * i, 0xAABBCCDD)
    ref = bytearray(tb.mem[base:base + 32])
    p = Prog()
    p.emit(li(1, base), li(2, 0x11223344))
    ops = [("sb", 0), ("sb", 5), ("sb", 10), ("sb", 15)]            # un SB en cada carril 0..3
    ops += [("sh", 8), ("sh", 14), ("sw", 16), ("sb", 23), ("sh", 26), ("sb", 28)]
    for op, off in ops:
        p.emit(S(op, 2, 1, off))
        n = {"sb": 1, "sh": 2, "sw": 4}[op]
        ref[off:off + n] = (0x11223344 & ((1 << (8 * n)) - 1)).to_bytes(n, "little")
    # offset negativo
    p.emit(li(3, base + 32), li(4, 0x99), S("sb", 4, 3, -1))
    h = p.halt()
    await tb.run(p, h)
    assert tb.mem[base:base + 32 - 1] == ref[:31], \
        f"memoria incorrecta tras stores:\n got={tb.mem[base:base+32].hex()}\n exp={bytes(ref).hex()}"
    assert tb.mem[base + 31] == 0x99


@cocotb.test()
async def test_x0_hardwired_zero(dut):
    """x0 siempre vale 0 sin importar qué instrucción intente escribirlo."""
    tb = await make_tb(dut)
    p = Prog()
    p.init_results()
    p.emit(I("addi", 0, 0, 5), I("ori", 0, 0, -1), R("add", 0, 0, 0), SH("slli", 0, 0, 3))
    p.emit(LUI(0, 0x12345), JAL(0, 4), L("lw", 0, 31, 0))
    p.emit(R("add", 1, 0, 0))
    p.store_result(1)
    p.emit(R("sub", 2, 0, 31))      # 0 - x31
    p.store_result(2)
    h = p.halt()
    await tb.run(p, h)
    check_results(tb, p, [0, u32(-RES_BASE)], "x0")
    assert geti(dut.registerFile[0]) == 0


@cocotb.test()
async def test_rdcycle_and_system(dut):
    """RDCYCLE devuelve el contador de ciclos (monótono). ECALL/EBREAK actúan como NOP (rd=x0)."""
    tb = await make_tb(dut)
    p = Prog()
    p.init_results()
    N = 5
    p.emit(RDCYCLE(1))
    p.emit([NOP] * N)
    p.emit(RDCYCLE(2))
    p.store_result(1)
    p.store_result(2)
    p.emit(RDCYCLE(3), ECALL, EBREAK, RDCYCLE(4))
    p.store_result(3)
    p.store_result(4)
    h = p.halt()
    await tb.run(p, h)
    c1, c2, c3, c4 = (tb.rd32(RES_BASE + 4 * i) for i in range(4))
    assert c2 > c1, f"cycles no crece: {c1} -> {c2}"
    # sin esperas, cada instrucción simple tarda 3 ciclos (FETCH, WAIT_INSTR, EXECUTE)
    assert c2 - c1 == 3 * (N + 1), f"Δcycles={c2 - c1}, esperado {3 * (N + 1)}"
    assert c4 - c3 == 3 * 3, f"ECALL/EBREAK deberían ser NOP de 3 ciclos: Δ={c4 - c3}"


@cocotb.test()
async def test_cycles_per_instruction(dut):
    """Regresión de latencias (sin esperas): ALU=3, load/store=4, shift de s bits = s+4."""
    tb = await make_tb(dut)
    p = Prog()
    p.init_results()
    p.emit(li(1, DATA_BASE + 0x100), li(2, 0x80000000), li(6, 0))
    probes = [("alu", I("addi", 3, 3, 1)), ("lw", L("lw", 4, 1, 0)), ("sw", S("sw", 2, 1, 0)),
              ("slli0", SH("slli", 5, 2, 0)), ("slli1", SH("slli", 5, 2, 1)), ("srai31", SH("srai", 5, 2, 31)),
              ("beq_nt", B("beq", 2, 0, 8)), ("beq_t", B("beq", 0, 0, 8)), ("jal", JAL(0, 4))]
    exp = {}
    for name, ins in probes:
        p.emit(RDCYCLE(7), ins)
        if name == "beq_t":
            p.emit(NOP)
        p.emit(RDCYCLE(8), R("sub", 9, 8, 7))
        p.store_result(9)
    h = p.halt()
    await tb.run(p, h)
    got = {n: tb.rd32(RES_BASE + 4 * i) for i, (n, _) in enumerate(probes)}
    # Δ incluye la propia instrucción RDCYCLE (3 ciclos) + la sonda
    dut._log.info("Δ ciclos (incluye RDCYCLE=3): " + ", ".join(f"{k}={v}" for k, v in got.items()))
    assert got["alu"] == 3 + 3
    assert got["lw"] == 3 + 4 and got["sw"] == 3 + 4
    assert got["slli0"] == 3 + 4 and got["slli1"] == 3 + 5 and got["srai31"] == 3 + 35
    assert got["beq_nt"] == 3 + 3 and got["beq_t"] == 3 + 3 and got["jal"] == 3 + 3


@cocotb.test()
async def test_program_fibonacci(dut):
    """Programa 'real': Fibonacci iterativo + suma de arreglo en memoria con bucles/loads/stores."""
    tb = await make_tb(dut)
    arr = DATA_BASE + 0x100
    for i in range(16):
        tb.wr32(arr + 4 * i, (i + 1) * 0x101)
    p = Prog()
    p.init_results()
    # fib(20) = 6765
    p.emit(I("addi", 1, 0, 0), I("addi", 2, 0, 1), I("addi", 3, 0, 20))
    loop = p.pc
    p.emit(R("add", 4, 1, 2), R("add", 1, 0, 2), R("add", 2, 0, 4), I("addi", 3, 3, -1),
           B("bne", 3, 0, loop - (p.pc + 16)))
    p.store_result(1)
    # suma arreglo
    p.emit(li(5, arr), I("addi", 6, 0, 16), I("addi", 7, 0, 0))
    loop2 = p.pc
    p.emit(L("lw", 8, 5, 0), R("add", 7, 7, 8), I("addi", 5, 5, 4), I("addi", 6, 6, -1),
           B("bne", 6, 0, loop2 - (p.pc + 16)))
    p.store_result(7)
    # copia con SB byte a byte (memcpy de 8 bytes) y verificación
    p.emit(li(5, arr), li(9, arr + 0x100), I("addi", 6, 0, 8))
    loop3 = p.pc
    p.emit(L("lbu", 8, 5, 0), S("sb", 8, 9, 0), I("addi", 5, 5, 1), I("addi", 9, 9, 1), I("addi", 6, 6, -1),
           B("bne", 6, 0, loop3 - (p.pc + 20)))
    p.emit(li(9, arr + 0x100), L("lw", 10, 9, 0), L("lw", 11, 9, 4))
    p.store_result(10)
    p.store_result(11)
    h = p.halt()
    await tb.run(p, h)
    src = tb.mem[arr:arr + 8]
    check_results(tb, p, [6765, sum((i + 1) * 0x101 for i in range(16)),
                          int.from_bytes(src[0:4], "little"), int.from_bytes(src[4:8], "little")], "programa")


# ==========================================================================
# ALEATORIO DIFERENCIAL CONTRA EL ISS
# ==========================================================================
def rand_val(rng):
    return rng.choice(CORNERS) if rng.random() < 0.5 else rng.getrandbits(32)


def rand_imm(rng):
    return rng.choice(IMM_CORNERS) if rng.random() < 0.4 else rng.randint(-2048, 2047)


def gen_random_program(rng, n_items):
    """Programa aleatorio con avance garantizado (sólo saltos hacia adelante).
    x30 = temporal para JALR, x31 = puntero base de datos (nunca se sobrescriben)."""
    base_ptr = DATA_BASE + 0x200
    items = []

    def reg_any():
        return rng.randint(0, 31)

    def reg_dst():
        return rng.choice([0] + list(range(1, 30)) * 3)

    for _ in range(n_items):
        k = rng.random()
        if k < 0.22:
            items.append(("w", [R(rng.choice(list(R_OPS)), reg_dst(), reg_any(), reg_any())]))
        elif k < 0.36:
            items.append(("w", [I(rng.choice(list(I_OPS)), reg_dst(), reg_any(), rand_imm(rng))]))
        elif k < 0.46:
            items.append(("w", [SH(rng.choice(list(SH_OPS)), reg_dst(), reg_any(), rng.randint(0, 31))]))
        elif k < 0.52:
            items.append(("w", [LUI(reg_dst(), rng.getrandbits(20))]))
        elif k < 0.56:
            items.append(("w", [AUIPC(reg_dst(), rng.getrandbits(20))]))
        elif k < 0.68:
            op = rng.choice(list(LD_OPS))
            sz = {"lb": 1, "lbu": 1, "lh": 2, "lhu": 2, "lw": 4}[op]
            off = rng.randrange(-0x200, 0x200, sz)
            items.append(("w", [L(op, reg_dst(), 31, off)]))
        elif k < 0.80:
            op = rng.choice(list(ST_OPS))
            sz = {"sb": 1, "sh": 2, "sw": 4}[op]
            off = rng.randrange(-0x200, 0x200, sz)
            items.append(("w", [S(op, reg_any(), 31, off)]))
        elif k < 0.90:
            items.append(("br", rng.choice(list(BR_OPS)), reg_any(), reg_any(), rng.randint(1, 4)))
        elif k < 0.95:
            items.append(("jal", reg_dst(), rng.randint(0, 3)))
        else:
            items.append(("jalr", reg_dst(), rng.randint(0, 3), rng.randint(0, 1)))
    items.append(("halt",))

    def nwords(it):
        return 2 if it[0] == "jalr" else 1

    p = Prog()
    for r in range(1, 31):
        p.emit(li(r, rand_val(rng)))
    p.emit(li(31, base_ptr))
    start = p.pc
    addrs, a = [], start
    for it in items:
        addrs.append(a)
        a += 4 * nwords(it)
    halt_addr = addrs[-1]
    n = len(items)
    for idx, it in enumerate(items):
        assert p.pc == addrs[idx]
        if it[0] == "w":
            p.emit(it[1])
        elif it[0] == "br":
            _, op, r1, r2, skip = it
            tgt = addrs[min(idx + 1 + skip, n - 1)]
            p.emit(B(op, r1, r2, tgt - p.pc))
        elif it[0] == "jal":
            _, rd, skip = it
            tgt = addrs[min(idx + 1 + skip, n - 1)]
            p.emit(JAL(rd, tgt - p.pc))
        elif it[0] == "jalr":
            _, rd, skip, odd = it
            tgt = addrs[min(idx + 1 + skip, n - 1)]
            p.emit(AUIPC(30, 0))
            p.emit(JALR(rd, 30, (tgt - p.pc + 4) + odd))
        else:
            p.emit(JAL(0, 0))
    return p, halt_addr


async def random_vs_iss(dut, seed, n_items, rbusy, wbusy):
    rng = random.Random(seed)
    tb = await make_tb(dut, rbusy_max=rbusy, wbusy_max=wbusy, seed=seed + 1000)
    prog, halt = gen_random_program(rng, n_items)
    # datos iniciales aleatorios
    for off in range(0, 0x400, 4):
        tb.wr32(DATA_BASE + 0x200 - 0x200 + off, rng.getrandbits(32))
    iss_mem = bytearray(MEM_SIZE)
    for addr, w in prog.words.items():
        iss_mem[addr:addr + 4] = w.to_bytes(4, "little")
    iss_mem[DATA_BASE:DATA_BASE + 0x400] = tb.mem[DATA_BASE:DATA_BASE + 0x400]
    iss = ISS(iss_mem)
    iss.run(halt)

    await tb.run(prog, halt, max_cycles=300000)

    # 1) traza de PCs (comprueba todos los saltos/branches/jalr)
    hw_trace = []
    for a in tb.fetch_trace:
        hw_trace.append(a)
        if a == halt:
            break
    assert hw_trace == iss.trace, _first_diff(hw_trace, iss.trace, "traza de PC")
    # 2) registros
    hw = tb.regs()
    for i in range(32):
        assert hw[i] == iss.x[i], f"seed={seed}: x{i} hw={hw[i]} iss=0x{iss.x[i]:08x}"
    # 3) memoria de datos
    assert tb.mem[DATA_BASE:DATA_BASE + 0x400] == iss_mem[DATA_BASE:DATA_BASE + 0x400], \
        f"seed={seed}: memoria de datos distinta"


def _first_diff(a, b, what):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f"{what}: diverge en paso {i}: hw=0x{x:x} iss=0x{y:x}"
    return f"{what}: longitudes distintas hw={len(a)} iss={len(b)}"


@cocotb.test()
async def test_random_vs_iss_no_wait(dut):
    """Aleatorio diferencial, sin estados de espera."""
    n = int(os.environ.get("N_RANDOM", "12"))
    for s in range(n):
        await random_vs_iss(dut, seed=100 + s, n_items=250, rbusy=0, wbusy=0)


@cocotb.test()
async def test_random_vs_iss_with_wait_states(dut):
    """Aleatorio diferencial con mem_rbusy/mem_wbusy aleatorios (como la SPI-RAM/Flash)."""
    n = int(os.environ.get("N_RANDOM", "12"))
    for s in range(n):
        await random_vs_iss(dut, seed=500 + s, n_items=250, rbusy=4, wbusy=4)
