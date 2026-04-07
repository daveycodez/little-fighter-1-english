#!/usr/bin/env python3
"""
Build script: generates MODS.COM (MAIN + embedded FUSION + router), SYS/TRANSFORM.COM
(satellite TSR for contest only — COM size limit), optional SYS/FIGHTBGM.COM, and patches PLAY.COM.

When bgm=1 in mods.cfg, MODS.COM installs a TSR that plays baked-in MAIN
MIDI through MPU-401 UART mode.  PIT rate matches the build (game_speed×N
Hz for jitter-free music); a chain prescaler in the ISR throttles BIOS
tick updates to the configured game_speed.  F11 toggles mute/unmute
(All Notes Off on mute).  MODS also copies the BIOS INT 08 vector to
IVT[0x68] as a fallback; satellites primarily read old_08_* from the prior
INT 08 handler (tagged 0xB601/0xB602) because int 68h is not safe to rely on
(CONTEST and other code may repurpose it).  INT 21h hook:
EXEC of FIGHT switches the same INT 08 stream to embedded FUSION (no second
TSR per fight — avoids repeat FIGHTBGM.COM resident copies crashing load).
CONTEST still runs TRANSFORM.COM / SYS\\TRANSFORM.COM.  After
WAIT (AH=4Dh) from the same PSP that EXEC'd FIGHT/CONTEST restores MAIN and
INT 08 (FIGHT may call WAIT internally — those must not restore).  When
bgm=0, PIT is reprogrammed directly to game_speed with no TSR.

Developer tool only — end users never run this.
"""

import os, struct, sys
from collections import OrderedDict

GAME_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_HZ = 1193182.0 / 65536.0  # ~18.2065 Hz (default DOS timer rate)
COOK_HZ = 72.8                 # cook MIDI at 72.8 Hz (N=4 × 18.2 → perfect 4:1)


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

    def mov_mem8_imm(self, l, v):
        self._emit(0xC6, 0x06); self._fixup('abs16', l); self._word(0); self._emit(v & 0xFF)

    # -- jumps --
    def _jcc8(self, op, l):    self._emit(op); self._fixup('rel8', l); self._emit(0)
    def jc(self, l):           self._jcc8(0x72, l)
    def jb(self, l):           self._jcc8(0x72, l)
    def jnc(self, l):          self._jcc8(0x73, l)
    def je(self, l):           self._jcc8(0x74, l)
    def jne(self, l):          self._jcc8(0x75, l)
    def jnz(self, l):          self._jcc8(0x75, l)
    def ja(self, l):           self._jcc8(0x77, l)
    def jbe(self, l):          self._jcc8(0x76, l)
    def jl(self, l):           self._jcc8(0x7C, l)
    def jle(self, l):          self._jcc8(0x7E, l)
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
# MIDI Parser
# ---------------------------------------------------------------------------

def read_vlq(data, pos):
    val = 0
    while True:
        b = data[pos]; pos += 1
        val = (val << 7) | (b & 0x7F)
        if not (b & 0x80):
            return val, pos


def midi_data_len(status):
    top = status & 0xF0
    if top in (0xC0, 0xD0):
        return 1
    if 0x80 <= top <= 0xEF:
        return 2
    return 0


def parse_midi(path):
    raw = open(path, 'rb').read()
    assert raw[:4] == b'MThd', "Not a MIDI file"
    hlen = struct.unpack('>I', raw[4:8])[0]
    fmt, ntrk, div = struct.unpack('>HHH', raw[8:14])
    assert not (div & 0x8000), "SMPTE timing not supported"

    events = []
    off = 8 + hlen

    for _ in range(ntrk):
        assert raw[off:off+4] == b'MTrk'
        tlen = struct.unpack('>I', raw[off+4:off+8])[0]
        end = off + 8 + tlen
        p = off + 8
        t = 0
        rs = 0

        while p < end:
            dt, p = read_vlq(raw, p)
            t += dt
            b = raw[p]

            if b == 0xFF:
                p += 1
                mtype = raw[p]; p += 1
                mlen, p = read_vlq(raw, p)
                mdata = raw[p:p+mlen]; p += mlen
                if mtype == 0x51 and mlen == 3:
                    tempo = (mdata[0] << 16) | (mdata[1] << 8) | mdata[2]
                    events.append((t, 'T', tempo))
            elif b in (0xF0, 0xF7):
                p += 1
                slen, p = read_vlq(raw, p)
                p += slen
            elif b & 0x80:
                rs = b; p += 1
                n = midi_data_len(rs)
                events.append((t, 'M', bytes([rs] + list(raw[p:p+n]))))
                p += n
            else:
                n = midi_data_len(rs)
                events.append((t, 'M', bytes([rs] + list(raw[p:p+n]))))
                p += n

        off = end

    events.sort(key=lambda e: (e[0], 0 if e[1] == 'T' else 1))
    return events, div


# ---------------------------------------------------------------------------
# Cook MIDI events into compact binary for the ISR
# Format: [u16 wait_ticks] [u8 count] [bytes...] ... [u16 0xFFFF = loop]
# ---------------------------------------------------------------------------

def cook_events(events, div, target_hz=BASE_HZ):
    us_per_tick = 1e6 / target_hz

    tempo = 500000
    last_t = 0
    last_us = 0.0

    timed = []
    for tick, kind, data in events:
        us_per_mt = float(tempo) / float(div)
        us = last_us + (tick - last_t) * us_per_mt
        if kind == 'T':
            last_t, last_us, tempo = tick, us, data
        elif kind == 'M':
            timed.append((us, data))

    groups = OrderedDict()
    for us, mbytes in timed:
        tt = max(0, int(us / us_per_tick))
        if tt not in groups:
            groups[tt] = bytearray()
        groups[tt].extend(mbytes)

    out = bytearray()
    prev = 0
    first = True
    for tt in sorted(groups):
        wait = tt - prev
        if wait < 0:
            wait = 0
        if first and wait < 1:
            wait = 1
        first = False
        midi = groups[tt]
        i = 0
        while i < len(midi):
            chunk = midi[i:i+255]
            w = wait if i == 0 else 0
            out += struct.pack('<H', w)
            out.append(len(chunk))
            out.extend(chunk)
            i += 255
        prev = tt

    out += struct.pack('<H', 0xFFFF)
    return bytes(out)


# ---------------------------------------------------------------------------
# Build MODS.COM
# ---------------------------------------------------------------------------

def build_mods_com(cooked_main, cooked_fusion):
    a = Asm16()

    # =================================================================
    #  RESIDENT SECTION (stays in memory when TSR)
    # =================================================================

    # Resident grew past ±32K of entry; use register indirect jmp to init
    a.mov_r16_label('bx', 'init')
    a.db(0xFF, 0xE3)            # jmp bx

    # -- Resident data --
    a.label('old_08_off');   a.dw(0)
    a.label('old_08_seg');   a.dw(0)
    a.label('data_ptr');     a.dw(0)
    a.label('wait_ctr');     a.dw(1)
    a.label('chain_acc');    a.dw(0)
    a.label('chain_step');   a.dw(182)
    a.label('chain_thresh'); a.dw(728)
    a.label('muted');        a.db(0)
    a.label('suspend_main'); a.db(0)   # 1 while satellite loads — stop MAIN stream / MPU fights
    a.label('bgm_track');     a.db(0)   # 0 = MAIN stream, 1 = FUSION (isr_loop rewind target)
    a.label('prev_scan');    a.db(0)
    a.label('wait_restore_psp'); a.dw(0)  # parent PSP: restore music only on WAIT when AH=62h matches
    a.label('exec_psp_snapshot'); a.dw(0)  # PSP read before nested EXEC (avoid AH=62 after child load)
    a.label('old_21_off');   a.dw(0)
    a.label('old_21_seg');   a.dw(0)
    a.dw(0xB601)              # tag before isr — slave finds BIOS vector via INT 35h + layout

    # -- Resident ISR: INT 08h handler --
    # PIT at game_speed×4 Hz with bgm (perfect 4:1 at default 18.2 Hz)
    # jitter).  Each tick processes exactly one cooked MIDI tick.  A chain
    # prescaler throttles BIOS tick-counter updates to game_speed rate.
    a.label('isr')
    a.push('ax');  a.push('cx');  a.push('dx');  a.push('si')
    a.db(0x1E)                   # push ds
    a.db(0x0E, 0x1F)            # push cs; pop ds

    # ---- Chain prescaler: game tick rate control ----
    # chain_acc += chain_step; fire when >= chain_thresh (COOK_HZ * 10)
    a.mov_ax_mem('chain_acc')
    a.db(0x03, 0x06); a._fixup('abs16', 'chain_step'); a._word(0)  # ADD AX, [chain_step]
    a.db(0x3B, 0x06); a._fixup('abs16', 'chain_thresh'); a._word(0)  # CMP AX, [chain_thresh]
    a.jb('isr_no_chain')

    a.db(0x2B, 0x06); a._fixup('abs16', 'chain_thresh'); a._word(0)  # SUB AX, [chain_thresh]
    a.mov_mem_ax('chain_acc')
    # Chain to original INT 08h (BIOS tick counter + EOI)
    a.db(0x9C)                   # pushf (simulate INT frame)
    a.db(0xFF, 0x1E)             # call far [old_08_off]
    a._fixup('abs16', 'old_08_off'); a._word(0)
    a.db(0xFA)                   # cli — BIOS may STI; block nested IRQ0 during MIDI

    # ---- F11: mute/unmute BGM (bgm=1 only; chain ticks only) ----
    a.db(0xE4, 0x60)            # in al, 0x60
    a.db(0x3A, 0x06); a._fixup('abs16', 'prev_scan'); a._word(0)  # cmp al, [prev_scan]
    a.je('isr_midi')             # same scan code — skip
    a.db(0xA2); a._fixup('abs16', 'prev_scan'); a._word(0)        # mov [prev_scan], al
    a.cmp_al_imm(0x57)          # F11 make code?
    a.jne('isr_midi')
    # Toggle muted; if newly muted, All Notes Off (CC#123 on all channels)
    a.db(0x80, 0x36); a._fixup('abs16', 'muted'); a._word(0)  # XOR byte [muted], 1
    a.db(0x01)
    a.db(0x80, 0x3E); a._fixup('abs16', 'muted'); a._word(0)  # CMP byte [muted], 0
    a.db(0x00)
    a.je('isr_midi')            # unmuted — no anoff
    a.push('bx');  a.push('cx')
    a.mov_r16_imm('cx', 16)
    a.xor_r8('bl')
    a.label('isr_mute_anoff')
    a.mov_r8_imm('al', 0xB0)
    a.db(0x08, 0xD8)            # or al, bl
    a.mov_r16_imm('dx', 0x0330)
    a.db(0xEE)                   # out dx, al
    a.mov_r8_imm('al', 0x7B)
    a.db(0xEE)                   # All Notes Off
    a.xor_r8('al')
    a.db(0xEE)                   # value 0
    a.db(0xFE, 0xC3)            # inc bl
    a.loop('isr_mute_anoff')
    a.pop('cx');  a.pop('bx')
    a.jmp('isr_midi')

    a.label('isr_no_chain')
    a.mov_mem_ax('chain_acc')
    # No chain — send EOI ourselves
    a.mov_r8_imm('al', 0x20)
    a.db(0xE6, 0x20)            # out 0x20, al

    # ---- Process MIDI ----
    a.label('isr_midi')

    # ---- Skip MIDI when muted ----
    a.db(0x80, 0x3E); a._fixup('abs16', 'muted'); a._word(0)  # CMP byte [muted], 0
    a.db(0x00)
    a.jne('isr_done')
    # ---- Skip MAIN stream while FIGHTBGM/TRANSFORM is taking over INT 08 / MPU ----
    a.db(0x80, 0x3E); a._fixup('abs16', 'suspend_main'); a._word(0)
    a.db(0x00)
    a.jne('isr_done')
    a.cld()
    a.db(0xFF, 0x0E); a._fixup('abs16', 'wait_ctr'); a._word(0)   # DEC word [wait_ctr]
    a.jnz('isr_done')

    a.db(0x8B, 0x36); a._fixup('abs16', 'data_ptr'); a._word(0)   # MOV SI, [data_ptr]

    a.label('isr_frame')
    a.lodsb()                    # count byte
    a.xor_r8('ch')
    a.mov_rr8('cl', 'al')
    a.jcxz('isr_next_wait')

    a.mov_r16_imm('dx', 0x0330)
    a.label('isr_send')
    a.lodsb()
    a.db(0xEE)                   # out dx, al
    a.loop('isr_send')

    a.label('isr_next_wait')
    a.db(0xAD)                   # lodsw — next wait value
    a.cmp_ax_imm(0xFFFF)
    a.je('isr_loop')
    a.db(0x85, 0xC0)            # test ax, ax
    a.je('isr_frame')            # wait=0 → process next frame immediately

    a.mov_mem_ax('wait_ctr')
    a.db(0x89, 0x36); a._fixup('abs16', 'data_ptr'); a._word(0)   # MOV [data_ptr], SI

    a.label('isr_done')
    a.db(0x1F)                   # pop ds
    a.pop('si');  a.pop('dx');  a.pop('cx');  a.pop('ax')
    a.db(0xCF)                   # iret

    # -- Loop: all notes off, rewind to start of song --
    a.label('isr_loop')
    a.mov_r16_imm('cx', 16)
    a.xor_r8('bl')
    a.label('isr_anoff')
    a.mov_r8_imm('al', 0xB0)
    a.db(0x08, 0xD8)            # or al, bl
    a.mov_r16_imm('dx', 0x0330)
    a.db(0xEE)                   # out dx, al  (CC#)
    a.mov_r8_imm('al', 0x7B)
    a.db(0xEE)                   # out dx, al  (All Notes Off)
    a.xor_r8('al')
    a.db(0xEE)                   # out dx, al  (value 0)
    a.db(0xFE, 0xC3)            # inc bl
    a.loop('isr_anoff')

    a.db(0x80, 0x3E); a._fixup('abs16', 'bgm_track'); a._word(0)  # CMP byte [bgm_track], 0
    a.db(0x00)
    a.je('isr_rewind_main')
    a.mov_r16_label('si', 'event_data_fusion')
    a.jmp('isr_rewind_go')
    a.label('isr_rewind_main')
    a.mov_r16_label('si', 'event_data')
    a.label('isr_rewind_go')
    a.db(0xAD)                   # lodsw — first wait of new loop
    a.db(0x85, 0xC0)            # test ax, ax
    a.je('isr_frame')
    a.mov_mem_ax('wait_ctr')
    a.db(0x89, 0x36); a._fixup('abs16', 'data_ptr'); a._word(0)
    a.jmp('isr_done')

    # -- INT 21h: FIGHT → in-process FUSION; CONTEST → TRANSFORM.COM; AH=4Dh → MAIN + restore INT 08 --
    a.label('all_notes_off_res')
    a.push('bx');  a.push('cx')
    a.mov_r16_imm('cx', 16)
    a.xor_r8('bl')
    a.label('anoff_res')
    a.mov_r8_imm('al', 0xB0)
    a.db(0x08, 0xD8)            # or al, bl
    a.mov_r16_imm('dx', 0x0330)
    a.db(0xEE)
    a.mov_r8_imm('al', 0x7B)
    a.db(0xEE)
    a.xor_r8('al')
    a.db(0xEE)
    a.db(0xFE, 0xC3)            # inc bl
    a.loop('anoff_res')
    a.pop('cx');  a.pop('bx')
    a.ret()

    # Re-hook INT 08 to MODS isr (satellite COM replaced it during fight/contest)
    a.label('restore_int08_is_mods')
    a.push('ax')
    a.push('dx')
    a.db(0x1E)                   # push ds
    a.mov_r16_imm('ax', 0x2508)
    a.db(0x0E, 0x1F)            # push cs; pop ds
    a.mov_r16_label('dx', 'isr')
    a.int21()
    a.db(0x1F)                   # pop ds
    a.pop('dx')
    a.pop('ax')
    a.ret()

    a.label('music_switch_main')
    a.call('all_notes_off_res')
    a.db(0x0E, 0x1F)            # push cs; pop ds
    a.mov_r16_label('si', 'event_data')
    a.db(0xAD)                   # lodsw
    a.mov_mem_ax('wait_ctr')
    a.db(0x89, 0x36); a._fixup('abs16', 'data_ptr'); a._word(0)
    a.call('restore_int08_is_mods')
    a.mov_mem8_imm('suspend_main', 0)
    a.mov_mem8_imm('bgm_track', 0)
    a.mov_mem16_imm('wait_restore_psp', 0)
    a.db(0xC3)                   # ret

    # Switch to FUSION stream in-process (same INT 08 / MPU — no satellite TSR).
    a.label('music_switch_fusion')
    a.call('all_notes_off_res')
    a.db(0x0E, 0x1F)            # push cs; pop ds
    a.mov_r16_label('si', 'event_data_fusion')
    a.db(0xAD)                   # lodsw — first wait
    a.mov_mem_ax('wait_ctr')
    a.db(0x89, 0x36); a._fixup('abs16', 'data_ptr'); a._word(0)
    a.mov_mem8_imm('bgm_track', 1)
    a.db(0xC3)                   # ret

    # Bare token at DS:SI is a path component? CF=1 if SI==DX or [SI-1] is \ or /
    # (Avoids NOCONTESCONTEST matching inner "CONTEST". DX = pathname offset from EXEC.)
    a.label('path_bare_token_ok')
    a.push('ax')
    a.push('bx')
    a.db(0x39, 0xD6)            # CMP SI, DX
    a.je('pbtk_yes')
    a.mov_rr16('bx', 'si')
    a.dec16('bx')
    a.db(0x8A, 0x07)            # MOV AL, [BX]
    a.cmp_al_imm(0x5C)          # '\'
    a.je('pbtk_yes')
    a.cmp_al_imm(ord('/'))
    a.je('pbtk_yes')
    a.cmp_al_imm(ord(':'))
    a.je('pbtk_yes')
    a.pop('bx')
    a.pop('ax')
    a.db(0xF8)
    a.ret()
    a.label('pbtk_yes')
    a.pop('bx')
    a.pop('ax')
    a.db(0xF9)
    a.ret()

    # DS:SI -> possible start of filename: "FIGHT" + NUL or "fight" + NUL? CF=1 if yes
    a.label('bare_fight_name_at_si')
    a.push('bx')
    a.mov_rr16('bx', 'si')
    a.db(0x8A, 0x07)            # MOV AL, [BX]
    a.cmp_al_imm(ord('F'))
    a.je('bf_chk_i')
    a.cmp_al_imm(ord('f'))
    a.jne('bf_fail')
    a.db(0x8A, 0x47, 0x01)
    a.cmp_al_imm(ord('i'))
    a.jne('bf_fail')
    a.db(0x8A, 0x47, 0x02)
    a.cmp_al_imm(ord('g'))
    a.jne('bf_fail')
    a.db(0x8A, 0x47, 0x03)
    a.cmp_al_imm(ord('h'))
    a.jne('bf_fail')
    a.db(0x8A, 0x47, 0x04)
    a.cmp_al_imm(ord('t'))
    a.jne('bf_fail')
    a.db(0x80, 0x7F, 0x05, 0x00)  # CMP byte [BX+5], 0
    a.jne('bf_fail')
    a.pop('bx')
    a.db(0xF9)
    a.ret()
    a.label('bf_chk_i')
    a.db(0x8A, 0x47, 0x01)
    a.cmp_al_imm(ord('I'))
    a.jne('bf_fail')
    a.db(0x8A, 0x47, 0x02)
    a.cmp_al_imm(ord('G'))
    a.jne('bf_fail')
    a.db(0x8A, 0x47, 0x03)
    a.cmp_al_imm(ord('H'))
    a.jne('bf_fail')
    a.db(0x8A, 0x47, 0x04)
    a.cmp_al_imm(ord('T'))
    a.jne('bf_fail')
    a.db(0x80, 0x7F, 0x05, 0x00)
    a.jne('bf_fail')
    a.pop('bx')
    a.db(0xF9)
    a.ret()
    a.label('bf_fail')
    a.pop('bx')
    a.db(0xF8)
    a.ret()

    # DS:SI -> "CONTEST" + NUL / "contest" + NUL? CF=1 if yes
    a.label('bare_contest_name_at_si')
    a.push('bx')
    a.mov_rr16('bx', 'si')
    a.db(0x8A, 0x07)
    a.cmp_al_imm(ord('C'))
    a.je('bc_u')
    a.cmp_al_imm(ord('c'))
    a.jne('bc_fail')
    a.db(0x80, 0x7F, 0x01, ord('o'))
    a.jne('bc_fail')
    a.db(0x80, 0x7F, 0x02, ord('n'))
    a.jne('bc_fail')
    a.db(0x80, 0x7F, 0x03, ord('t'))
    a.jne('bc_fail')
    a.db(0x80, 0x7F, 0x04, ord('e'))
    a.jne('bc_fail')
    a.db(0x80, 0x7F, 0x05, ord('s'))
    a.jne('bc_fail')
    a.db(0x80, 0x7F, 0x06, ord('t'))
    a.jne('bc_fail')
    a.db(0x80, 0x7F, 0x07, 0x00)
    a.jne('bc_fail')
    a.pop('bx')
    a.db(0xF9)
    a.ret()
    a.label('bc_u')
    a.db(0x80, 0x7F, 0x01, ord('O'))
    a.jne('bc_fail')
    a.db(0x80, 0x7F, 0x02, ord('N'))
    a.jne('bc_fail')
    a.db(0x80, 0x7F, 0x03, ord('T'))
    a.jne('bc_fail')
    a.db(0x80, 0x7F, 0x04, ord('E'))
    a.jne('bc_fail')
    a.db(0x80, 0x7F, 0x05, ord('S'))
    a.jne('bc_fail')
    a.db(0x80, 0x7F, 0x06, ord('T'))
    a.jne('bc_fail')
    a.db(0x80, 0x7F, 0x07, 0x00)
    a.jne('bc_fail')
    a.pop('bx')
    a.db(0xF9)
    a.ret()
    a.label('bc_fail')
    a.pop('bx')
    a.db(0xF8)
    a.ret()

    # Path at DS:DX contains "FIGHT.EXE" (case as on disk)? CF=1 if yes
    a.label('path_has_fight_exe')
    a.cld()
    a.push('bx')
    a.mov_rr16('si', 'dx')
    a.mov_r16_imm('bx', 200)
    a.label('ph_loop')
    a.db(0x85, 0xDB)            # test bx, bx
    a.jl('ph_fail')
    a.dec16('bx')
    a.db(0x80, 0x3C, 0x00)      # cmp byte [si], 0
    a.je('ph_fail')
    a.push('si')
    a.push('bx')
    a.db(0x0E, 0x07)            # push cs; pop es
    a.mov_r16_label('di', 'str_fight_exe')
    a.mov_r16_imm('cx', 9)
    a.db(0xF3, 0xA6)            # repe cmpsb  (DS:SI vs ES:DI)
    a.pop('bx')
    a.pop('si')
    a.je('ph_ok')
    a.push('si')
    a.push('bx')
    a.db(0x0E, 0x07)            # push cs; pop es
    a.mov_r16_label('di', 'str_fight_lower')
    a.mov_r16_imm('cx', 9)
    a.db(0xF3, 0xA6)            # try "fight.exe"
    a.pop('bx')
    a.pop('si')
    a.je('ph_ok')
    a.call('bare_fight_name_at_si')
    a.jnc('ph_after_bare_fight')
    a.call('path_bare_token_ok')
    a.jc('ph_ok')               # PLAY.COM uses "FIGHT" + NUL (cwd SYS after CD)
    a.label('ph_after_bare_fight')
    a.inc16('si')
    a.jmp('ph_loop')
    a.label('ph_ok')
    a.pop('bx')
    a.db(0xF9)                   # stc
    a.db(0xC3)
    a.label('ph_fail')
    a.pop('bx')
    a.db(0xF8)                   # clc
    a.db(0xC3)

    # Path at DS:DX contains "CONTEST.EXE"? CF=1 if yes
    a.label('path_has_contest_exe')
    a.cld()
    a.push('bx')
    a.mov_rr16('si', 'dx')
    a.mov_r16_imm('bx', 200)
    a.label('phc_loop')
    a.db(0x85, 0xDB)
    a.jl('phc_fail')
    a.dec16('bx')
    a.db(0x80, 0x3C, 0x00)
    a.je('phc_fail')
    a.push('si')
    a.push('bx')
    a.db(0x0E, 0x07)
    a.mov_r16_label('di', 'str_contest_exe')
    a.mov_r16_imm('cx', 10)
    a.db(0xF3, 0xA6)
    a.pop('bx')
    a.pop('si')
    a.je('phc_ok')
    a.push('si')
    a.push('bx')
    a.db(0x0E, 0x07)
    a.mov_r16_label('di', 'str_contest_lower')
    a.mov_r16_imm('cx', 10)
    a.db(0xF3, 0xA6)
    a.pop('bx')
    a.pop('si')
    a.je('phc_ok')
    a.call('bare_contest_name_at_si')
    a.jnc('phc_after_bare_contest')
    a.call('path_bare_token_ok')
    a.jc('phc_ok')              # "CONTEST" + NUL without .EXE (not NOCONTESCONTEST)
    a.label('phc_after_bare_contest')
    a.inc16('si')
    a.jmp('phc_loop')
    a.label('phc_ok')
    a.pop('bx')
    a.db(0xF9)
    a.db(0xC3)
    a.label('phc_fail')
    a.pop('bx')
    a.db(0xF8)
    a.db(0xC3)

    a.label('dos_isr')
    a.db(0xFB)                   # STI
    a.db(0x80, 0xFC, 0x4B)      # cmp ah, 4Bh
    a.je('dos_exec_check')
    a.db(0x80, 0xFC, 0x4D)      # cmp ah, 4Dh
    a.jne('dos_not_wait')
    a.jmp_near('dos_wait_check')
    a.label('dos_not_wait')
    a.label('dos_chain')
    a.db(0x2E, 0xFF, 0x2E)      # jmp far [CS:old_21_off]
    a._fixup('abs16', 'old_21_off'); a._word(0)

    a.label('dos_exec_check')
    a.cmp_al_imm(0)
    a.je('dos_exec_al0')
    a.jmp_near('dos_chain')
    a.label('dos_exec_al0')
    a.push('ax');  a.push('bx');  a.push('cx');  a.push('dx');  a.push('si')
    a.push('di');  a.push('bp')
    a.db(0x06)                   # push es
    a.call('path_has_fight_exe')
    a.jc('dos_exec_fight')
    a.call('path_has_contest_exe')
    a.jc('dos_exec_contest')
    a.db(0x07)                   # pop es
    a.pop('bp');  a.pop('di');  a.pop('si');  a.pop('dx')
    a.pop('cx');  a.pop('bx');  a.pop('ax')
    a.jmp_near('dos_chain')
    a.label('dos_exec_fight')
    a.db(0x1E)                   # push ds
    a.db(0x0E, 0x1F)            # push cs; pop ds
    a.mov_mem16_imm('wait_restore_psp', 0)
    a.push('ax')
    a.push('bx')
    a.mov_r8_imm('ah', 0x62)
    a.int21()
    a.mov_rr16('ax', 'bx')
    a.mov_mem_ax('exec_psp_snapshot')
    a.pop('bx')
    a.pop('ax')
    a.call('music_switch_fusion')
    a.mov_ax_mem('exec_psp_snapshot')
    a.mov_mem_ax('wait_restore_psp')
    a.label('dos_spawn_fight_join')
    a.db(0x1F)                   # pop ds
    a.db(0x07)                   # pop es
    a.pop('bp');  a.pop('di');  a.pop('si');  a.pop('dx')
    a.pop('cx');  a.pop('bx');  a.pop('ax')
    a.jmp_near('dos_chain')
    a.label('dos_exec_contest')
    a.db(0x1E)
    a.db(0x0E, 0x1F)
    a.mov_mem16_imm('wait_restore_psp', 0)
    a.push('ax')
    a.push('bx')
    a.mov_r8_imm('ah', 0x62)
    a.int21()
    a.mov_rr16('ax', 'bx')
    a.mov_mem_ax('exec_psp_snapshot')
    a.pop('bx')
    a.pop('ax')
    a.call('all_notes_off_res')
    a.mov_mem8_imm('suspend_main', 1)
    a.mov_r8_imm('ah', 0x4B)
    a.mov_r8_imm('al', 0x00)
    a.mov_r16_label('dx', 'fn_transform_cwd')
    a.int21()
    a.jnc('dos_contest_spawned')
    a.mov_r16_label('dx', 'fn_transform_sys')
    a.int21()
    a.label('dos_contest_spawned')
    a.jc('dos_spawn_contest_undo')
    a.mov_ax_mem('exec_psp_snapshot')
    a.mov_mem_ax('wait_restore_psp')
    a.jmp('dos_spawn_contest_join')
    a.label('dos_spawn_contest_undo')
    a.mov_mem8_imm('suspend_main', 0)
    a.mov_mem16_imm('wait_restore_psp', 0)
    a.label('dos_spawn_contest_join')
    a.db(0x1F)
    a.db(0x07)
    a.pop('bp');  a.pop('di');  a.pop('si');  a.pop('dx')
    a.pop('cx');  a.pop('bx');  a.pop('ax')
    a.jmp_near('dos_chain')

    a.label('dos_wait_check')
    a.push('ax')                 # preserve AH=4Dh (etc.) for real WAIT after chain
    a.push('bx')
    a.db(0x1E)                   # push ds
    a.db(0x0E, 0x1F)            # push cs; pop ds
    a.mov_bx_mem('wait_restore_psp')
    a.db(0x85, 0xDB)            # test bx, bx
    a.db(0x1F)                   # pop ds
    a.pop('bx')
    a.jnz('dos_wait_psp_cmp')
    a.pop('ax')
    a.jmp_near('dos_chain')
    a.label('dos_wait_psp_cmp')
    a.push('bx')
    a.push('cx')
    a.db(0x1E)                   # push ds
    a.db(0x0E, 0x1F)
    a.db(0x8B, 0x0E); a._fixup('abs16', 'wait_restore_psp'); a._word(0)  # MOV CX,[wait_restore_psp]
    a.mov_r8_imm('ah', 0x62)
    a.int21()
    a.db(0x3B, 0xD9)            # CMP BX, CX  (current PSP vs parent that EXEC'd FIGHT)
    a.db(0x1F)                   # pop ds
    a.pop('cx')
    a.pop('bx')
    a.je('dos_wait_restore_pop_ax')
    a.pop('ax')
    a.jmp_near('dos_chain')
    a.label('dos_wait_restore_pop_ax')
    a.pop('ax')
    a.label('dos_wait_restore_main')
    a.push('ax');  a.push('bx');  a.push('cx');  a.push('dx');  a.push('si')
    a.push('di');  a.push('bp')
    a.db(0x06)                   # push es
    a.db(0x1E)                   # push ds
    a.db(0x0E, 0x1F)
    a.call('music_switch_main')
    a.db(0x1F)                   # pop ds
    a.db(0x07)                   # pop es
    a.pop('bp');  a.pop('di');  a.pop('si');  a.pop('dx')
    a.pop('cx');  a.pop('bx');  a.pop('ax')
    a.jmp_near('dos_chain')

    a.label('str_fight_exe')
    a.db(b'FIGHT.EXE')
    a.label('str_fight_lower')
    a.db(b'fight.exe')
    a.label('str_contest_exe')
    a.db(b'CONTEST.EXE')
    a.label('str_contest_lower')
    a.db(b'contest.exe')
    a.label('fn_transform_cwd')
    a.db(b'TRANSFORM.COM\x00')
    a.label('fn_transform_sys')
    a.db(b'SYS\\TRANSFORM.COM\x00')

    # -- Cooked MIDI (resident): MAIN + FUSION (contest stays in TRANSFORM.COM — size limit)
    a.label('event_data')
    a.db(cooked_main)
    a.label('event_data_fusion')
    a.db(cooked_fusion)
    a.label('end_resident')

    # =================================================================
    #  NON-RESIDENT SECTION (freed after TSR or on normal exit)
    # =================================================================

    a.label('init')
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

    a.mov_r16_label('si', 'str_vsync_off')
    a.call('search')
    a.mov_mem_al('flag_vsync_off')

    a.mov_r16_label('si', 'str_fast_mp')
    a.call('search')
    a.mov_mem_al('flag_fast_mp')

    a.mov_r16_label('si', 'str_cheap_supers')
    a.call('search')
    a.mov_mem_al('flag_cheap_supers')

    a.mov_r16_label('si', 'str_easy_supers')
    a.call('search')
    a.mov_mem_al('flag_easy_supers')

    a.mov_r16_label('si', 'str_bgm')
    a.call('search')
    a.mov_mem_al('flag_bgm')

    # -- game_speed: parse decimal Hz value from mods.cfg --
    # Format: game_speed=XX.X (PIT Hz / FPS). 18.2=normal; with bgm, match COOK_HZ/N in build.
    # Parsed as value×10 (one decimal place), stored in value_x10_var.
    a.mov_ax_mem('bytes_read')
    a.db(0x2D); a._word(10)     # SUB AX, 10 (positions to scan)
    a.cmp_ax_imm(1)
    a.db(0x7D, 0x03)            # JGE +3 (skip jmp if >= 1)
    a.jmp_near('gs_done')
    a.mov_rr16('cx', 'ax')
    a.mov_r16_label('di', 'read_buffer')

    a.label('gs_scan')
    a.push('cx');  a.push('di')
    a.mov_r16_label('si', 'str_game_speed')
    a.mov_r16_imm('cx', 11)     # len("game_speed=")

    a.label('gs_cmp')
    a.lodsb()
    a.cmp_al_di_ind()
    a.jne('gs_miss')
    a.inc16('di')
    a.loop('gs_cmp')
    a.pop('ax');  a.pop('cx')    # discard saved DI and CX
    a.jmp('gs_parse')

    a.label('gs_miss')
    a.pop('di');  a.pop('cx')
    a.inc16('di')
    a.loop('gs_scan')
    a.jmp_near('gs_done')

    # Parse decimal number at [DI]
    a.label('gs_parse')
    a.xor_r16('ax')             # integer accumulator
    a.xor_r16('cx')             # decimal digit (default 0)

    a.label('gs_int')
    a.db(0x8A, 0x1D)            # MOV BL, [DI]
    a.db(0x80, 0xFB, ord('0'))  # CMP BL, '0'
    a.jb('gs_int_done')
    a.db(0x80, 0xFB, ord('9'))  # CMP BL, '9'
    a.ja('gs_int_done')
    a.db(0x80, 0xEB, ord('0'))  # SUB BL, '0'
    a.xor_r8('bh')
    a.push('bx')
    a.mov_r16_imm('bx', 10)
    a.db(0xF7, 0xE3)            # MUL BX (DX:AX = AX × 10)
    a.pop('bx')
    a.add_rr16('ax', 'bx')
    a.inc16('di')
    a.jmp('gs_int')

    a.label('gs_int_done')
    a.cmp_byte_di_ind_imm(ord('.'))
    a.jne('gs_mul')
    a.inc16('di')
    a.db(0x8A, 0x1D)            # MOV BL, [DI]
    a.db(0x80, 0xFB, ord('0'))
    a.jb('gs_mul')
    a.db(0x80, 0xFB, ord('9'))
    a.ja('gs_mul')
    a.db(0x80, 0xEB, ord('0'))  # SUB BL, '0'
    a.xor_r8('bh')
    a.mov_rr16('cx', 'bx')     # CX = decimal digit

    a.label('gs_mul')
    a.mov_r16_imm('bx', 10)
    a.db(0xF7, 0xE3)            # MUL BX
    a.add_rr16('ax', 'cx')      # AX = value × 10

    # Cap at 2000 (200.0 Hz)
    a.cmp_ax_imm(2000)
    a.jbe('gs_cap_ok')
    a.mov_r16_imm('ax', 2000)
    a.label('gs_cap_ok')

    # Always store the effective Hz*10 (default 182 if parser didn't run)
    a.mov_mem_ax('value_x10_var')

    # 18.2 Hz or below (after offset) → no PIT change needed
    a.cmp_ax_imm(183)
    a.db(0x73, 0x03)            # JNB +3 (skip jmp if >= 183)
    a.jmp_near('gs_done')

    # PIT divisor = 11931820 / value_x10  (1193182 Hz × 10)
    a.push('ax')
    a.mov_r16_imm('dx', 0x00B6)
    a.mov_r16_imm('ax', 0x10AC)  # DX:AX = 0x00B610AC = 11931820
    a.pop('cx')
    a.db(0xF7, 0xF1)            # DIV CX → AX = divisor
    a.mov_mem_ax('pit_divisor_val')

    a.label('gs_done')

    # When bgm=1: TSR + PIT/chain_thresh from build; F11 = mute/unmute.
    # Game tick rate is throttled by the chain prescaler in the ISR.
    a.mov_al_mem('flag_bgm')
    a.cmp_al_imm(1)
    a.jne('gs_bgm_done')

    # chain_step = value_x10_var (game_speed * 10)
    a.mov_ax_mem('value_x10_var')
    a.mov_mem_ax('chain_step')

    # PIT fixed at 72.8 Hz (= 18.2 × 4) for MIDI timing.
    # chain_thresh = 728 (72.8 × 10). Perfect 4:1 at game_speed=18.2.
    a.mov_r16_imm('ax', 728)
    a.mov_mem_ax('chain_thresh')

    # PIT divisor = 16390 (1193182 / 72.8)
    a.mov_r16_imm('ax', 16390)
    a.mov_mem_ax('pit_divisor_val')

    a.label('gs_bgm_done')

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

    # free_run patch 4: offset 0x1B1D7, 5 bytes (second -10 MP for run)
    a.mov_al_mem('flag_free_run')
    a.mov_r16_imm('cx', 0x0001)
    a.mov_r16_imm('dx', 0xB1D7)
    a.mov_r16_label('si', 'nops')
    a.mov_r16_label('di', 'sub_mp_orig')
    a.mov_r8_imm('bl', 5)
    a.call('apply_patch')

    # free_run patch 5: offset 0x1B181, 1 byte (first MP>=10 gate: JNL→JMP)
    a.mov_al_mem('flag_free_run')
    a.mov_r16_imm('cx', 0x0001)
    a.mov_r16_imm('dx', 0xB181)
    a.mov_r16_label('si', 'jmp_byte')
    a.mov_r16_label('di', 'jnl_byte')
    a.mov_r8_imm('bl', 1)
    a.call('apply_patch')

    # free_run patch 6: offset 0x1B1C8, 1 byte (second MP>=10 gate: JNL→JMP)
    a.mov_al_mem('flag_free_run')
    a.mov_r16_imm('cx', 0x0001)
    a.mov_r16_imm('dx', 0xB1C8)
    a.mov_r16_label('si', 'jmp_byte')
    a.mov_r16_label('di', 'jnl_byte')
    a.mov_r8_imm('bl', 1)
    a.call('apply_patch')

    # free_jump patch: offset 0x1B1D7, 5 bytes (jump -10 MP)
    a.mov_al_mem('flag_free_jump')
    a.mov_r16_imm('cx', 0x0001)
    a.mov_r16_imm('dx', 0xB1D7)
    a.mov_r16_label('si', 'nops')
    a.mov_r16_label('di', 'sub_mp_orig')
    a.mov_r8_imm('bl', 5)
    a.call('apply_patch')

    # cheap_supers: halve cost in push/compute/pop blocks before every CMP and SUB
    for cx_hi, dx_lo in [(0x0000, 0x9D73), (0x0000, 0xC35B), (0x0000, 0xCAEF),
                          (0x0001, 0x083E), (0x0001, 0x09CD), (0x0001, 0x9FE9),
                          (0x0000, 0x8DE6), (0x0000, 0xC86C), (0x0000, 0xC94F),
                          (0x0000, 0xCB94), (0x0001, 0x0880), (0x0001, 0x0A16)]:
        a.mov_al_mem('flag_cheap_supers')
        a.mov_r16_imm('cx', cx_hi)
        a.mov_r16_imm('dx', dx_lo)
        a.mov_r16_label('si', 'cheap_cost_on')
        a.mov_r16_label('di', 'cheap_cost_off')
        a.mov_r8_imm('bl', 11)
        a.call('apply_patch')

    # cheap_supers: DI-variant mana check at file 0xE83E
    a.mov_al_mem('flag_cheap_supers')
    a.mov_r16_imm('cx', 0x0000)
    a.mov_r16_imm('dx', 0xE83E)
    a.mov_r16_label('si', 'cheap_cost_on_di')
    a.mov_r16_label('di', 'cheap_cost_off_di')
    a.mov_r8_imm('bl', 11)
    a.call('apply_patch')

    # cheap_supers: hardcoded 25 MP → 12 MP at file 0x1187E
    a.mov_al_mem('flag_cheap_supers')
    a.mov_r16_imm('cx', 0x0001)
    a.mov_r16_imm('dx', 0x187E)
    a.mov_r16_label('si', 'sub_mp_12')
    a.mov_r16_label('di', 'sub_mp_25_orig')
    a.mov_r8_imm('bl', 5)
    a.call('apply_patch')

    # cheap_supers: hardcoded 50 MP → 25 MP at file 0x156EC
    a.mov_al_mem('flag_cheap_supers')
    a.mov_r16_imm('cx', 0x0001)
    a.mov_r16_imm('dx', 0x56EC)
    a.mov_r16_label('si', 'sub_mp_25_orig')
    a.mov_r16_label('di', 'sub_mp_50_orig')
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
    # free_supers: skip "enough MP?" gate at 0x9D82 — JNG→JMP (1 byte)
    a.mov_al_mem('flag_free_supers')
    a.mov_r16_imm('cx', 0x0000)
    a.mov_r16_imm('dx', 0x9D82)
    a.mov_r16_label('si', 'jmp_byte')
    a.mov_r16_label('di', 'jng_byte')
    a.mov_r8_imm('bl', 1)
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

    # vsync=0: skip retrace wait (EB→CB at 0x22435, RETF instead of JMP)
    a.mov_al_mem('flag_vsync_off')
    a.mov_r16_imm('cx', 0x0002)
    a.mov_r16_imm('dx', 0x2435)
    a.mov_r16_label('si', 'retf_byte')
    a.mov_r16_label('di', 'jmp_short_byte')
    a.mov_r8_imm('bl', 1)
    a.call('apply_patch')

    # easy_supers=1: replace combo handlers A,B,C,D,E,H with single-key check
    for label_suffix, cx_hi, dx_lo in [
        ('A', 0x0000, 0x9868),
        ('B', 0x0000, 0x9924),
        ('C', 0x0000, 0x99E0),
        ('D', 0x0000, 0x9A9C),
        ('E', 0x0000, 0x9B38),
    ]:
        a.mov_al_mem('flag_easy_supers')
        a.mov_r16_imm('cx', cx_hi)
        a.mov_r16_imm('dx', dx_lo)
        a.mov_r16_label('si', f'easy_super_{label_suffix}')
        a.mov_r16_label('di', f'combo_{label_suffix}_orig')
        a.mov_r8_imm('bl', 86)
        a.call('apply_patch')
    # Handler H: 139 bytes
    a.mov_al_mem('flag_easy_supers')
    a.mov_r16_imm('cx', 0x0000)
    a.mov_r16_imm('dx', 0x9C14)
    a.mov_r16_label('si', 'easy_super_H')
    a.mov_r16_label('di', 'combo_H_orig')
    a.mov_r8_imm('bl', 139)
    a.call('apply_patch')

    # easy_run: ISR hook + code cave
    a.mov_al_mem('flag_easy_supers')
    a.mov_r16_imm('cx', 0x0000)
    a.mov_r16_imm('dx', 0x7386)
    a.mov_r16_label('si', 'easy_run_hook')
    a.mov_r16_label('di', 'easy_run_hook_orig')
    a.mov_r8_imm('bl', 3)
    a.call('apply_patch')

    a.mov_al_mem('flag_easy_supers')
    a.mov_r16_imm('cx', 0x0000)
    a.mov_r16_imm('dx', 0x9B8E)
    a.mov_r16_label('si', 'easy_run_cave')
    a.mov_r16_label('di', 'easy_run_cave_orig')
    a.mov_r8_imm('bl', 133)
    a.call('apply_patch')

    # cheap_supers + easy_supers: halve the 50 MP summon cost in handler H
    a.mov_al_mem('flag_easy_supers')
    a.cmp_al_imm(1)
    a.jne('skip_h_cheap')
    a.mov_al_mem('flag_cheap_supers')
    a.mov_r16_imm('cx', 0x0000)
    a.mov_r16_imm('dx', 0x9C6D)
    a.mov_r16_label('si', 'sub_mp_25_orig')
    a.mov_r16_label('di', 'sub_mp_50_orig')
    a.mov_r8_imm('bl', 5)
    a.call('apply_patch')
    a.label('skip_h_cheap')

    # free_supers + easy_supers: NOP the 50 MP summon cost in handler H
    a.mov_al_mem('flag_easy_supers')
    a.cmp_al_imm(1)
    a.jne('skip_h_free')
    a.mov_al_mem('flag_free_supers')
    a.mov_r16_imm('cx', 0x0000)
    a.mov_r16_imm('dx', 0x9C6D)
    a.mov_r16_label('si', 'nops')
    a.mov_r16_label('di', 'sub_mp_50_orig')
    a.mov_r8_imm('bl', 5)
    a.call('apply_patch')
    a.label('skip_h_free')

    # Close FIGHT.EXE
    a.mov_bx_mem('cur_handle')
    a.mov_r8_imm('ah', 0x3E)
    a.int21()

    # =================================================================
    #  TSR / PIT decision
    # =================================================================

    # Check if BGM requested → need TSR for music playback
    a.mov_al_mem('flag_bgm')
    a.cmp_al_imm(1)
    a.je('tsr_init')

    # -- No TSR needed; reprogram PIT for game_speed if != 1.0 --
    a.mov_ax_mem('pit_divisor_val')
    a.db(0x85, 0xC0)            # test ax, ax
    a.jnz('pit_do_reprog')      # divisor≠0 → reprogram PIT
    a.jmp_near('exit')          # divisor=0 → speed 1.0, nothing to do
    a.label('pit_do_reprog')

    # Reprogram PIT channel 0
    a.push('ax')
    a.mov_r8_imm('al', 0x36)    # channel 0, lobyte/hibyte, mode 3
    a.db(0xE6, 0x43)            # out 0x43, al
    a.pop('ax')
    a.db(0xE6, 0x40)            # out 0x40, al  (lo byte of divisor)
    a.mov_rr8('al', 'ah')
    a.db(0xE6, 0x40)            # out 0x40, al  (hi byte of divisor)
    a.jmp_near('exit')

    # -- TSR path: install music ISR --
    a.label('tsr_init')

    # Reset MPU-401
    a.mov_r16_imm('dx', 0x0331)
    a.mov_r8_imm('al', 0xFF)
    a.db(0xEE)                   # out dx, al
    a.mov_r16_imm('cx', 0x2000)
    a.label('mpu_d1')
    a.loop('mpu_d1')
    a.mov_r16_imm('dx', 0x0330)
    a.db(0xEC)                   # in al, dx

    # Enter UART mode
    a.mov_r16_imm('dx', 0x0331)
    a.mov_r8_imm('al', 0x3F)
    a.db(0xEE)
    a.mov_r16_imm('cx', 0x2000)
    a.label('mpu_d2')
    a.loop('mpu_d2')
    a.mov_r16_imm('dx', 0x0330)
    a.db(0xEC)

    # Hook INT 08h
    a.mov_r16_imm('ax', 0x3508)
    a.int21()
    a.db(0x89, 0x1E); a._fixup('abs16', 'old_08_off'); a._word(0)  # MOV [old_08_off], BX
    a.db(0x8C, 0x06); a._fixup('abs16', 'old_08_seg'); a._word(0)  # MOV [old_08_seg], ES

    a.mov_r16_imm('ax', 0x2508)
    a.mov_r16_label('dx', 'isr')
    a.int21()

    # Publish real BIOS INT 08 at IVT[0x68] (linear 01A0h) for satellite COM chain
    a.xor_r16('ax')
    a.db(0x8E, 0xC0)            # MOV ES, AX
    a.mov_ax_mem('old_08_off')
    a.db(0x26, 0xA3, 0xA0, 0x01)  # MOV ES:[01A0h], AX
    a.mov_ax_mem('old_08_seg')
    a.db(0x26, 0xA3, 0xA2, 0x01)  # MOV ES:[01A2h], AX

    # Hook INT 21h (FIGHT/CONTEST → satellite .COM; AH=4Dh → MAIN)
    a.mov_r16_imm('ax', 0x3521)
    a.int21()
    a.db(0x89, 0x1E); a._fixup('abs16', 'old_21_off'); a._word(0)
    a.db(0x8C, 0x06); a._fixup('abs16', 'old_21_seg'); a._word(0)
    a.mov_r16_imm('ax', 0x2521)
    a.mov_r16_label('dx', 'dos_isr')
    a.int21()

    # Reprogram PIT if game_speed != 1.0
    a.mov_ax_mem('pit_divisor_val')
    a.db(0x85, 0xC0)            # test ax, ax
    a.je('tsr_no_pit')

    a.push('ax')
    a.mov_r8_imm('al', 0x36)
    a.db(0xE6, 0x43)            # out 0x43, al
    a.pop('ax')
    a.db(0xE6, 0x40)            # out 0x40, al  (lo)
    a.mov_rr8('al', 'ah')
    a.db(0xE6, 0x40)            # out 0x40, al  (hi)

    a.label('tsr_no_pit')

    # Init music playback state
    a.mov_r16_label('si', 'event_data')
    a.db(0xAD)                   # lodsw — first wait value
    a.mov_mem_ax('wait_ctr')
    a.db(0x89, 0x36); a._fixup('abs16', 'data_ptr'); a._word(0)   # MOV [data_ptr], SI

    # Go TSR — keep everything up to end_resident
    end_addr = a.labels['end_resident']
    tsr_paras = (end_addr + 0x0F) >> 4
    a.mov_r16_imm('dx', tsr_paras)
    a.mov_r16_imm('ax', 0x3100)
    a.int21()

    # -- Normal exit --
    a.label('exit')
    a.mov_r16_imm('ax', 0x4C00)
    a.int21()

    # =================================================================
    #  Subroutines (non-resident)
    # =================================================================

    # search: SI = null-terminated string → AL = 1 if found in read_buffer
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

    # apply_patch: AL=flag CX:DX=offset SI=on DI=off BL=size
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

    # =================================================================
    #  Data (non-resident)
    # =================================================================

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
    a.label('str_vsync_off'); a.db("vsync=0\x00")
    a.label('str_fast_mp'); a.db("fast_mp=1\x00")
    a.label('str_cheap_supers');a.db("cheap_supers=1\x00")
    a.label('str_easy_supers');a.db("easy_supers=1\x00")
    a.label('str_bgm');      a.db("bgm=1\x00")
    a.label('str_game_speed'); a.db("game_speed=\x00")
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
    a.label('jng_byte');     a.db(0x7E)
    a.label('jnl_byte');     a.db(0x7D)
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
    a.label('flag_vsync_off'); a.db(0)
    a.label('flag_fast_mp'); a.db(0)
    a.label('flag_cheap_supers'); a.db(0)
    a.label('flag_easy_supers'); a.db(0)
    a.label('flag_bgm');     a.db(0)
    a.label('rate_value');   a.dw(0x012C)
    a.label('cur_handle');   a.dw(0)
    a.label('bytes_read');   a.dw(0)
    a.label('pit_divisor_val'); a.dw(0)
    a.label('value_x10_var');  a.dw(182)

    # cheap_supers: IMUL BX,SI,0x34 + SHR AX,1
    a.label('cheap_cost_on');   a.db(0x50, 0x6B, 0xDE, 0x34, 0x58, 0xD1, 0xE8, 0x90, 0x90, 0x90, 0x90)
    a.label('cheap_cost_off');  a.db(0x50, 0x8B, 0xC6, 0xBA, 0x34, 0x00, 0xF7, 0xEA, 0x8B, 0xD8, 0x58)
    a.label('cheap_cost_on_di');a.db(0x50, 0x6B, 0xDF, 0x34, 0x58, 0xD1, 0xE8, 0x90, 0x90, 0x90, 0x90)
    a.label('cheap_cost_off_di');a.db(0x50, 0x8B, 0xC7, 0xBA, 0x34, 0x00, 0xF7, 0xEA, 0x8B, 0xD8, 0x58)
    a.label('sub_mp_12');       a.db(0x83, 0xAF, 0x20, 0x34, 0x0C)

    a.label('fast_mp_on');     a.db(0x8B, 0xC6, 0xB2, 0x34, 0xF7, 0xEA, 0x8B, 0xD8, 0x83, 0x87, 0x20, 0x34, 0x02)
    a.label('fast_mp_off');   a.db(0x8B, 0xC6, 0xBA, 0x34, 0x00, 0xF7, 0xEA, 0x8B, 0xD8, 0xFF, 0x87, 0x20, 0x34)
    a.label('retf_byte');     a.db(0xCB)
    a.label('jmp_short_byte');a.db(0xEB)

    # easy_supers: per-handler 86-byte patches
    # Do NOT gate on entity index (SI): SI is which fighter slot in the match (can be 4+
    # for "character 5" etc.). Which *controls* apply is [bx+0x3404] (P1/P2/P3 slot).
    easy_super_prefix = [
         0x55,
         0x8B, 0xEC,
         0x56,
         0x57,
         0x8B, 0x76, 0x06,
         0x8B, 0x7E, 0x08,
         0x90, 0x90, 0x90, 0x90, 0x90,  # was: cmp si,3 / jge skip (wrong for 4+ fighters)
         0xEB, 0x04,
         0x00, 0x00,
         0x00, 0x00,
         0x8B, 0xC6,
         0xBA, 0x34, 0x00,
         0xF7, 0xEA,
         0x8B, 0xD8,
         0x8A, 0x87, 0x04, 0x34,
         0xB3, 0x03,
         0xF6, 0xE3,
         0x03, 0xC7,
         0xE8, 0x00, 0x00,
         0x5B,
         0x83, 0xC3, 0x21,
         0x2E, 0xD7,
         0x30, 0xE4,
         0x8B, 0xD8,
         0xD1, 0xE3,
         0x83, 0xBF, 0x6E, 0x2E, 0x00,
         0x74, 0x0A,
         0x57,
         0x56,
         0x0E,
    ]
    easy_super_suffix = [
         0x90, 0x90,
         0x59,
         0x59,
         0x5F,
         0x5E,
         0x5D,
         0xCB,
         0x10, 0x12, 0x2C,
         0x16, 0x18, 0x32,
         0x47, 0x49, 0x4F,
    ]
    for suffix, file_off in [('A',0x9868),('B',0x9924),('C',0x99E0),
                              ('D',0x9A9C),('E',0x9B38)]:
        code_off = file_off - 0x1400
        disp = (0x7958 - (code_off + 69)) & 0xFFFF
        a.label(f'easy_super_{suffix}')
        a.db(*easy_super_prefix)
        a.db(0xE8, disp & 0xFF, (disp >> 8) & 0xFF)
        a.db(*easy_super_suffix)

    # Handler H: 139 bytes
    code_off_H = 0x9C14 - 0x1400
    disp_H = (0x7958 - (code_off_H + 108)) & 0xFFFF
    easy_super_H = [
         0x55,
         0x8B, 0xEC,
         0x56,
         0x57,
         0x8B, 0x76, 0x06,
         0x8B, 0x7E, 0x08,
         0x90, 0x90, 0x90, 0x90, 0x90,  # was: cmp si,3 / jge skip
         0xEB, 0x04,
         0x00, 0x00,
         0x00, 0x00,
         0x8B, 0xC6,
         0xBA, 0x34, 0x00,
         0xF7, 0xEA,
         0x8B, 0xD8,
         0x8A, 0x87, 0x04, 0x34,
         0xB3, 0x03,
         0xF6, 0xE3,
         0x03, 0xC7,
         0xE8, 0x00, 0x00,
         0x5B,
         0x83, 0xC3, 0x56,
         0x2E, 0xD7,
         0x30, 0xE4,
         0x8B, 0xD8,
         0xD1, 0xE3,
         0x83, 0xBF, 0x6E, 0x2E, 0x00,
         0x74, 0x31,
         0x8B, 0xC6,
         0xBA, 0x34, 0x00,
         0xF7, 0xEA,
         0x8B, 0xD8,
         0x8B, 0x87, 0x14, 0x34,
         0x53,
         0xBB, 0x32, 0x00,
         0x99,
         0xF7, 0xFB,
         0x5B,
         0x3D, 0x05, 0x00,
         0x74, 0x0D,
         0x83, 0xAF, 0x20, 0x34, 0x32,
         0xC7, 0x87, 0x14, 0x34, 0x10, 0x0E,
         0xEB, 0x0A,
         0x57,
         0x56,
         0x0E,
         0xE8, disp_H & 0xFF, (disp_H >> 8) & 0xFF,
         0x90, 0x90,
         0x59,
         0x59,
         0x5F,
         0x5E,
         0x5D,
         0xCB,
         0x90, 0x90, 0x90, 0x90, 0x90, 0x90, 0x90,
         0x90, 0x90, 0x90, 0x90, 0x90, 0x90, 0x90,
         0x10, 0x12, 0x2C,
         0x16, 0x18, 0x32,
         0x47, 0x49, 0x4F,
    ]
    a.label('easy_super_H')
    a.db(*easy_super_H)

    # Original combo handler bytes (for restoration)
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

    # easy_run: ISR hook
    a.label('easy_run_hook')
    a.db(0xE9, 0x05, 0x28)
    a.label('easy_run_hook_orig')
    a.db(0x5D, 0x5F, 0x5E)

    # easy_run: 133-byte code cave
    a.label('easy_run_cave')
    a.db(
         0x5D,
         0x5F,
         0x5E,
         0xA1, 0x6C, 0x2E,
         0x3C, 0x2E,
         0x74, 0x20,
         0x3C, 0x34,
         0x74, 0x22,
         0x3C, 0x51,
         0x74, 0x24,
         0x3C, 0x1E,
         0x74, 0x5D,
         0x3C, 0x20,
         0x74, 0x59,
         0x3C, 0x24,
         0x74, 0x55,
         0x3C, 0x26,
         0x74, 0x51,
         0x3C, 0x4B,
         0x74, 0x4D,
         0x3C, 0x4D,
         0x75, 0x58,
         0xB3, 0x20,
         0xB2, 0x00,
         0xEB, 0x0A,
         0xB3, 0x26,
         0xB2, 0x01,
         0xEB, 0x04,
         0xB3, 0x4D,
         0xB2, 0x02,
         0x8A, 0xCB,
         0x80, 0xE9, 0x02,
         0x30, 0xFF,
         0x53,
         0xD1, 0xE3,
         0x83, 0xBF, 0x6E, 0x2E, 0x00,
         0x5B,
         0x75, 0x14,
         0x3A, 0xD9,
         0x74, 0x04,
         0x8A, 0xD9,
         0xEB, 0xED,
         0x30, 0xF6,
         0x8B, 0xDA,
         0x8A, 0x9F, 0x30, 0x2F,
         0x08, 0xDB,
         0x74, 0x22,
         0x8A, 0xD3,
         0x8A, 0xF2,
         0x31, 0xDB,
         0x8A, 0x1E, 0x98, 0x00,
         0x89, 0x97, 0xF6, 0x2D,
         0x80, 0x06, 0x98, 0x00, 0x02,
         0xBB, 0x30, 0x2F,
         0x3C, 0x22,
         0x72, 0x06,
         0x43,
         0x3C, 0x40,
         0x72, 0x01,
         0x43,
         0x88, 0x07,
         0xE9, 0x76, 0xD7,
    )

    # easy_run cave: original 133 bytes (for revert)
    a.label('easy_run_cave_orig')
    a.db(0x8B, 0xC6, 0xBA, 0x05, 0x00, 0xF7, 0xEA, 0x8B,
         0xD8, 0x80, 0xBF, 0x2C, 0x4D, 0x78, 0x75, 0x18,
         0x8B, 0xC6, 0xBA, 0x05, 0x00, 0xF7, 0xEA, 0x8B,
         0xD8, 0x80, 0xBF, 0x2B, 0x4D, 0x77, 0x75, 0x08,
         0x57, 0x56, 0x0E, 0xE8, 0xA4, 0xF1, 0x59, 0x59,
         0xEB, 0x58, 0x8B, 0xC6, 0xBA, 0x05, 0x00, 0xF7,
         0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2F, 0x4D, 0x73,
         0x75, 0x48, 0x8B, 0xC6, 0xBA, 0x05, 0x00, 0xF7,
         0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2E, 0x4D, 0x61,
         0x75, 0x38, 0x8B, 0xC6, 0xBA, 0x05, 0x00, 0xF7,
         0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2D, 0x4D, 0x64,
         0x75, 0x28, 0x8B, 0xC6, 0xBA, 0x05, 0x00, 0xF7,
         0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2C, 0x4D, 0x78,
         0x75, 0x18, 0x8B, 0xC6, 0xBA, 0x05, 0x00, 0xF7,
         0xEA, 0x8B, 0xD8, 0x80, 0xBF, 0x2B, 0x4D, 0x77,
         0x75, 0x08, 0x57, 0x56, 0x0E, 0xE8, 0x4A, 0xF1,
         0x59, 0x59, 0x5F, 0x5E, 0x5D)

    a.label('read_buffer')

    a.resolve()
    isr_to_old08 = a.labels['isr'] - a.labels['old_08_off']
    return bytes(a.buf), isr_to_old08


def build_music_slave_com(cooked_track, mods_isr_to_old08):
    """Single-track BGM TSR. Chains timer using BIOS vector from prior INT 08 handler image."""
    a = Asm16()

    a.mov_r16_label('bx', 'slave_init')
    a.db(0xFF, 0xE3)

    a.label('old_08_off');   a.dw(0)
    a.label('old_08_seg');   a.dw(0)
    a.label('data_ptr');     a.dw(0)
    a.label('wait_ctr');     a.dw(1)
    a.label('chain_acc');    a.dw(0)
    a.label('chain_step');   a.dw(182)
    a.label('chain_thresh'); a.dw(728)
    a.label('muted');        a.db(0)
    a.label('prev_scan');    a.db(0)
    a.dw(0xB602)              # satellite tag (paired with MODS 0xB601 for chain discovery)

    a.label('isr')
    a.push('ax');  a.push('cx');  a.push('dx');  a.push('si')
    a.db(0x1E)
    a.db(0x0E, 0x1F)

    a.mov_ax_mem('chain_acc')
    a.db(0x03, 0x06); a._fixup('abs16', 'chain_step'); a._word(0)
    a.db(0x3B, 0x06); a._fixup('abs16', 'chain_thresh'); a._word(0)
    a.jb('sl_isr_no_chain')

    a.db(0x2B, 0x06); a._fixup('abs16', 'chain_thresh'); a._word(0)
    a.mov_mem_ax('chain_acc')
    a.db(0x9C)
    a.db(0xFF, 0x1E)
    a._fixup('abs16', 'old_08_off'); a._word(0)
    a.db(0xFA)                   # cli — same as MODS isr (no nested IRQ0 during MIDI)

    a.db(0xE4, 0x60)
    a.db(0x3A, 0x06); a._fixup('abs16', 'prev_scan'); a._word(0)
    a.je('sl_isr_midi')
    a.db(0xA2); a._fixup('abs16', 'prev_scan'); a._word(0)
    a.cmp_al_imm(0x57)
    a.jne('sl_isr_midi')
    a.db(0x80, 0x36); a._fixup('abs16', 'muted'); a._word(0)
    a.db(0x01)
    a.db(0x80, 0x3E); a._fixup('abs16', 'muted'); a._word(0)
    a.db(0x00)
    a.je('sl_isr_midi')
    a.push('bx');  a.push('cx')
    a.mov_r16_imm('cx', 16)
    a.xor_r8('bl')
    a.label('sl_isr_mute_anoff')
    a.mov_r8_imm('al', 0xB0)
    a.db(0x08, 0xD8)
    a.mov_r16_imm('dx', 0x0330)
    a.db(0xEE)
    a.mov_r8_imm('al', 0x7B)
    a.db(0xEE)
    a.xor_r8('al')
    a.db(0xEE)
    a.db(0xFE, 0xC3)
    a.loop('sl_isr_mute_anoff')
    a.pop('cx');  a.pop('bx')
    a.jmp('sl_isr_midi')

    a.label('sl_isr_no_chain')
    a.mov_mem_ax('chain_acc')
    a.mov_r8_imm('al', 0x20)
    a.db(0xE6, 0x20)

    a.label('sl_isr_midi')
    a.db(0x80, 0x3E); a._fixup('abs16', 'muted'); a._word(0)
    a.db(0x00)
    a.jne('sl_isr_done')
    a.cld()
    a.db(0xFF, 0x0E); a._fixup('abs16', 'wait_ctr'); a._word(0)
    a.jnz('sl_isr_done')

    a.db(0x8B, 0x36); a._fixup('abs16', 'data_ptr'); a._word(0)

    a.label('sl_isr_frame')
    a.lodsb()
    a.xor_r8('ch')
    a.mov_rr8('cl', 'al')
    a.jcxz('sl_isr_next_wait')

    a.mov_r16_imm('dx', 0x0330)
    a.label('sl_isr_send')
    a.lodsb()
    a.db(0xEE)
    a.loop('sl_isr_send')

    a.label('sl_isr_next_wait')
    a.db(0xAD)
    a.cmp_ax_imm(0xFFFF)
    a.je('sl_isr_loop')
    a.db(0x85, 0xC0)
    a.je('sl_isr_frame')

    a.mov_mem_ax('wait_ctr')
    a.db(0x89, 0x36); a._fixup('abs16', 'data_ptr'); a._word(0)

    a.label('sl_isr_done')
    a.db(0x1F)
    a.pop('si');  a.pop('dx');  a.pop('cx');  a.pop('ax')
    a.db(0xCF)

    a.label('sl_isr_loop')
    a.mov_r16_imm('cx', 16)
    a.xor_r8('bl')
    a.label('sl_isr_anoff')
    a.mov_r8_imm('al', 0xB0)
    a.db(0x08, 0xD8)
    a.mov_r16_imm('dx', 0x0330)
    a.db(0xEE)
    a.mov_r8_imm('al', 0x7B)
    a.db(0xEE)
    a.xor_r8('al')
    a.db(0xEE)
    a.db(0xFE, 0xC3)
    a.loop('sl_isr_anoff')

    a.mov_r16_label('si', 'event_data')
    a.db(0xAD)
    a.db(0x85, 0xC0)
    a.je('sl_isr_frame')
    a.mov_mem_ax('wait_ctr')
    a.db(0x89, 0x36); a._fixup('abs16', 'data_ptr'); a._word(0)
    a.jmp('sl_isr_done')

    a.label('event_data')
    a.db(cooked_track)
    a.label('end_resident')

    a.label('slave_init')
    a.cld()
    a.db(0x0E, 0x1F)

    # Resolve real BIOS INT 08 target from current handler (MODS or prior slave).
    # IVT[0x68] alone is unsafe — CONTEST / other code may repurpose int 68h.
    a.mov_r8_imm('ah', 0x35)
    a.mov_r8_imm('al', 0x08)
    a.int21()
    a.push('bx')
    a.db(0x26, 0x8B, 0x47, 0xFE)  # MOV AX, ES:[BX-2]  (tag before isr entry)
    a.cmp_ax_imm(0xB601)
    a.je('sl_ivt_mods')
    a.cmp_ax_imm(0xB602)
    a.je('sl_ivt_slave')
    a.pop('bx')
    a.xor_r16('ax')
    a.db(0x8E, 0xC0)
    a.db(0x26, 0xA1, 0xA0, 0x01)
    a.mov_mem_ax('old_08_off')
    a.db(0x26, 0xA1, 0xA2, 0x01)
    a.mov_mem_ax('old_08_seg')
    a.jmp('sl_ivt_done')
    a.label('sl_ivt_mods')
    a.pop('bx')
    a.mov_rr16('si', 'bx')
    a.db(0x81, 0xEE)
    a.dw(mods_isr_to_old08 & 0xFFFF)
    a.db(0x26, 0x8B, 0x04)       # MOV AX, ES:[SI]  -> old_08_off in prior handler image
    a.mov_mem_ax('old_08_off')
    a.db(0x26, 0x8B, 0x44, 0x02)  # MOV AX, ES:[SI+2]
    a.mov_mem_ax('old_08_seg')
    a.db(0x26, 0x8B, 0x44, 0x0A)  # MOV AX, ES:[SI+10]  chain_step (match MODS / prior slave)
    a.mov_mem_ax('chain_step')
    a.db(0x26, 0x8B, 0x44, 0x0C)  # MOV AX, ES:[SI+12]  chain_thresh
    a.mov_mem_ax('chain_thresh')
    a.jmp('sl_ivt_done')
    a.label('sl_ivt_slave')
    a.pop('bx')
    a.mov_rr16('si', 'bx')
    slave_isr_to_old08 = a.labels['isr'] - a.labels['old_08_off']
    a.db(0x81, 0xEE)
    a.dw(slave_isr_to_old08 & 0xFFFF)
    a.db(0x26, 0x8B, 0x04)
    a.mov_mem_ax('old_08_off')
    a.db(0x26, 0x8B, 0x44, 0x02)
    a.mov_mem_ax('old_08_seg')
    a.db(0x26, 0x8B, 0x44, 0x0A)
    a.mov_mem_ax('chain_step')
    a.db(0x26, 0x8B, 0x44, 0x0C)
    a.mov_mem_ax('chain_thresh')
    a.label('sl_ivt_done')

    # No MPU 0xFF / UART re-init — MODS already put MPU-401 in UART mode at TSR install.
    # Re-running reset (old slave_init) clears GM state → piano until PCs arrive; the
    # embedded FUSION path only switched data_ptr and kept the same hardware state.

    a.mov_r16_imm('ax', 0x2508)
    a.mov_r16_label('dx', 'isr')
    a.int21()

    a.mov_r16_label('si', 'event_data')
    a.db(0xAD)
    a.mov_mem_ax('wait_ctr')
    a.db(0x89, 0x36); a._fixup('abs16', 'data_ptr'); a._word(0)

    end_addr = a.labels['end_resident']
    tsr_paras = (end_addr + 0x0F) >> 4
    a.mov_r16_imm('dx', tsr_paras)
    a.mov_r16_imm('ax', 0x3100)
    a.int21()

    a.mov_r16_imm('ax', 0x4C00)
    a.int21()

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
    silent = struct.pack('<HBH', 1, 0, 0xFFFF)

    midi_path = os.path.join(GAME_DIR, "SYS", "MAIN.mid")
    fusion_path = os.path.join(GAME_DIR, "SYS", "FUSION.mid")
    transformed_path = os.path.join(GAME_DIR, "SYS", "TRANSFORMED.MID")

    if os.path.exists(midi_path):
        print("Parsing MAIN.mid...")
        events, div = parse_midi(midi_path)
        midi_count = sum(1 for _, k, _ in events if k == 'M')
        tempo_count = sum(1 for _, k, _ in events if k == 'T')
        print(f"  {midi_count} MIDI events, {tempo_count} tempo changes, division={div}")
        print(f"Cooking MAIN (target rate: {COOK_HZ:.1f} Hz)...")
        cooked_main = cook_events(events, div, target_hz=COOK_HZ)
        print(f"  Cooked MAIN: {len(cooked_main)} bytes")
    else:
        print("  SYS/MAIN.mid not found — BGM will be silent")
        cooked_main = silent

    if os.path.exists(fusion_path):
        print("Parsing FUSION.mid...")
        fev, fdiv = parse_midi(fusion_path)
        print(f"Cooking FUSION (target rate: {COOK_HZ:.1f} Hz)...")
        cooked_fusion = cook_events(fev, fdiv, target_hz=COOK_HZ)
        print(f"  Cooked FUSION: {len(cooked_fusion)} bytes")
    else:
        print("  SYS/FUSION.mid not found — embedded fight slot uses silent stub (not a second MAIN copy)")
        cooked_fusion = silent

    if os.path.exists(transformed_path):
        print("Parsing TRANSFORMED.MID...")
        tev, tdiv = parse_midi(transformed_path)
        print(f"Cooking TRANSFORMED (target rate: {COOK_HZ:.1f} Hz)...")
        cooked_transform = cook_events(tev, tdiv, target_hz=COOK_HZ)
        print(f"  Cooked TRANSFORMED: {len(cooked_transform)} bytes")
    else:
        print("  SYS/TRANSFORMED.MID not found — contest music falls back to MAIN")
        cooked_transform = cooked_main

    com_limit = 65280

    print("Building MODS.COM (MAIN + embedded FUSION + router)...")
    mods_bin, mods_isr_to_old08 = build_mods_com(cooked_main, cooked_fusion)
    if len(mods_bin) > com_limit:
        print(f"  ERROR: MODS.COM too large ({len(mods_bin)} bytes, limit ~{com_limit})")
        sys.exit(1)
    mods_path = os.path.join(GAME_DIR, "MODS.COM")
    open(mods_path, "wb").write(mods_bin)
    print(f"  Written {len(mods_bin)} bytes to MODS.COM")

    print("Building SYS/FIGHTBGM.COM (legacy satellite — not used by MODS router)...")
    fight_bin = build_music_slave_com(cooked_fusion, mods_isr_to_old08)
    if len(fight_bin) > com_limit:
        print(f"  ERROR: FIGHTBGM.COM too large ({len(fight_bin)} bytes)")
        sys.exit(1)
    fight_path = os.path.join(GAME_DIR, "SYS", "FIGHTBGM.COM")
    open(fight_path, "wb").write(fight_bin)
    print(f"  Written {len(fight_bin)} bytes to SYS/FIGHTBGM.COM")

    print("Building SYS/TRANSFORM.COM (TRANSFORMED)...")
    tr_bin = build_music_slave_com(cooked_transform, mods_isr_to_old08)
    if len(tr_bin) > com_limit:
        print(f"  ERROR: TRANSFORM.COM too large ({len(tr_bin)} bytes)")
        sys.exit(1)
    tr_path = os.path.join(GAME_DIR, "SYS", "TRANSFORM.COM")
    open(tr_path, "wb").write(tr_bin)
    print(f"  Written {len(tr_bin)} bytes to SYS/TRANSFORM.COM")

    print("Patching PLAY.COM...")
    if patch_play_com():
        print("  Done")
    else:
        print("  FAILED — see above")
        sys.exit(1)

    print("\nAll done. Users just edit mods.cfg and launch the game.")
