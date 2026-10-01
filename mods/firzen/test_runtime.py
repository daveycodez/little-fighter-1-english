"""Execute the actual DOS hook bytes to validate aliases and Cannon controls."""
from pathlib import Path
import struct,sys,unittest
sys.path.insert(0,str(Path.home()/'.cache/lf1-firzen-tools'))
from unicorn import Uc,UC_ARCH_X86,UC_MODE_16,UC_HOOK_CODE
from unicorn.x86_const import *
from mods.firzen.build_runtime import build_fragment,program_patches

class RuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob,cls.exports=build_fragment(0x100,0x40)
        cls.manifest=program_patches()
    def setUp(self):
        self.u=Uc(UC_ARCH_X86,UC_MODE_16);self.u.mem_map(0,0x200000)
        self.u.mem_write(0x10000+0x100,self.blob)
        self.u.reg_write(UC_X86_REG_DS,0x5463);self.u.reg_write(UC_X86_REG_ES,0x5463)
        self.u.reg_write(UC_X86_REG_SS,0x8000);self.u.reg_write(UC_X86_REG_SP,0xe000)
        self.u.reg_write(UC_X86_REG_EFLAGS,0x202)
        self.set_res('runtime_firzen',b'\1')
        self.set_res('runtime_info',struct.pack('<BBHHHH',1,2,0x3000,0x5463,0x5800,0x1400))
    def set_res(self,name,b):self.u.mem_write(0x10000+self.exports[name],b)
    def word(self,offset,v=None):
        addr=0x54630+offset
        if v is None:return struct.unpack('<H',self.u.mem_read(addr,2))[0]
        self.u.mem_write(addr,struct.pack('<H',v&0xffff))
    def hook(self,file,si=0,bx=0):
        relative=0x15f1 if file>=0x17310 else 0x61d
        cs=0x3000+relative;ip=file+2-0x1400-relative*16
        self.u.reg_write(UC_X86_REG_ESI,si);self.u.reg_write(UC_X86_REG_EBX,bx)
        self.u.reg_write(UC_X86_REG_SP,0xe000)
        self.u.mem_write(0x8e000,struct.pack('<HHH',ip,cs,0x202))
        self.u.reg_write(UC_X86_REG_CS,0x1000)
        stop=self.u.hook_add(UC_HOOK_CODE,lambda u,a,s,d:u.emu_stop() if u.reg_read(UC_X86_REG_CS)==cs else None)
        self.u.emu_start(0x10000+self.exports['runtime_irq65'],0x1ffff,count=20000)
        self.u.hook_del(stop)
        self.assertNotEqual(self.u.reg_read(UC_X86_REG_CS),0x1000,'hook did not return')
    def test_character_boss_alias_never_changes_weapon12(self):
        offset=next(o for o,s,a,l in self.manifest['FIGHT.EXE']['sites'] if s==1 and a==11)
        for klass,kind,match in [(1,11,True),(1,12,True),(1,1,False),(2,12,False),(2,11,True)]:
            self.word(0x33f2,klass);self.word(0x3418,kind);self.hook(offset)
            self.assertEqual(bool(self.u.reg_read(UC_X86_REG_EFLAGS)&0x40),match)
    def test_elemental_collision_and_homing_aliases(self):
        sites=self.manifest['FIGHT.EXE']['sites'];self.word(0x33f2,2)
        for kind,imm in [(29,16),(30,18)]:
            self.word(0x3418,kind);off=next(o for o,s,a,l in sites if s==1 and a==imm);self.hook(off)
            self.assertTrue(self.u.reg_read(UC_X86_REG_EFLAGS)&0x40)
            self.hook(0xa47c);self.assertTrue(self.u.reg_read(UC_X86_REG_EFLAGS)&0x40)
    def test_cannon_cadence_release_and_mana(self):
        self.word(0x33f2,1);self.word(0x3418,12);self.word(0x3414,1100);self.word(0x341c,0)
        self.word(0x3404,1);self.word(0x3420,50);self.word(0x3402,1);self.word(0x33fc,80);self.word(0x33fe,150)
        self.u.mem_write(0x54630+0x146,b'\x1e');self.word(0x2e6e+0x1e*2,1)
        for tick in range(11):self.hook(0x1596f)
        kinds=[self.word(0x3418+i*52) for i in range(8,30) if self.word(0x33f2+i*52)]
        self.assertEqual(kinds,[27,28,28]);self.assertEqual(self.word(0x3420),44)
        self.assertEqual(self.word(0x3410+8*52),0)
        self.assertEqual(self.word(0x33fc+8*52),107)
        self.word(0x2e6e+0x1e*2,0);self.hook(0x1596f)
        self.assertEqual(self.word(0x3414),1)
    def test_disaster_emits_four_alternating_shots(self):
        self.word(0x33f2,1);self.word(0x3418,12);self.word(0x3414,1100);self.word(0x341c,1)
        self.word(0x3402,1);self.word(0x33fc,80);self.word(0x33fe,150)
        for tick in range(29):self.hook(0x1596f)
        kinds=[self.word(0x3418+i*52) for i in range(8,30) if self.word(0x33f2+i*52)]
        self.assertEqual(kinds,[29,30,29,30]);self.assertEqual(self.word(0x3414),1)
        self.assertEqual([self.word(0x33fe+i*52) for i in range(8,12)],[144,156,144,156])
    def test_native_projectile_crop_keeps_all_eight_arguments(self):
        pattern=bytes.fromhex('2e07000098020000a1020000')
        offset=self.blob.index(pattern)+0x100
        self.u.mem_write(0x10000+offset+2,struct.pack('<H',0x4000))
        self.u.mem_write(0x4072e,bytes.fromhex('b867458ec0b8cdabcb'))
        args=(1,15,17,13,4,0x5000,4,0x6000)
        self.u.mem_write(0x8e006,struct.pack('<8H',*args))
        self.word(0x3418+8*52,18)
        captured=[]
        def capture(u,a,size,data):
            if a==0x4072e:
                sp=u.reg_read(UC_X86_REG_SP);ss=u.reg_read(UC_X86_REG_SS)
                captured.append(struct.unpack('<8H',u.mem_read(ss*16+sp+4,16)))
        h=self.u.hook_add(UC_HOOK_CODE,capture)
        self.hook(0x19bdc,si=8)
        self.u.hook_del(h)
        self.assertEqual(captured,[args])
        self.assertEqual(self.u.reg_read(UC_X86_REG_AX),0xabcd)
        self.assertEqual(self.u.reg_read(UC_X86_REG_ES),0x4567)
    def test_native_graphics_allocations_fit_expanded_assets(self):
        patches={p['offset']:bytes.fromhex(p['new']) for p in self.manifest['FIGHT.EXE']['patches']}
        self.assertEqual(struct.unpack('<H',patches[0x1791c])[0],312*156+300)
        self.assertEqual(struct.unpack('<H',patches[0x178f4])[0],216*13+300)
        self.assertEqual(struct.unpack('<H',patches[0x17993])[0],216)
    def test_config_ignores_comments_and_partial_values(self):
        for cfg,want in [(b'# firzen=1\nfirzen=0\n',0),(b'firzen=10\n',0),
                         (b'  firzen=1\n',1),(b'firzen=0\n; firzen=1',0),(b'firzen=1',1)]:
            self.u.mem_write(0x54630+0x100,cfg)
            self.u.mem_write(0x54630+0x300,b'firzen=1\0')
            self.u.reg_write(UC_X86_REG_DI,0x100);self.u.reg_write(UC_X86_REG_SI,0x300)
            self.u.reg_write(UC_X86_REG_CX,len(cfg));self.u.reg_write(UC_X86_REG_CS,0x1000)
            self.u.reg_write(UC_X86_REG_SP,0xe000);self.u.mem_write(0x8e000,struct.pack('<H',0xff00))
            h=self.u.hook_add(UC_HOOK_CODE,lambda u,a,s,d:u.emu_stop() if a==0x1ff00 else None)
            self.u.emu_start(0x10000+self.exports['runtime_cfg_search'],0x1ffff,count=10000)
            self.u.hook_del(h);self.assertEqual(self.u.reg_read(UC_X86_REG_AL),want,cfg)
    def test_character_tables_and_menu_lookups_do_not_overlap(self):
        for regions in [[(0x4000,13*75),(0x4401,2+60*2),(0x4480,13*2),(0x44a0,13*2),(0x44c0,13*2)],
                        [(0x5800,13*75),(0x5bd1,2+60*2),(0x5c60,13*2)]]:
            for (a,size),(b,_) in zip(regions,regions[1:]):self.assertLessEqual(a+size,b)
    def test_legacy_patch_queue_preserves_on_off_bytes_and_file_offsets(self):
        start=self.exports['runtime_queue']-0x100
        instruction=self.blob.index(bytes.fromhex('2e8b3e'),start)
        length_address=struct.unpack_from('<H',self.blob,instruction+3)[0]
        self.set_res('runtime_patch_target',b'\2')
        self.u.mem_write(0x54630+0x300,b'ABC');self.u.mem_write(0x54630+0x400,b'xyz')
        for enabled,offset in [(1,0x15282),(0,0x8df1)]:
            for reg,v in [(UC_X86_REG_AX,enabled),(UC_X86_REG_BX,3),(UC_X86_REG_CX,offset>>16),
                          (UC_X86_REG_DX,offset&0xffff),(UC_X86_REG_SI,0x300),(UC_X86_REG_DI,0x400),
                          (UC_X86_REG_CS,0x1000),(UC_X86_REG_SP,0xe000)]:self.u.reg_write(reg,v)
            self.u.mem_write(0x8e000,struct.pack('<H',0xff00))
            h=self.u.hook_add(UC_HOOK_CODE,lambda u,a,s,d:u.emu_stop() if a==0x1ff00 else None)
            self.u.emu_start(0x10000+self.exports['runtime_queue'],0x1ffff,count=10000);self.u.hook_del(h)
        self.assertEqual(struct.unpack('<H',self.u.mem_read(0x10000+length_address,2))[0],18)
        self.assertEqual(bytes(self.u.mem_read(0x10000+length_address+2,18)),
                         struct.pack('<BBI',2,3,0x15282)+b'ABC'+struct.pack('<BBI',2,3,0x8df1)+b'xyz')
    def test_polar_volcano_freeze_then_fire_and_restore_character(self):
        pattern=bytes.fromhex('d8ca0000e4c000000a2f0000')
        offset=self.blob.index(pattern)+0x100
        for relative in (2,6):self.u.mem_write(0x10000+offset+relative,struct.pack('<H',0x4000))
        self.u.mem_write(0x4cad8,b'\xcb');self.u.mem_write(0x4c0e4,b'\xcb')
        self.word(0x33f2,1);self.word(0x3418,12);self.word(0x3414,2300);self.word(0x341c,2)
        counts=[0,0]
        def native(u,a,size,data):
            if a==0x4cad8:
                self.assertEqual(self.word(0x3414),2800);counts[0]+=1;self.word(0x3414,1)
            if a==0x4c0e4:
                self.assertEqual(self.word(0x3418),6);self.assertEqual(self.word(0x341c),1)
                counts[1]+=1;self.word(0x3414,2300+counts[1] if counts[1]<3 else 1)
        h=self.u.hook_add(UC_HOOK_CODE,native)
        for tick in range(3):
            self.hook(0x1596f)
            self.assertEqual(self.word(0x3418),12);self.assertEqual(self.word(0x341c),2)
        self.u.hook_del(h);self.assertEqual(counts,[1,3]);self.assertEqual(self.word(0x3414),1)
    def test_statistics_has_room_for_twelve_characters(self):
        patches={p['offset']:bytes.fromhex(p['new']) for p in self.manifest['FIGHT.EXE']['patches']}
        self.assertEqual(struct.unpack('<H',patches[0x1c447])[0],156)
        self.assertEqual(struct.unpack('<b',patches[0x1c5bd+2])[0],-0x44)
        self.assertEqual(struct.unpack('<b',patches[0x1c5c9+2])[0],-0x2c)
        regions=[(-156,16),(-140,24),(-116,24),(-92,24),(-68,24),(-44,24),(-20,20)]
        for (a,size),(b,_) in zip(regions,regions[1:]):self.assertEqual(a+size,b)
    def test_loader_recognizes_only_game_executable_names(self):
        entry=self.blob.index(bytes.fromhex('601e062e8c16'))+0x100
        self.u.mem_write(0x10000+0x40,struct.pack('<HH',0x100,0x6666))
        for name,kind in [('SYS\\START.EXE',1),('fight.exe',2),('CONTEST.EXE',3),('STARTBAD.EXE',0),('CONTEST.DAT',0),('FIGHT.COM',0)]:
            self.u.mem_write(0x54630+0x100,name.encode()+b'\0')
            self.u.reg_write(UC_X86_REG_AX,0x4b00);self.u.reg_write(UC_X86_REG_DX,0x100)
            self.u.reg_write(UC_X86_REG_CS,0x1000);self.u.reg_write(UC_X86_REG_SP,0xe000)
            reached=[]
            def stop(u,address,size,data):
                if address==0x10000+entry:reached.append(True);u.emu_stop()
                if address==0x66760:reached.append(False);u.emu_stop()
            h=self.u.hook_add(UC_HOOK_CODE,stop)
            self.u.emu_start(0x10000+self.exports['runtime_dispatch'],0x200000,count=20000);self.u.hook_del(h)
            self.assertEqual(reached,[bool(kind)],name)
            if kind:self.assertEqual(self.u.mem_read(0x10000+self.exports['runtime_info']+1,1)[0],kind)
    def test_tournament_head_and_boss_lookups_include_firzen(self):
        p={p['offset']:bytes.fromhex(p['new']) for p in self.manifest['CONTEST.EXE']['patches']}
        self.assertEqual(p[0x5292+2],struct.pack('<H',0x3400))
        self.assertEqual(p[0x54c8+2],struct.pack('<H',0x3420))
        for offset in (0x6b6b,0x6b8d,0x6be4,0x6c06,0x6c28):self.assertEqual(p[offset],b'\x7c')
    def test_cannon_motion_respects_camera_adjusted_position(self):
        offset=self.blob.index(bytes.fromhex('d8ca0000e4c000000a2f0000'))+0x100
        self.u.mem_write(0x10000+offset+10,struct.pack('<H',0x4000));self.u.mem_write(0x42f0a,b'\xcb')
        slot=8
        self.word(0x33f2+slot*52,2);self.word(0x3418+slot*52,27)
        self.word(0x33fc+slot*52,90);self.word(0x33fe+slot*52,150);self.word(0x3402+slot*52,1)
        self.u.reg_write(UC_X86_REG_BP,0xd000);self.u.mem_write(0x8d006,struct.pack('<H',slot))
        self.hook(0xa3fa)
        self.assertEqual(self.word(0x33fc+slot*52),95)
    def test_menu_has_thirteenth_portrait_and_availability_slots(self):
        p=self.manifest['START.EXE']['patches'];lookup={x['offset']:bytes.fromhex(x['new']) for x in p}
        self.assertEqual(lookup[0x7667+2],struct.pack('<H',0x44a0))
        self.assertEqual(lookup[0x7900+2],struct.pack('<H',0x44c0))

if __name__=='__main__':unittest.main()
