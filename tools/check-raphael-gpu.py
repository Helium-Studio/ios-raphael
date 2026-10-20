#!/usr/bin/env python3
"""Exercise the actual read-only A640 probe with modeled MMIO (XNU_TREE)."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

source = (Path(sys.argv[1]) / 'bsd/dev/sweet_gpu.c').read_text()
source = source[source.index('static bool\ngpu_is_raphael'):source.rindex('#endif')]
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uintptr_t vm_offset_t;
typedef int DTEntry;
#define kSuccess 0
#define PAGE_SIZE 16384
#define __builtin_arm_rsr64(x) 0ULL
static uint32_t gcc[0x100000/4], cc[0xc000/4], gmu[0x34000/4], gpu[0x40000/4], smmu[0x10000/4];
static int enabled, maps, missing, failmap;
static const char *compatible;
static unsigned length;
static int PE_parse_boot_argn(const char *k, void *v, int n) {
    assert(!strcmp(k,"raphaelgpu") && n==sizeof(int)); *(int *)v=enabled; return 1;
}
static int SecureDTLookupEntry(void *a,const char *b,DTEntry *r) { (void)a; (void)b; *r=0; return missing; }
static int SecureDTGetProperty(DTEntry r,const char *k,const void **p,unsigned *n) { (void)r; (void)k; *p=compatible; *n=length; return 0; }
static uintptr_t ml_io_map(uintptr_t address,uintptr_t bytes) {
    ++maps;
    if(failmap)return 0;
    switch(address) {
    case 0x100000: assert(bytes==sizeof(gcc)); return (uintptr_t)gcc;
    case 0x2c90000: assert(bytes==sizeof(cc)); return (uintptr_t)cc;
    case 0x2c68000: assert(bytes==sizeof(gmu)); return (uintptr_t)gmu;
    case 0x2c00000: assert(bytes==sizeof(gpu)); return (uintptr_t)gpu;
    case 0x2ca0000: assert(bytes==sizeof(smmu)); return (uintptr_t)smmu;
    default: assert(0); return 0;
    }
}
''' + source + r'''
int main(void) {
    compatible="D22AP\0xiaomi,raphael"; length=sizeof("D22AP\0xiaomi,raphael");
    sweet_gpu_probe(); assert(maps==0); /* opt-in */
    enabled=1; compatible="xiaomi,sweet"; length=sizeof("xiaomi,sweet");
    sweet_gpu_probe(); assert(maps==0);
    compatible="xiaomi,raphaelX"; length=sizeof("xiaomi,raphaelX");
    sweet_gpu_probe(); assert(maps==0);
    compatible="xiaomi,raphael"; length=sizeof("xiaomi,raphael")-1;
    sweet_gpu_probe(); assert(maps==0); /* no NUL */
    ++length; missing=1; sweet_gpu_probe(); assert(maps==0); missing=0;
    failmap=1; sweet_gpu_probe(); assert(maps==1); failmap=0; maps=0;
    sweet_gpu_probe(); assert(maps==1); /* config clock off: no GPUCC read */
    maps=0; gcc[0x71004/4]=1;
    sweet_gpu_probe(); assert(maps==2); /* CX/GX off: neither GMU nor GPU/SMMU */
    assert(gpu_clock_live(1) && gpu_clock_live(0x80000003));
    assert(!gpu_clock_live(0) && !gpu_clock_live(0x80000001) && !gpu_clock_live(0x80000002));
    cc[0x106c/4]=1u<<31; cc[0x1078/4]=cc[0x1098/4]=cc[0x109c/4]=1;
    maps=0; sweet_gpu_probe(); assert(maps==2); /* request is not CX HW status */
    cc[0x1540/4]=1u<<31;
    maps=0; sweet_gpu_probe(); assert(maps==3); /* CX only */
    cc[0x100c/4]=1u<<31; gcc[0x7100c/4]=gcc[0x71018/4]=1;
    maps=0; sweet_gpu_probe(); assert(maps==4); /* GX request is not completion */
    cc[0x1010/4]=1u<<16; cc[0x1508/4]=1;
    maps=0; sweet_gpu_probe(); assert(maps==4); /* GX I/O still clamped */
    cc[0x1508/4]=0;
    maps=0; sweet_gpu_probe(); assert(maps==5); /* all banks */
    /* MMIO banks must retain their exact values: no writes or DMA setup. */
    for(unsigned i=0;i<sizeof(gcc)/4;i++)assert(gcc[i]==(i==0x71004/4 || i==0x7100c/4 || i==0x71018/4 ? 1u : 0u));
    for(unsigned i=0;i<sizeof(cc)/4;i++)assert(cc[i]==(i==0x106c/4 || i==0x100c/4 || i==0x1540/4 ? 1u<<31 : i==0x1010/4 ? 1u<<16 : i==0x1078/4 || i==0x1098/4 || i==0x109c/4 ? 1u : 0u));
    for(unsigned i=0;i<sizeof(gmu)/4;i++)assert(!gmu[i]);
    for(unsigned i=0;i<sizeof(gpu)/4;i++)assert(!gpu[i]);
    for(unsigned i=0;i<sizeof(smmu)/4;i++)assert(!smmu[i]);
}
'''
with tempfile.TemporaryDirectory(prefix='raphael-gpu-') as tmp:
    c, exe = Path(tmp) / 'check.c', Path(tmp) / 'check'
    c.write_text(code)
    subprocess.run([os.environ.get('CC', 'cc'), '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-g', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, stdout=subprocess.DEVNULL)
print('PASS: actual A640 probe, board/clock/domain gates, map failure and unchanged MMIO (ASan/UBSan)')
