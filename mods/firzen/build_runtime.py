"""Compile the runtime-only LF1 loader and Firzen hooks with NASM."""
from pathlib import Path
import json,struct,subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[2]
try:
    from capstone import Cs,CS_ARCH_X86,CS_MODE_16
    from capstone.x86 import X86_OP_MEM,X86_OP_IMM
except ImportError:
    sys.path.insert(0,str(Path.home()/'.cache/lf1-firzen-tools'))
    from capstone import Cs,CS_ARCH_X86,CS_MODE_16
    from capstone.x86 import X86_OP_MEM,X86_OP_IMM


def program_patches(root=ROOT):
    md=Cs(CS_ARCH_X86,CS_MODE_16);md.detail=True;md.skipdata=True
    result={}
    for name,header,data_seg,old_chars,new_chars,old_colors,new_colors,code_end in [
        ('START.EXE',0xe00,0xf35,0x2d29,0x4000,0x2d04,0x4401,0x10150),
        ('FIGHT.EXE',0x1400,0x2463,0x3cdb,0x5800,0x4675,0x5bd1,0x25a30)]:
        raw=(root/'SYS'/name).read_bytes();patches=[];sites=[];seen=set()
        def add(offset,data,why):
            if offset in seen:raise ValueError(f'Duplicate patch {name}:{offset:x}')
            seen.add(offset);patches.append({'offset':offset,'old':raw[offset:offset+len(data)].hex(),'new':bytes(data).hex(),'reason':why})
        for ins in md.disasm(raw[header:code_end],header):
            if ins.id==0:continue
            for op in ins.operands:
                field=None;value=None
                if op.type==X86_OP_MEM and ins.reg_name(op.mem.segment) not in ('ss','cs','es') and ins.reg_name(op.mem.base) not in ('bp','ebp','esp'):
                    field=ins.disp_offset;value=op.mem.disp
                elif op.type==X86_OP_IMM and ins.mnemonic in ('mov','add','push') and ins.imm_size==2:
                    field=ins.imm_offset;value=op.imm
                if field is None or not field:continue
                new=None
                if name=='START.EXE' and op.type==X86_OP_MEM and op.mem.base and value in (0x137,0x14d,0xea):
                    new={0x137:0x4480,0x14d:0x44a0,0xea:0x44c0}[value]
                elif name=='FIGHT.EXE' and op.type==X86_OP_MEM and op.mem.base and value==0xd8:new=0x5c60
                elif old_chars<=value<=old_chars+149:new=value-old_chars+new_chars
                elif value==old_colors+2:new=value-old_colors+new_colors
                elif value==old_colors and (op.type!=X86_OP_MEM or op.mem.base):new=new_colors
                if new is not None:add(ins.address+field,struct.pack('<H',new),'relocate character/head-color tables')
        if name=='START.EXE':
            for offset in [0x670d,0x6729,0x779b,0x77b2,0x7a4c,0x7a69]:
                assert raw[offset:offset+3]==b'\xbb\x0b\0';add(offset+1,b'\x0c\0','12-column head addressing')
            for offset in [0x6d72,0x75f3]:
                assert raw[offset:offset+6]==b'\xc7\x06\xe8\0\x0b\0';add(offset+4,b'\x0c\0','Julian unlock also unlocks Firzen')
            assert raw[0x64c5:0x64c8]==b'\x83\xfe\x37';add(0x64c7,b'\x3c','60 head colors')
            # Existing boss-selection policy treats both boss IDs alike.
            add(0x9d63,b'\x7c','existing boss: IDs11 and12')
            add(0x9d79,b'\x0c','unlocked character bound12')
            sites.append((0x9dc0,9,0,6));add(0x9dc0,b'\xcd\x65'+b'\x90'*4,'AI boss selection chooses Julian or Firzen')
            sites.append((0x6759,10,0,5));add(0x6759,b'\xcd\x65'+b'\x90'*3,'Firzen menu head sits one pixel higher')
        else:
            for offset in [0x174fd,0x17518,0x17621,0x1763c,0x1940d,0x19428,0x197f7,0x19812]:
                assert raw[offset:offset+3]==b'\xbb\x0b\0';add(offset+1,b'\x0c\0','12-column head addressing')
            assert raw[0x17fd3:0x17fd6]==b'\x83\xfe\x37';add(0x17fd5,b'\x3c','60 head colors')
            assert raw[0x178f3:0x178f6]==bytes.fromhex('bab80b')
            add(0x178f4,struct.pack('<H',216*13+300),'allocate cached head row for12 columns')
            assert raw[0x1791b:0x1791e]==bytes.fromhex('ba9c9f')
            add(0x1791c,struct.pack('<H',312*156+300),'allocate expanded ACT2 without overwriting weapon atlas')
            assert raw[0x17992:0x17995]==bytes.fromhex('b8c600')
            add(0x17993,struct.pack('<H',216),'copy full12-column cached head row')
            # End-of-battle statistics has five character-indexed word arrays
            # and an eight-player sorting array in its stack frame.
            assert raw[0x1c445:0x1c449]==bytes.fromhex('81ec9200')
            add(0x1c447,struct.pack('<H',156),'reserve five12-character statistics arrays')
            bases={-0x2a:-0x2c,-0x40:-0x44,-0x56:-0x5c,-0x6c:-0x74,-0x82:-0x8c,-0x92:-0x9c,-0x90:-0x9a}
            for ins in md.disasm(raw[0x1c442:0x1c70e],0x1c442):
                if not ins.id or ins.mnemonic!='lea':continue
                for operand in ins.operands:
                    if operand.type==X86_OP_MEM and ins.reg_name(operand.mem.base)=='bp' and operand.mem.disp in bases:
                        value=bases[operand.mem.disp]
                        add(ins.address+ins.disp_offset,struct.pack('<b' if ins.disp_size==1 else '<h',value),'expand character statistics stack layout')

            # Type comparisons retain native control flow and flags. The ISR
            # aliases Firzen to Julian only for character/boss logic, and
            # cloned elemental projectiles to their original collision types.
            for offset in range(header,code_end-5):
                if raw[offset:offset+4]==b'\x83\xbf\x18\x34' and raw[offset+4] in [11,16,18,26]:
                    imm=raw[offset+4]
                    if imm==11 and offset in (0x17463,0x19212,0x19705):continue  # Julian-specific artwork, not shared boss behavior
                    sites.append((offset,1,imm,5));add(offset,b'\xcd\x65'+b'\x90'*3,'context-aware native type comparison')
            for offset,svc,length in [(0x1596f,2,5),(0xa3fa,3,3),(0x19bdc,4,5),(0x19c28,5,5)]:
                sites.append((offset,svc,0,length));add(offset,b'\xcd\x65'+b'\x90'*(length-2),'Firzen controller/motion/render hook')
        # Ensure native definitions and opcode patches do not overlap.
        ranges=sorted((p['offset'],p['offset']+len(bytes.fromhex(p['new']))) for p in patches)
        assert all(a[1]<=b[0] for a,b in zip(ranges,ranges[1:])),name
        reloc_count=struct.unpack_from('<H',raw,6)[0];reloc_start=struct.unpack_from('<H',raw,24)[0]
        relocations=[header+s*16+o for o,s in (struct.unpack_from('<HH',raw,reloc_start+4*i) for i in range(reloc_count))]
        result[name]={'header':header,'data_segment':data_seg,'character_table':new_chars,'color_table':new_colors,'patches':patches,'sites':sites,'relocations':relocations}
    raw=(root/'SYS/CONTEST.EXE').read_bytes()
    contest_patches=[]
    def contest_add(offset,data,why):
        contest_patches.append({'offset':offset,'old':raw[offset:offset+len(data)].hex(),'new':bytes(data).hex(),'reason':why})
    for ins in md.disasm(raw[0xc00:0xdc60],0xc00):
        if not ins.id:continue
        for operand in ins.operands:
            if operand.type==X86_OP_MEM and operand.mem.base and operand.mem.disp in (0x94,0xaa):
                contest_add(ins.address+ins.disp_offset,struct.pack('<H',{0x94:0x3400,0xaa:0x3420}[operand.mem.disp]),'13-entry tournament head/portrait lookup')
    for offset in [0x5297,0x52b3]:
        assert raw[offset:offset+3]==bytes.fromhex('bb0b00')
        contest_add(offset+1,b'\x0c\0','12-column tournament heads')
    for offset in [0x6b6b,0x6b8d,0x6be4,0x6c06,0x6c28]:
        assert raw[offset]==0x75
        contest_add(offset,b'\x7c','Firzen shares Julian automatic CPU tournament outcomes')
    result['CONTEST.EXE']={'header':0xc00,'data_segment':0xd06,'character_table':0x3400,'color_table':0,
                           'patches':contest_patches,'sites':[],'relocations':[]}
    return result


def build_fragment(origin,old21,root=ROOT):
    manifest=program_patches(root)
    lines=[f'ORG {origin}',f'%define OLD21 {old21}']
    for name,prefix in [('START.EXE','start'),('FIGHT.EXE','fight'),('CONTEST.EXE','contest')]:
        obj=manifest[name];lines += [f'{prefix}_patches:']
        for p in obj['patches']:
            data=bytes.fromhex(p['new']);lines += [f'dd {p["offset"]}',f'db {len(data)}','db '+','.join(str(b) for b in data)]
        lines += ['dd 0ffffffffh',f'{prefix}_sites:']
        for off,svc,arg,length in obj['sites']:lines += [f'dd {off+2}',f'db {svc},{arg}']
        lines += ['dd 0ffffffffh']
    # Only legacy byte patches may need MZ fixups. List relocation words in
    # the actual gameplay-mod ranges (including easy-super code caves).
    for name,prefix in [('START.EXE','start'),('FIGHT.EXE','fight')]:
        if name=='START.EXE':intervals=[(0x6d70,0x6d72),(0x75f1,0x75f3)]
        else:intervals=[(0x6000,0xa000),(0x14000,0x1b500),(0x22435,0x22436)]
        values=[v for v in manifest[name]['relocations'] if any(a<=v<b for a,b in intervals)]
        lines += [f'{prefix}_legacy_relocs:','dw '+str(len(values))]
        for v in values:lines += ['dd '+str(v)]
    generated='\n'.join(lines[2:])+'\n'
    with tempfile.TemporaryDirectory(prefix='firzen-nasm-') as temporary:
        directory=Path(temporary);inc=directory/'patches.inc';inc.write_text(generated)
        asm=directory/'runtime.asm'
        template=(root/'mods/firzen/runtime.asm').read_text()
        asm.write_text(f'bits 16\norg {origin}\n%define OLD21 {old21}\n%define CANNON_PATH "{root}/SYS/FZCANNON.GRH"\n'+template.replace('%include "patches.inc"',f'%include "{inc}"'))
        output=directory/'runtime.bin';subprocess.run(['nasm','-f','bin',str(asm),'-o',str(output)],check=True)
        blob=output.read_bytes()
    names=['runtime_dispatch','runtime_queue','runtime_firzen','runtime_patch_target','runtime_balanced','runtime_free_supers','runtime_cheap_supers','runtime_easy_supers','runtime_irq65','runtime_info','runtime_cfg_search']
    exports=dict(zip(names,struct.unpack_from('<11H',blob)))
    (root/'build/firzen').mkdir(parents=True,exist_ok=True)
    (root/'build/firzen/patch-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return blob,exports
