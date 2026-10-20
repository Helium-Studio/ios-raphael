#!/usr/bin/env python3
"""Host-check actual keys board matching and SPMI APID selection: XNU_TREE argument."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

source = (Path(sys.argv[1]) / 'bsd/dev/sweet_keys.c').read_text()
start = source.index('static int\nkeys_board(')
board = source[start:source.index('\nstatic uint32_t\nkeys_rd', start)]
start = source.index('static uint16_t\nkeys_find_apid(')
apid = source[start:source.index('\nstatic bool\nkeys_read', start)]
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#define kSuccess 0
#define KEYS_NO_APID 0xffffu
typedef int DTEntry;
static const char *compat; static unsigned length; static int missing;
static int SecureDTLookupEntry(void *a, const char *b, DTEntry *r) { (void)a; (void)b; *r=0; return missing; }
static int SecureDTGetProperty(DTEntry r, const char *k, const void **p, unsigned *n) { (void)r; (void)k; *p=compat; *n=length; return 0; }
static uintptr_t keys_core=1, keys_cnfg=2;
static uint32_t maps[512], owners[512];
static uint32_t keys_rd(uintptr_t base, uint32_t off) { return base==keys_core ? maps[(off-0x900)/4] : owners[(off-0x700)/4]; }
''' + board + apid + r'''
int main(void) {
    compat="D22AP\0iPhone10,3\0xiaomi,raphael"; length=32;
    assert(keys_board()==1);
    compat="D22AP\0xiaomi,sweet"; length=19; assert(keys_board()==0);
    compat="xiaomi,raphael-extra"; length=21; assert(keys_board()==-1);
    compat="xiaomi,raphael"; length=14; assert(keys_board()==-1); /* missing terminator */
    missing=1; assert(keys_board()==-1); missing=0;
    assert(keys_find_apid(0x0c5,512)==KEYS_NO_APID);
    maps[3]=0x0c500; owners[3]=4;
    assert(keys_find_apid(0x0c5,512)==3);
    maps[5]=0x4c100; owners[5]=0;
    assert(keys_find_apid(0x0c5,512)==3 && keys_find_apid(0x4c1,512)==5);
    maps[511]=0x0c500; owners[511]=0;
    assert(keys_find_apid(0x0c5,512)==511);
    assert(keys_find_apid(0x0c5,511)==3);
    maps[12]=0x00800; owners[12]=0;
    assert(keys_find_apid(0x008,512)==12);
}
'''
with tempfile.TemporaryDirectory(prefix='raphael-keys-') as tmp:
    c, exe = Path(tmp)/'check.c', Path(tmp)/'check'
    c.write_text(code)
    subprocess.run([os.environ.get('CC','cc'), '-Wall','-Wextra','-Werror',
                    '-fsanitize=address,undefined','-g',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS: actual keys board matcher and APID selector, SID0 vs SID4, ownership and bounds (ASan/UBSan)')
