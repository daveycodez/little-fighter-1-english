#!/usr/bin/env python3
"""
Build script: generates MODS.COM (DOS patcher) and patches PLAY.COM.
Developer tool only — end users never run this.
"""

import os, struct, sys

GAME_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Minimal two-pass 16-bit x86 assembler for DOS .COM files
# ---------------------------------------------------------------------------

class Asm16:
    """Assembles 16-bit x86 machine code with label resolution."""

    REGS16 = {'ax':0,'cx':1,'dx':2,'bx':3,'sp':4,'bp':5,'si':6,'di':7}
    REGS8  = {'al':0,'cl':1,'dl':2,'bl':3,'ah':4,'ch':5,'dh':6,'bh':7}

    def __init__(self):
        self.buf = bytearray()
        self.base = 0x100
        self.labels = {}
        self.fixups = []

    @property
    def pos(self):
        return self.base + len(self.buf)

    def label(self, name):
        self.labels[name] = self.pos

    def _emit(self, *bs):
        for b in bs:
            self.buf.append(b & 0xFF)

    def _word(self, v):
        self._emit(v & 0xFF, (v >> 8) & 0xFF)

    def _fixup(self, kind, label):
        self.fixups.append((len(self.buf), label, kind))

    # -- data --
    def db(self, *args):
        for a in args:
            if isinstance(a, (bytes, bytearray)):
                self.buf.extend(a)
            elif isinstance(a, str):
                self.buf.extend(a.encode('ascii'))
            else:
                self._emit(a)

    def dw(self, v):
        self._word(v)

    # -- basic --
    def int21(self):          self._emit(0xCD, 0x21)
    def ret(self):            self._emit(0xC3)
    def cld(self):            self._emit(0xFC)

    def push(self, r):        self._emit(0x50 + self.REGS16[r])
    def pop(self, r):         self._emit(0x58 + self.REGS16[r])
    def inc16(self, r):       self._emit(0x40 + self.REGS16[r])
    def dec16(self, r):       self._emit(0x48 + self.REGS16[r])

    # -- mov reg, imm --
    def mov_r16_imm(self, r, v):  self._emit(0xB8 + self.REGS16[r]); self._word(v)
    def mov_r8_imm(self, r, v):   self._emit(0xB0 + self.REGS8[r], v & 0xFF)
    def mov_r16_label(self, r, l):
        self._emit(0xB8 + self.REGS16[r]); self._fixup('abs16', l); self._word(0)

    # -- mov reg, reg --
    def mov_rr16(self, dst, src):
        self._emit(0x89, 0xC0 | (self.REGS16[src] << 3) | self.REGS16[dst])
    def mov_rr8(self, dst, src):
        self._emit(0x8A, 0xC0 | (self.REGS8[dst] << 3) | self.REGS8[src])

    # -- mov AL/AX, [mem] and [mem], AL/AX --
    def mov_al_mem(self, l):   self._emit(0xA0); self._fixup('abs16', l); self._word(0)
    def mov_ax_mem(self, l):   self._emit(0xA1); self._fixup('abs16', l); self._word(0)
    def mov_mem_al(self, l):   self._emit(0xA2); self._fixup('abs16', l); self._word(0)
    def mov_mem_ax(self, l):   self._emit(0xA3); self._fixup('abs16', l); self._word(0)

    # -- mov BX, [mem16] --
    def mov_bx_mem(self, l):
        self._emit(0x8B, 0x1E); self._fixup('abs16', l); self._word(0)

    # -- indirect reg access --
    def mov_al_si_ind(self):   self._emit(0x8A, 0x04)   # MOV AL, [SI]
    def mov_al_di_ind(self):   self._emit(0x8A, 0x05)   # MOV AL, [DI]
    def cmp_al_di_ind(self):   self._emit(0x3A, 0x05)   # CMP AL, [DI]
    def cmp_byte_bx_imm(self, v): self._emit(0x80, 0x3F, v & 0xFF)  # CMP byte [BX], v
    def cmp_byte_di_ind_imm(self, v): self._emit(0x80, 0x3D, v & 0xFF)  # CMP byte [DI], v

    # -- ALU --
    def cmp_al_imm(self, v):   self._emit(0x3C, v & 0xFF)
    def sub_al_imm(self, v):   self._emit(0x2C, v & 0xFF)
    def sub_ax_dx(self):       self._emit(0x29, 0xD0)
    def cmp_ax_imm(self, v):   self._emit(0x3D); self._word(v)
    def xor_r8(self, r):
        c = self.REGS8[r]; self._emit(0x30, 0xC0 | (c << 3) | c)
    def xor_r16(self, r):
        c = self.REGS16[r]; self._emit(0x31, 0xC0 | (c << 3) | c)
    def add_rr16(self, dst, src):
        self._emit(0x01, 0xC0 | (self.REGS16[src] << 3) | self.REGS16[dst])
    def or_rr16(self, dst, src):
        self._emit(0x09, 0xC0 | (self.REGS16[src] << 3) | self.REGS16[dst])
    def cbw(self):             self._emit(0x98)
    def mul_bl(self):          self._emit(0xF6, 0xE3)   # AX = AL * BL
    def div_bx(self):          self._emit(0xF7, 0xF3)   # AX = DX:AX / BX

    # -- misc --
    def lodsb(self):           self._emit(0xAC)
    def lodsw(self):           self._emit(0xAD)

    def mov_mem16_imm(self, l, v):
        self._emit(0xC7, 0x06); self._fixup('abs16', l); self._word(0); self._word(v)

    # -- jumps --
    def _jcc8(self, op, l):    self._emit(op); self._fixup('rel8', l); self._emit(0)
    def jc(self, l):           self._jcc8(0x72, l)
    def jb(self, l):           self._jcc8(0x72, l)
    def je(self, l):           self._jcc8(0x74, l)
    def jne(self, l):          self._jcc8(0x75, l)
    def jnz(self, l):          self._jcc8(0x75, l)
    def ja(self, l):           self._jcc8(0x77, l)
    def jl(self, l):           self._jcc8(0x7C, l)
    def jmp(self, l):          self._jcc8(0xEB, l)
    def jcxz(self, l):         self._jcc8(0xE3, l)
    def loop(self, l):         self._jcc8(0xE2, l)
    def jmp_near(self, l):
        self._emit(0xE9); self._fixup('rel16', l); self._word(0)
    def jc_far(self, l):
        """JC with rel16 range: JNC over a JMP near."""
        self._emit(0x73, 0x03)  # JNC +3 (skip the JMP)
        self.jmp_near(l)
    def call(self, l):
        self._emit(0xE8); self._fixup('rel16', l); self._word(0)

    # -- resolve fixups --
    def resolve(self):
        for off, label, kind in self.fixups:
            t = self.labels[label]
            if kind == 'abs16':
                self.buf[off] = t & 0xFF
                self.buf[off + 1] = (t >> 8) & 0xFF
            elif kind == 'rel8':
                d = t - (self.base + off + 1)
                assert -128 <= d <= 127, f"rel8 overflow: {label} disp={d}"
                self.buf[off] = d & 0xFF
            elif kind == 'rel16':
                d = t - (self.base + off + 2)
                assert -32768 <= d <= 32767, f"rel16 overflow: {label} disp={d}"
                self.buf[off] = d & 0xFF
                self.buf[off + 1] = (d >> 8) & 0xFF

    def build(self):
        self.resolve()
        return bytes(self.buf)


# ---------------------------------------------------------------------------
# Build MODS.COM
# ---------------------------------------------------------------------------

def build_mods_com():
    a = Asm16()

    # === MAIN ===
    a.cld()

    # -- open & read MODS.CFG --
    a.mov_r8_imm('ah', 0x3D)
    a.mov_r8_imm('al', 0x00)
    a.mov_r16_label('dx', 'cfg_fname')
    a.int21()
    a.jc_far('exit')

    a.mov_rr16('bx', 'ax')
    a.mov_r8_imm('ah', 0x3F)
    a.mov_r16_imm('cx', 1024)
    a.mov_r16_label('dx', 'read_buffer')
    a.int21()
    a.jc('close_cfg')
    a.mov_mem_ax('bytes_read')

    a.label('close_cfg')
    a.mov_r8_imm('ah', 0x3E)
    a.int21()

    # -- search for each option --
    a.mov_r16_label('si', 'str_julian')
    a.call('search')
    a.mov_mem_al('flag_julian')

    a.mov_r16_label('si', 'str_free_run')
    a.call('search')
    a.mov_mem_al('flag_free_run')

    a.mov_r16_label('si', 'str_free_jump')
    a.call('search')
    a.mov_mem_al('flag_free_jump')

    a.mov_r16_label('si', 'str_free_supers')
    a.call('search')
    a.mov_mem_al('flag_free_supers')

    a.mov_r16_label('si', 'str_spawn_w0')
    a.call('search')
    a.mov_mem_al('flag_spawn_w0')

    a.mov_r16_label('si', 'str_spawn_w2')
    a.call('search')
    a.mov_mem_al('flag_spawn_w2')

    a.mov_r16_label('si', 'str_spawn_w3')
    a.call('search')
    a.mov_mem_al('flag_spawn_w3')

    a.mov_r16_label('si', 'str_all_weapons')
    a.call('search')
    a.mov_mem_al('flag_all_weapons')

    a.mov_r16_label('si', 'str_speed_hack')
    a.call('search')
    a.mov_mem_al('flag_speed_hack')

    a.mov_r16_label('si', 'str_fast_mp')
    a.call('search')
    a.mov_mem_al('flag_fast_mp')

    a.mov_r16_label('si', 'str_easy_supers')
    a.call('search')
    a.mov_mem_al('flag_easy_supers')

    # -- compute spawn rate value --
    a.mov_r16_imm('ax', 0x012C)        # default = 300
    a.mov_mem_ax('rate_value')
    a.mov_al_mem('flag_spawn_w2')
    a.cmp_al_imm(1)
    a.jne('no_sw2')
    a.mov_r16_imm('ax', 0x0096)        # 2x = 150
    a.mov_mem_ax('rate_value')
    a.label('no_sw2')
    a.mov_al_mem('flag_spawn_w3')
    a.cmp_al_imm(1)
    a.jne('no_sw3')
    a.mov_r16_imm('ax', 0x0064)        # 3x = 100
    a.mov_mem_ax('rate_value')
    a.label('no_sw3')

    # -- patch START.EXE --
    a.mov_r8_imm('ah', 0x3D)
    a.mov_r8_imm('al', 0x02)
    a.mov_r16_label('dx', 'fn_start')
    a.int21()
    a.jc('patch_fight')
    a.mov_mem_ax('cur_handle')

    # julian patch 1: file offset 0x6D70, 2 bytes
    a.mov_al_mem('flag_julian')
    a.mov_r16_imm('cx', 0x0000)
    a.mov_r16_imm('dx', 0x6D70)
    a.mov_r16_label('si', 'julian_on')
    a.mov_r16_label('di', 'julian_off')
    a.mov_r8_imm('bl', 2)
    a.call('apply_patch')

    # julian patch 2: file offset 0x75F1, 2 bytes
    a.mov_al_mem('flag_julian')
    a.mov_r16_imm('cx', 0x0000)
    a.mov_r16_imm('dx', 0x75F1)
    a.mov_r16_label('si', 'julian_on')
    a.mov_r16_label('di', 'julian_off')
    a.mov_r8_imm('bl', 2)
    a.call('apply_patch')

    a.mov_bx_mem('cur_handle')
    a.mov_r8_imm('ah', 0x3E)
    a.int21()

    # -- patch FIGHT.EXE --
    a.label('patch_fight')
    a.mov_r8_imm('ah', 0x3D)
    a.mov_r8_imm('al', 0x02)
    a.mov_r16_label('dx', 'fn_fight')
    a.int21()
    a.jc_far('exit')
    a.mov_mem_ax('cur_handle')

    # free_run patch 1: offset 0x1B190, 5 bytes (dash init -10 MP)
    a.mov_al_mem('flag_free_run')
    a.mov_r16_imm('cx', 0x0001)
    a.mov_r16_imm('dx', 0xB190)
    a.mov_r16_label('si', 'nops')
    a.mov_r16_label('di', 'sub_mp_orig')
    a.mov_r8_imm('bl', 5)
    a.call('apply_patch')

    # free_run patch 2: offset 0x1A1A2, 4 bytes (run drain P1)
    a.mov_al_mem('flag_free_run')
    a.mov_r16_imm('cx', 0x0001)
    a.mov_r16_imm('dx', 0xA1A2)
    a.mov_r16_label('si', 'nops')
    a.mov_r16_label('di', 'dec_mp_orig')
    a.mov_r8_imm('bl', 4)
    a.call('apply_patch')

    # free_run patch 3: offset 0x1A20A, 4 bytes (run drain P2)
    a.mov_al_mem('flag_free_run')
    a.mov_r16_imm('cx', 0x0001)
    a.mov_r16_imm('dx', 0xA20A)
    a.mov_r16_label('si', 'nops')
    a.mov_r16_label('di', 'dec_mp_orig')
    a.mov_r8_imm('bl', 4)
    a.call('apply_patch')

    # free_jump patch: offset 0x1B1D7, 5 bytes (jump -10 MP)
    a.mov_al_mem('flag_free_jump')
    a.mov_r16_imm('cx', 0x0001)
    a.mov_r16_imm('dx', 0xB1D7)
    a.mov_r16_label('si', 'nops')
    a.mov_r16_label('di', 'sub_mp_orig')
    a.mov_r8_imm('bl', 5)
    a.call('apply_patch')

    # free_supers: 6 dynamic-cost patches (SUB [BX+3420h], AX — 4 bytes)
    for cx_hi, dx_lo in [(0x0000, 0x8DF1), (0x0000, 0xC877),
                          (0x0000, 0xC95A), (0x0000, 0xCB9F),
                          (0x0001, 0x088B), (0x0001, 0x0A21)]:
        a.mov_al_mem('flag_free_supers')
        a.mov_r16_imm('cx', cx_hi)
        a.mov_r16_imm('dx', dx_lo)
        a.mov_r16_label('si', 'nops')
        a.mov_r16_label('di', 'sub_mp_ax_orig')
        a.mov_r8_imm('bl', 4)
        a.call('apply_patch')

    # free_supers: hardcoded 25 MP cost at 0x1187E (5 bytes)
    a.mov_al_mem('flag_free_supers')
    a.mov_r16_imm('cx', 0x0001)
    a.mov_r16_imm('dx', 0x187E)
    a.mov_r16_label('si', 'nops')
    a.mov_r16_label('di', 'sub_mp_25_orig')
    a.mov_r8_imm('bl', 5)
    a.call('apply_patch')

    # free_supers: hardcoded 50 MP cost at 0x156EC (5 bytes)
    a.mov_al_mem('flag_free_supers')
    a.mov_r16_imm('cx', 0x0001)
    a.mov_r16_imm('dx', 0x56EC)
    a.mov_r16_label('si', 'nops')
    a.mov_r16_label('di', 'sub_mp_50_orig')
    a.mov_r8_imm('bl', 5)
    a.call('apply_patch')

    # spawn_weapons=0: disable spawns — JNE→JMP at 0x1BDB9 (1 byte)
    a.mov_al_mem('flag_spawn_w0')
    a.mov_r16_imm('cx', 0x0001)
    a.mov_r16_imm('dx', 0xBDB9)
    a.mov_r16_label('si', 'jmp_byte')
    a.mov_r16_label('di', 'jne_byte')
    a.mov_r8_imm('bl', 1)
    a.call('apply_patch')

    # spawn rate: write precomputed rate_value at 0x1BDA7 (2 bytes)
    a.mov_r8_imm('al', 1)
    a.mov_r16_imm('cx', 0x0001)
    a.mov_r16_imm('dx', 0xBDA7)
    a.mov_r16_label('si', 'rate_value')
    a.mov_r16_label('di', 'rate_value')
    a.mov_r8_imm('bl', 2)
    a.call('apply_patch')

    # all_weapons=1: type count 10→12 at 0xBE6F
    a.mov_al_mem('flag_all_weapons')
    a.mov_r16_imm('cx', 0x0000)
    a.mov_r16_imm('dx', 0xBE6F)
    a.mov_r16_label('si', 'wtype_all')
    a.mov_r16_label('di', 'wtype_orig')
    a.mov_r8_imm('bl', 1)
    a.call('apply_patch')

    # fast_mp=1: double MP recovery (ADD 2 instead of INC at 0x1571E, 13 bytes)
    a.mov_al_mem('flag_fast_mp')
    a.mov_r16_imm('cx', 0x0001)
    a.mov_r16_imm('dx', 0x571E)
    a.mov_r16_label('si', 'fast_mp_on')
    a.mov_r16_label('di', 'fast_mp_off')
    a.mov_r8_imm('bl', 13)
    a.call('apply_patch')

    # speed_hack=1: skip retrace wait (EB→CB at 0x22435, RETF instead of JMP)
    a.mov_al_mem('flag_speed_hack')
    a.mov_r16_imm('cx', 0x0002)
    a.mov_r16_imm('dx', 0x2435)
    a.mov_r16_label('si', 'retf_byte')
    a.mov_r16_label('di', 'jmp_short_byte')
    a.mov_r8_imm('bl', 1)
    a.call('apply_patch')

    # easy_supers=1: replace combo handlers A,B,C,D,E,H with single-key check
    # Each handler gets its own patch with a handler-specific CALL NEAR displacement
    # to execute_super (0x7958), matching the original calling convention exactly.
    for label_suffix, cx_hi, dx_lo in [
        ('A', 0x0000, 0x9868),   # combo A handler at file offset 0x9868
        ('B', 0x0000, 0x9924),   # combo B handler at file offset 0x9924
        ('C', 0x0000, 0x99E0),   # combo C handler at file offset 0x99E0
        ('D', 0x0000, 0x9A9C),   # combo D handler at file offset 0x9A9C
        ('E', 0x0000, 0x9B38),   # combo E handler at file offset 0x9B38
    ]:
        a.mov_al_mem('flag_easy_supers')
        a.mov_r16_imm('cx', cx_hi)
        a.mov_r16_imm('dx', dx_lo)
        a.mov_r16_label('si', f'easy_super_{label_suffix}')
        a.mov_r16_label('di', f'combo_{label_suffix}_orig')
        a.mov_r8_imm('bl', 86)
        a.call('apply_patch')
    # Handler H: 139 bytes (proper weapon flag check + summon/attack dual-path)
    a.mov_al_mem('flag_easy_supers')
    a.mov_r16_imm('cx', 0x0000)
    a.mov_r16_imm('dx', 0x9C14)
    a.mov_r16_label('si', 'easy_super_H')
    a.mov_r16_label('di', 'combo_H_orig')
    a.mov_r8_imm('bl', 139)
    a.call('apply_patch')

    a.mov_bx_mem('cur_handle')
    a.mov_r8_imm('ah', 0x3E)
    a.int21()

    a.label('exit')
    a.mov_r16_imm('ax', 0x4C00)
    a.int21()

    # === search subroutine ===
    # SI = null-terminated search string
    # Returns AL = 1 if found in read_buffer, 0 if not
    a.label('search')
    a.push('si');  a.push('di');  a.push('bx');  a.push('cx');  a.push('dx')

    a.xor_r16('dx')
    a.mov_rr16('bx', 'si')
    a.label('s_len')
    a.cmp_byte_bx_imm(0)
    a.je('s_len_done')
    a.inc16('dx')
    a.inc16('bx')
    a.jmp('s_len')

    a.label('s_len_done')
    a.mov_ax_mem('bytes_read')
    a.sub_ax_dx()
    a.jl('s_nf')
    a.inc16('ax')
    a.mov_rr16('cx', 'ax')
    a.mov_r16_label('di', 'read_buffer')

    a.label('s_try')
    a.push('cx');  a.push('si');  a.push('di')
    a.mov_rr16('cx', 'dx')

    a.label('s_cmp')
    a.jcxz('s_match')
    a.mov_al_si_ind()
    a.cmp_al_di_ind()
    a.jne('s_miss')
    a.inc16('si');  a.inc16('di');  a.dec16('cx')
    a.jmp('s_cmp')

    a.label('s_match')
    a.pop('di');  a.pop('si');  a.pop('cx')
    a.jmp('s_found')

    a.label('s_miss')
    a.pop('di');  a.pop('si');  a.pop('cx')
    a.inc16('di')
    a.loop('s_try')

    a.label('s_nf')
    a.pop('dx');  a.pop('cx');  a.pop('bx');  a.pop('di');  a.pop('si')
    a.xor_r8('al')
    a.ret()

    a.label('s_found')
    a.pop('dx');  a.pop('cx');  a.pop('bx');  a.pop('di');  a.pop('si')
    a.mov_r8_imm('al', 1)
    a.ret()

    # === apply_patch subroutine ===
    # AL=flag  CX:DX=file offset  SI=on bytes  DI=off bytes  BL=size
    a.label('apply_patch')
    a.push('ax');  a.push('bx');  a.push('si');  a.push('di')
    a.push('ax');  a.push('bx')

    a.mov_bx_mem('cur_handle')
    a.mov_r16_imm('ax', 0x4200)
    a.int21()

    a.pop('bx');  a.pop('ax')
    a.cmp_al_imm(1)
    a.je('ap_on')
    a.mov_rr16('si', 'di')
    a.label('ap_on')
    a.mov_rr16('dx', 'si')
    a.xor_r8('ch')
    a.mov_rr8('cl', 'bl')
    a.mov_bx_mem('cur_handle')
    a.mov_r8_imm('ah', 0x40)
    a.int21()

    a.pop('di');  a.pop('si');  a.pop('bx');  a.pop('ax')
    a.ret()

    # === DATA ===
    a.label('cfg_fname');    a.db("MODS.CFG\x00")
    a.label('fn_start');     a.db("SYS\\START.EXE\x00")
    a.label('fn_fight');     a.db("SYS\\FIGHT.EXE\x00")
    a.label('str_julian');   a.db("julian=1\x00")
    a.label('str_free_run'); a.db("free_run=1\x00")
    a.label('str_free_jump');a.db("free_jump=1\x00")
    a.label('str_free_supers');a.db("free_supers=1\x00")
    a.label('str_spawn_w0'); a.db("spawn_weapons=0\x00")
    a.label('str_spawn_w2'); a.db("spawn_weapons=2\x00")
    a.label('str_spawn_w3'); a.db("spawn_weapons=3\x00")
    a.label('str_all_weapons');a.db("all_weapons=1\x00")
    a.label('str_speed_hack');a.db("speed_hack=1\x00")
    a.label('str_fast_mp'); a.db("fast_mp=1\x00")
    a.label('str_easy_supers');a.db("easy_supers=1\x00")
    a.label('julian_on');    a.db(0x90, 0x90)
    a.label('julian_off');   a.db(0x74, 0x06)
    a.label('nops');         a.db(0x90, 0x90, 0x90, 0x90, 0x90)
    a.label('sub_mp_orig');  a.db(0x83, 0xAF, 0x20, 0x34, 0x0A)
    a.label('dec_mp_orig');  a.db(0xFF, 0x8F, 0x20, 0x34)
    a.label('sub_mp_ax_orig');a.db(0x29, 0x87, 0x20, 0x34)
    a.label('sub_mp_25_orig');a.db(0x83, 0xAF, 0x20, 0x34, 0x19)
    a.label('sub_mp_50_orig');a.db(0x83, 0xAF, 0x20, 0x34, 0x32)
    a.label('jmp_byte');     a.db(0xEB)
    a.label('jne_byte');     a.db(0x75)
    a.label('wtype_all');    a.db(0x0C)
    a.label('wtype_orig');   a.db(0x0A)
    a.label('flag_julian');  a.db(0)
    a.label('flag_free_run');a.db(0)
    a.label('flag_free_jump'); a.db(0)
    a.label('flag_free_supers'); a.db(0)
    a.label('flag_spawn_w0');a.db(0)
    a.label('flag_spawn_w2');a.db(0)
    a.label('flag_spawn_w3');a.db(0)
    a.label('flag_all_weapons'); a.db(0)
    a.label('flag_speed_hack'); a.db(0)
    a.label('flag_fast_mp'); a.db(0)
    a.label('flag_easy_supers'); a.db(0)
    a.label('rate_value');   a.dw(0x012C)
    a.label('cur_handle');   a.dw(0)
    a.label('bytes_read');   a.dw(0)

    a.label('fast_mp_on');     a.db(0x8B, 0xC6, 0xB2, 0x34, 0xF7, 0xEA, 0x8B, 0xD8, 0x83, 0x87, 0x20, 0x34, 0x02)
    a.label('fast_mp_off');   a.db(0x8B, 0xC6, 0xBA, 0x34, 0x00, 0xF7, 0xEA, 0x8B, 0xD8, 0xFF, 0x87, 0x20, 0x34)
    a.label('retf_byte');     a.db(0xCB)    # RETF (skip retrace wait)
    a.label('jmp_short_byte');a.db(0xEB)   # original JMP SHORT at 0x22435

    # easy_supers: per-handler 86-byte patches
    # Key fix: uses entity.field_0x3404 (control slot: 0=P1, 1=P2, 2=P3) to
    # look up the correct easy-super scan code, rather than the entity index.
    # The game compacts entities (e.g. P1+P3 → entities 0,1) but each entity
    # keeps its original control slot. execute_super still receives the entity
    # index (SI) so it operates on the correct character.
    # Bytes 20-21 are an MZ relocation target → JMP SHORT skips them.
    #   P1: Q=0x10 E=0x12 Z=0x2C   P2: U=0x16 O=0x18 M=0x32
    #   P3: Num7=0x47 Num9=0x49 Num1=0x4F
    easy_super_prefix = [                    # bytes 0-65 (common)
         0x55,                               # 0:  push bp
         0x8B, 0xEC,                         # 1:  mov bp, sp
         0x56,                               # 3:  push si
         0x57,                               # 4:  push di
         0x8B, 0x76, 0x06,                   # 5:  mov si, [bp+6]  (entity index)
         0x8B, 0x7E, 0x08,                   # 8:  mov di, [bp+8]  (super index)
         0x83, 0xFE, 0x03,                   # 11: cmp si, 3
         0x7D, 0x39,                         # 14: jge done  (+57 → byte 73)
         0xEB, 0x04,                         # 16: jmp short past_reloc → byte 22
         0x00, 0x00,                         # 18: padding (never executed)
         0x00, 0x00,                         # 20: relocation target (loader writes here)
         # Look up entity's control slot from field 0x3404
         0x8B, 0xC6,                         # 22: mov ax, si
         0xBA, 0x34, 0x00,                   # 24: mov dx, 0x34
         0xF7, 0xEA,                         # 27: imul dx  (ax = si * 0x34)
         0x8B, 0xD8,                         # 29: mov bx, ax
         0x8A, 0x87, 0x04, 0x34,             # 31: mov al, [bx+0x3404]  (control slot)
         0xB3, 0x03,                         # 35: mov bl, 3
         0xF6, 0xE3,                         # 37: mul bl   (AX = slot*3)
         0x03, 0xC7,                         # 39: add ax, di
         0xE8, 0x00, 0x00,                   # 41: call $+3  (PIC: push IP)
         0x5B,                               # 44: pop bx
         0x83, 0xC3, 0x21,                   # 45: add bx, 33  (bx → table@77)
         0x2E, 0xD7,                         # 48: cs xlatb  (al = scancode)
         0x30, 0xE4,                         # 50: xor ah, ah
         0x8B, 0xD8,                         # 52: mov bx, ax
         0xD1, 0xE3,                         # 54: shl bx, 1
         0x83, 0xBF, 0x6E, 0x2E, 0x00,      # 56: cmp word [bx+2E6Eh], 0
         0x74, 0x0A,                         # 61: jz done  (+10 → byte 73)
         0x57,                               # 63: push di
         0x56,                               # 64: push si  (entity index for execute_super)
         0x0E,                               # 65: push cs
    ]
    easy_super_suffix = [                    # bytes 69-85 (common)
         0x90, 0x90,                         # 69: NOP NOP (padding after 3-byte call)
         0x59,                               # 71: pop cx
         0x59,                               # 72: pop cx
         0x5F,                               # 73: pop di   ← done:
         0x5E,                               # 74: pop si
         0x5D,                               # 75: pop bp
         0xCB,                               # 76: retf
         0x10, 0x12, 0x2C,                   # 77: table P1: Q  E  Z
         0x16, 0x18, 0x32,                   # 80: table P2: U  O  M
         0x47, 0x49, 0x4F,                   # 83: table P3: 7  9  1
    ]
    # CALL NEAR E8 displacement: target(0x7958) - (handler_code + 69)
    for suffix, file_off in [('A',0x9868),('B',0x9924),('C',0x99E0),
                              ('D',0x9A9C),('E',0x9B38)]:
        code_off = file_off - 0x1400
        disp = (0x7958 - (code_off + 69)) & 0xFFFF
        a.label(f'easy_super_{suffix}')
        a.db(*easy_super_prefix)
        a.db(0xE8, disp & 0xFF, (disp >> 8) & 0xFF)  # 66: call near execute_super
        a.db(*easy_super_suffix)

    # Handler H: 139-byte version for Deep's weapon summon (combo type H).
    # Uses animation state check (field_0x3414 / 50 == 5) to determine weapon
    # status, matching the game's own state-5 handler logic. State 5 means
    # "idle holding weapon" → weapon attack. Any other state → summon sword.
    # The old [bx+0x2F1A] weapon-data-table check stayed set after throwing,
    # preventing re-summon. The state check correctly resets when not holding.
    code_off_H = 0x9C14 - 0x1400
    disp_H = (0x7958 - (code_off_H + 108)) & 0xFFFF
    easy_super_H = [
         0x55,                               # 0:  push bp
         0x8B, 0xEC,                         # 1:  mov bp, sp
         0x56,                               # 3:  push si
         0x57,                               # 4:  push di
         0x8B, 0x76, 0x06,                   # 5:  mov si, [bp+6]  (entity index)
         0x8B, 0x7E, 0x08,                   # 8:  mov di, [bp+8]  (super index)
         0x83, 0xFE, 0x03,                   # 11: cmp si, 3
         0x7D, 0x60,                         # 14: jge done  (+96 → byte 112)
         0xEB, 0x04,                         # 16: jmp short past_reloc → byte 22
         0x00, 0x00,                         # 18: padding
         0x00, 0x00,                         # 20: relocation target
         0x8B, 0xC6,                         # 22: mov ax, si
         0xBA, 0x34, 0x00,                   # 24: mov dx, 0x34
         0xF7, 0xEA,                         # 27: imul dx
         0x8B, 0xD8,                         # 29: mov bx, ax
         0x8A, 0x87, 0x04, 0x34,             # 31: mov al, [bx+0x3404]  (control slot)
         0xB3, 0x03,                         # 35: mov bl, 3
         0xF6, 0xE3,                         # 37: mul bl
         0x03, 0xC7,                         # 39: add ax, di
         0xE8, 0x00, 0x00,                   # 41: call $+3  (PIC)
         0x5B,                               # 44: pop bx
         0x83, 0xC3, 0x56,                   # 45: add bx, 86  (bx → table@130)
         0x2E, 0xD7,                         # 48: cs xlatb
         0x30, 0xE4,                         # 50: xor ah, ah
         0x8B, 0xD8,                         # 52: mov bx, ax
         0xD1, 0xE3,                         # 54: shl bx, 1
         0x83, 0xBF, 0x6E, 0x2E, 0x00,      # 56: cmp word [bx+0x2E6Eh], 0
         0x74, 0x31,                         # 61: jz done  (+49 → byte 112)
         # Key pressed → compute entity offset
         0x8B, 0xC6,                         # 63: mov ax, si
         0xBA, 0x34, 0x00,                   # 65: mov dx, 0x34
         0xF7, 0xEA,                         # 68: imul dx
         0x8B, 0xD8,                         # 70: mov bx, ax
         # State check: [bx+0x3414] / 50 == 5 means holding weapon (idle)
         0x8B, 0x87, 0x14, 0x34,             # 72: mov ax, [bx+0x3414]
         0x53,                               # 76: push bx
         0xBB, 0x32, 0x00,                   # 77: mov bx, 0x32  (50)
         0x99,                               # 80: cwd
         0xF7, 0xFB,                         # 81: idiv bx
         0x5B,                               # 83: pop bx
         0x3D, 0x05, 0x00,                   # 84: cmp ax, 5
         0x74, 0x0D,                         # 87: jz has_weapon  (+13 → byte 102)
         # Not state 5 → SUMMON: deduct MP, set state 0x0E10 (creates sword)
         0x83, 0xAF, 0x20, 0x34, 0x32,      # 89: sub word [bx+0x3420], 50
         0xC7, 0x87, 0x14, 0x34, 0x10, 0x0E, # 94: mov word [bx+0x3414], 0x0E10
         0xEB, 0x0A,                         # 100: jmp short done  (+10 → byte 112)
         # has_weapon (state 5) → WEAPON ATTACK via execute_super
         0x57,                               # 102: push di
         0x56,                               # 103: push si
         0x0E,                               # 104: push cs
         0xE8, disp_H & 0xFF, (disp_H >> 8) & 0xFF,  # 105: call execute_super
         0x90, 0x90,                         # 108: nop nop
         0x59,                               # 110: pop cx
         0x59,                               # 111: pop cx
         # done:
         0x5F,                               # 112: pop di
         0x5E,                               # 113: pop si
         0x5D,                               # 114: pop bp
         0xCB,                               # 115: retf
         # NOP padding to keep table at byte 130
         0x90, 0x90, 0x90, 0x90, 0x90, 0x90, 0x90,  # 116-122
         0x90, 0x90, 0x90, 0x90, 0x90, 0x90, 0x90,  # 123-129
         0x10, 0x12, 0x2C,                   # 130: table P1: Q  E  Z
         0x16, 0x18, 0x32,                   # 133: table P2: U  O  M
         0x47, 0x49, 0x4F,                   # 136: table P3: 7  9  1
    ]
    a.label('easy_super_H')
    a.db(*easy_super_H)

    # Original first 86 bytes of each combo handler (for restoration)
    a.label('combo_A_orig')
    a.db(0x55, 0x8B, 0xEC, 0x56, 0x57, 0x8B, 0x76, 0x06, 0x8B, 0x7E,
         0x08, 0x39, 0x26, 0x7F, 0x0C, 0x77, 0x05, 0x9A, 0x2C, 0x34,
         0x00, 0x00, 0x8B, 0xC6, 0xBA, 0x34, 0x00, 0xF7, 0xEA, 0x8B,
         0xD8, 0x83, 0xBF, 0x02, 0x34, 0x01, 0x75, 0x4A, 0x8B, 0xC6,
         0xBA, 0x05, 0x00, 0xF7, 0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2F,
         0x4D, 0x73, 0x75, 0x38, 0x8B, 0xC6, 0xBA, 0x05, 0x00, 0xF7,
         0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2E, 0x4D, 0x64, 0x75,
         0x28, 0x8B, 0xC6, 0xBA, 0x05, 0x00,
         0xF7, 0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2D, 0x4D, 0x64, 0x75, 0x18)
    a.label('combo_B_orig')
    a.db(0x55, 0x8B, 0xEC, 0x56, 0x57, 0x8B, 0x76, 0x06, 0x8B, 0x7E,
         0x08, 0x39, 0x26, 0x7F, 0x0C, 0x77, 0x05, 0x9A, 0x2C, 0x34,
         0x00, 0x00, 0x8B, 0xC6, 0xBA, 0x34, 0x00, 0xF7, 0xEA, 0x8B,
         0xD8, 0x83, 0xBF, 0x02, 0x34, 0x01, 0x75, 0x4A, 0x8B, 0xC6,
         0xBA, 0x05, 0x00, 0xF7, 0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2F,
         0x4D, 0x73, 0x75, 0x38, 0x8B, 0xC6, 0xBA, 0x05, 0x00, 0xF7,
         0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2E, 0x4D, 0x77, 0x75,
         0x28, 0x8B, 0xC6, 0xBA, 0x05, 0x00,
         0xF7, 0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2D, 0x4D, 0x78, 0x75, 0x18)
    a.label('combo_C_orig')
    a.db(0x55, 0x8B, 0xEC, 0x56, 0x57, 0x8B, 0x76, 0x06, 0x8B, 0x7E,
         0x08, 0x39, 0x26, 0x7F, 0x0C, 0x77, 0x05, 0x9A, 0x2C, 0x34,
         0x00, 0x00, 0x8B, 0xC6, 0xBA, 0x34, 0x00, 0xF7, 0xEA, 0x8B,
         0xD8, 0x83, 0xBF, 0x02, 0x34, 0x01, 0x75, 0x4A, 0x8B, 0xC6,
         0xBA, 0x05, 0x00, 0xF7, 0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2F,
         0x4D, 0x73, 0x75, 0x38, 0x8B, 0xC6, 0xBA, 0x05, 0x00, 0xF7,
         0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2E, 0x4D, 0x64, 0x75,
         0x28, 0x8B, 0xC6, 0xBA, 0x05, 0x00,
         0xF7, 0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2D, 0x4D, 0x61, 0x75, 0x18)
    a.label('combo_D_orig')
    a.db(0x55, 0x8B, 0xEC, 0x56, 0x57, 0x8B, 0x76, 0x06, 0x8B, 0x7E,
         0x08, 0x39, 0x26, 0x7F, 0x0C, 0x77, 0x05, 0x9A, 0x2C, 0x34,
         0x00, 0x00, 0x8B, 0xC6, 0xBA, 0x34, 0x00, 0xF7, 0xEA, 0x8B,
         0xD8, 0x83, 0xBF, 0x02, 0x34, 0x01, 0x75, 0x3A, 0x8B, 0xC6,
         0xBA, 0x05, 0x00, 0xF7, 0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2F,
         0x4D, 0x73, 0x75, 0x28, 0x8B, 0xC6, 0xBA, 0x05, 0x00, 0xF7,
         0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2E, 0x4D, 0x64, 0x75,
         0x18, 0x8B, 0xC6, 0xBA, 0x05, 0x00,
         0xF7, 0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2D, 0x4D, 0x64, 0x75, 0x08)
    a.label('combo_E_orig')
    a.db(0x55, 0x8B, 0xEC, 0x56, 0x57, 0x8B, 0x76, 0x06, 0x8B, 0x7E,
         0x08, 0x39, 0x26, 0x7F, 0x0C, 0x77, 0x05, 0x9A, 0x2C, 0x34,
         0x00, 0x00, 0x8B, 0xC6, 0xBA, 0x34, 0x00, 0xF7, 0xEA, 0x8B,
         0xD8, 0x83, 0xBF, 0x02, 0x34, 0x01, 0x75, 0x5A, 0x8B, 0xC6,
         0xBA, 0x05, 0x00, 0xF7, 0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2F,
         0x4D, 0x73, 0x75, 0x48, 0x8B, 0xC6, 0xBA, 0x05, 0x00, 0xF7,
         0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2E, 0x4D, 0x64, 0x75,
         0x38, 0x8B, 0xC6, 0xBA, 0x05, 0x00,
         0xF7, 0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2D, 0x4D, 0x61, 0x75, 0x28)
    a.label('combo_H_orig')
    a.db(0x55, 0x8B, 0xEC, 0x56, 0x57, 0x8B, 0x76, 0x06, 0x8B, 0x7E,
         0x08, 0x39, 0x26, 0x7F, 0x0C, 0x77, 0x05, 0x9A, 0x2C, 0x34,
         0x00, 0x00, 0x8B, 0xC6, 0xBA, 0x34, 0x00, 0xF7, 0xEA, 0x8B,
         0xD8, 0x8B, 0x87, 0x14, 0x34, 0xBB, 0x32, 0x00, 0x99, 0xF7,
         0xFB, 0x3D, 0x05, 0x00, 0x74, 0x03, 0xE9, 0xEE, 0x00, 0x8B,
         0xC6, 0xBA, 0x34, 0x00, 0xF7, 0xEA, 0x8B, 0xD8, 0x83, 0xBF,
         0x02, 0x34, 0x01, 0x75, 0x70, 0x8B, 0xC6, 0xBA, 0x05,
         0x00, 0xF7, 0xEA, 0x8B, 0xD8, 0x80,
         0xBF, 0x2F, 0x4D, 0x73, 0x75, 0x5E, 0x8B, 0xC6, 0xBA, 0x05, 0x00,
         0xF7, 0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2E, 0x4D, 0x64, 0x75,
         0x4E, 0x8B, 0xC6, 0xBA, 0x05, 0x00, 0xF7, 0xEA, 0x8B, 0xD8,
         0x80, 0xBF, 0x2D, 0x4D,
         0x61, 0x75, 0x3E, 0x8B, 0xC6,
         0xBA, 0x05, 0x00, 0xF7, 0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2C,
         0x4D, 0x64, 0x75, 0x2E, 0x8B, 0xC6, 0xBA, 0x34, 0x00, 0xF7,
         0xEA, 0x8B, 0xD8, 0x8B)

    a.label('read_buffer')

    a.resolve()
    return bytes(a.buf)


# ---------------------------------------------------------------------------
# Patch PLAY.COM to run MODS before the game
# ---------------------------------------------------------------------------

def patch_play_com():
    path = os.path.join(GAME_DIR, "PLAY.COM")
    data = bytearray(open(path, "rb").read())

    if len(data) == 1152 and data[0x305] == 0x70 and data[0x306] == 0x05:
        print("  PLAY.COM already patched")
        return True

    if len(data) != 1131:
        print(f"  PLAY.COM unexpected size ({len(data)}), skipping")
        return False

    if data[0x305] != 0x91 or data[0x306] != 0x04:
        print(f"  PLAY.COM entry point unexpected ({data[0x305]:02x}{data[0x306]:02x}), skipping")
        return False

    patch = bytearray()
    patch += b"MODS\x00"
    patch += bytes([0x8D, 0xB6, 0x66, 0x01])   # LEA SI, [BP+0166h]
    patch += bytes([0x8D, 0xBE, 0x3D, 0x00])   # LEA DI, [BP+003Dh]
    patch += bytes([0xB8, 0x23, 0x02])          # MOV AX, 0223h
    patch += bytes([0xFF, 0xD0])                # CALL AX
    patch += bytes([0xE9, 0x11, 0xFF])          # JMP 0491h
    assert len(patch) == 21

    data.extend(patch)
    data[0x305] = 0x70
    data[0x306] = 0x05

    open(path, "wb").write(data)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Building MODS.COM...")
    mods_bin = build_mods_com()
    mods_path = os.path.join(GAME_DIR, "MODS.COM")
    open(mods_path, "wb").write(mods_bin)
    print(f"  Written {len(mods_bin)} bytes to MODS.COM")

    print("Patching PLAY.COM...")
    if patch_play_com():
        print("  Done")
    else:
        print("  FAILED — see above")
        sys.exit(1)

    print("\nAll done. Users just edit mods.cfg and launch the game.")
