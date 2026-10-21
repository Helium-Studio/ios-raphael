#!/usr/bin/env python3
"""Exercise the actual A640 probe and CX rollback with modeled MMIO (XNU_TREE)."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

source = (Path(sys.argv[1]) / 'bsd/dev/sweet_gpu.c').read_text()
source = source[source.index('static bool\ngpu_is_raphael'):source.rindex('#endif')]
for barrier in ('dmb oshst', 'dsb osh'):
    source = source.replace(f'__asm__ volatile("{barrier}" ::: "memory");', '')
source = source.replace('*(volatile uint32_t *)(bank + off) = next;', 'model_write(bank, off, next);')
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
#define PZERO 0
#define hz 100
#define __builtin_arm_rsr64(x) 0ULL
static uint32_t gcc[0x100000/4], cc[0xc000/4], gmu[0x34000/4], gpu[0x40000/4], smmu[0x10000/4];
static int enabled, maps, missing, failmap;
static int model, power_fail, clock_fail, off_fail, gmu_failmap, log_secs=1, writes, sleeps, delays;
static const char *compatible;
static unsigned length;
static int PE_parse_boot_argn(const char *k, void *v, int n) {
    assert(n==sizeof(int));
    if(!strcmp(k,"raphaelgpu"))*(int *)v=enabled;
    else {assert(!strcmp(k,"ufslogsecs")); *(int *)v=log_secs;}
    return 1;
}
static void model_write(uintptr_t bank,unsigned off,uint32_t value) {
    assert(model && bank==(uintptr_t)cc);
    uint32_t mask=off==0x106c ? 0xfff007u : off==0x1078 || off==0x1098 || off==0x109c ? 1u : 0u;
    assert(mask && !((cc[off/4]^value)&~mask));
    cc[off/4]=value; ++writes;
}
static int tsleep(void *channel,int priority,const char *name,int ticks) {
    (void)channel; assert(priority==PZERO && !strcmp(name,"gpucxlog") && ticks==3*hz); ++sleeps; return 0;
}
static void delay(unsigned n) {
    (void)n; assert(++delays<10000);
    if(!model)return;
    if(!(cc[0x106c/4]&1) && !power_fail)cc[0x106c/4]|=1u<<31,cc[0x1540/4]|=1u<<31;
    if((cc[0x106c/4]&1) && !off_fail)cc[0x106c/4]&=~(1u<<31),cc[0x1540/4]&=~(1u<<31);
    unsigned offsets[]={0x1078,0x1098,0x109c};
    for(unsigned i=0;i<3;i++) {
        uint32_t *v=&cc[offsets[i]/4];
        if((cc[0x1540/4]&(1u<<31)) && (*v&1) && !clock_fail)*v&=~(1u<<31);
        else *v|=1u<<31;
    }
}
static int SecureDTLookupEntry(void *a,const char *b,DTEntry *r) { (void)a; (void)b; *r=0; return missing; }
static int SecureDTGetProperty(DTEntry r,const char *k,const void **p,unsigned *n) { (void)r; (void)k; *p=compatible; *n=length; return 0; }
static uintptr_t ml_io_map(uintptr_t address,uintptr_t bytes) {
    ++maps;
    if(failmap)return 0;
    switch(address) {
    case 0x100000: assert(bytes==sizeof(gcc)); return (uintptr_t)gcc;
    case 0x2c90000: assert(bytes==sizeof(cc)); return (uintptr_t)cc;
    case 0x2c68000:
        assert(bytes==sizeof(gmu));
        if(model)assert(cc[0x1540/4]&(1u<<31));
        return gmu_failmap ? 0 : (uintptr_t)gmu;
    case 0x2c00000: assert(bytes==sizeof(gpu)); return (uintptr_t)gpu;
    case 0x2ca0000: assert(bytes==sizeof(smmu)); return (uintptr_t)smmu;
    default: assert(0); return 0;
    }
}
''' + source + r'''
static uint32_t saved[sizeof(cc)/4];
static void reset_cx(void) {
    enabled=2; model=1; maps=writes=sleeps=delays=0;
    power_fail=clock_fail=off_fail=gmu_failmap=0; log_secs=1;
    memset(cc,0,sizeof(cc));
    cc[0x106c/4]=cc[0x100c/4]=0x222001;
    cc[0x1540/4]=0x5ff4; cc[0x1010/4]=0x88400; cc[0x1508/4]=0x3c0001;
    cc[0x1078/4]=cc[0x109c/4]=0x80000001; cc[0x1098/4]=0x80004220;
    cc[0x1120/4]=0x80000000;
    memcpy(saved,cc,sizeof(cc));
}
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
    assert(!gpu_clock_live(0xffffffffu) && !gpu_clock_live(0) && !gpu_clock_live(0x80000001) && !gpu_clock_live(0x80000002));
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
    reset_cx(); sweet_gpu_probe();
    assert(maps==3 && writes>0 && sleeps==1 && !memcmp(saved,cc,sizeof(cc)));
    reset_cx(); power_fail=1; sweet_gpu_probe();
    assert(maps==2 && sleeps==1 && !memcmp(saved,cc,sizeof(cc)));
    reset_cx(); clock_fail=1; sweet_gpu_probe();
    assert(maps==2 && sleeps==1 && !memcmp(saved,cc,sizeof(cc)));
    reset_cx(); gmu_failmap=1; sweet_gpu_probe();
    assert(maps==3 && !memcmp(saved,cc,sizeof(cc)));
    reset_cx(); off_fail=1; sweet_gpu_probe();
    assert(maps==3 && delays>2000 && (cc[0x106c/4]&0xfff007u)==(saved[0x106c/4]&0xfff007u));
    reset_cx(); log_secs=10; sweet_gpu_probe(); assert(writes==0 && sleeps==0);
    reset_cx(); cc[0x106c/4]|=2; sweet_gpu_probe(); assert(writes==0 && sleeps==0);
    reset_cx(); cc[0x1540/4]|=1u<<31; sweet_gpu_probe(); assert(writes==0 && sleeps==0);
    reset_cx(); cc[0x1124/4]=0x602; sweet_gpu_probe(); assert(writes==0 && sleeps==0);
    reset_cx(); cc[0x1540/4]=0xffffffffu; sweet_gpu_probe(); assert(writes==0 && sleeps==0);
    reset_cx(); cc[0x1098/4]=0xffffffffu; sweet_gpu_probe(); assert(writes==0 && sleeps==0);
    reset_cx(); enabled=3; sweet_gpu_probe(); assert(maps==0 && writes==0);
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
print('PASS: actual A640 probe gates, CX success/timeouts/map failure/rollback, no GX or DMA writes (ASan/UBSan)')
