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
source = source.replace('return *(const volatile uint32_t *)(bank + off);', 'return model_read(bank + off);')
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "ArmSmmu4K.h"
typedef uintptr_t vm_offset_t;
typedef uint32_t ppnum_t;
typedef int kern_return_t;
typedef int DTEntry;
#define kSuccess 0
#define PAGE_SIZE 16384
#define PAGE_SHIFT 14
#define PAGE_MASK (PAGE_SIZE-1)
#define KERN_SUCCESS 0
#define KMA_DATA 1
#define KMA_ZERO 2
#define VM_KERN_MEMORY_IOKIT 3
#define TRUE 1
#define kernel_map 1
#define kernel_pmap 2
#define ptoa_64(x) ((uint64_t)(x)<<PAGE_SHIFT)
#define PZERO 0
#define hz 100
#define __builtin_arm_rsr64(x) 0ULL
static uint32_t gcc[0x100000/4], cc[0xc000/4], gmu[0x34000/4], gpu[0x40000/4], smmu[0x10000/4];
static int enabled, maps, missing, failmap;
static int model, power_fail, clock_fail, off_fail, gmu_failmap, log_secs=1, writes, sleeps, delays;
static int bus_fail, smmu_failmap, smmu_reads, context_reads;
static int alloc_fail, physical_fail, allocated, cleaned, freed, rcg_fail, xo_fail, tcm_fail, tcm_writes;
static _Alignas(16384) uint8_t arena[32768];
static kern_return_t kmem_alloc_contig(int map,uintptr_t *v,size_t n,uintptr_t mask,ppnum_t max,ppnum_t pmask,int flags,int tag) {
    assert(map==kernel_map && n==sizeof(arena) && mask==PAGE_MASK && max==(((1ull<<40)-1)>>PAGE_SHIFT) && !pmask && flags==(KMA_DATA|KMA_ZERO) && tag==VM_KERN_MEMORY_IOKIT && !allocated);
    if(alloc_fail)return 5;
    *v=(uintptr_t)arena;memset(arena,0,sizeof(arena));allocated=1;return 0;
}
static ppnum_t pmap_find_phys(int pmap,uintptr_t v) {
    assert(pmap==kernel_pmap && allocated && (v==(uintptr_t)arena || v==(uintptr_t)arena+PAGE_SIZE));
    return ((0x104000000ull+(v-(uintptr_t)arena))>>PAGE_SHIFT) ^ ((physical_fail && v!=(uintptr_t)arena) ? 8u : 0u);
}
static void clean_dcache64(uint64_t pa,size_t n,int phys) {
    assert(allocated && pa==0x104000000ull && n==sizeof(arena) && phys==TRUE);
    const uint32_t *payload=(const uint32_t *)(arena+PAGE_SIZE);
    for(unsigned i=0;i<PAGE_SIZE/4;i++)assert(payload[i]==(0x64000000u^i));
    ++cleaned;
}
static void kmem_free(int map,uintptr_t v,size_t n) {
    assert(map==kernel_map && v==(uintptr_t)arena && n==sizeof(arena) && allocated);allocated=0;++freed;
}
static const char *compatible;
static unsigned length;
static int PE_parse_boot_argn(const char *k, void *v, int n) {
    assert(n==sizeof(int));
    if(!strcmp(k,"raphaelgpu"))*(int *)v=enabled;
    else {assert(!strcmp(k,"ufslogsecs")); *(int *)v=log_secs;}
    return 1;
}
static void model_write(uintptr_t bank,unsigned off,uint32_t value) {
    assert(model);
    if(bank==(uintptr_t)gmu+0x2000) {
        assert((off>=0x6fe0 && off<0x7000) || (off>=0xafe0 && off<0xb000));
        assert((cc[0x1540/4]&(1u<<31)) && (cc[0x1124/4]&0x371f)==0x602 && gmu[0x16000/4]==1);
        if(!(tcm_fail && off==0x6fe0 && value==0xa6400000u))gmu[(off+0x2000)/4]=value;
        ++tcm_writes;
    } else {
        assert(bank==(uintptr_t)cc || bank==(uintptr_t)gcc);
        uint32_t *b=(uint32_t *)bank;
        uint32_t mask=bank==(uintptr_t)gcc ? (off==0x52004 ? 1u<<16 : 0) : off==0x106c ? 0xfff007u : off==0x1124 ? 0x371fu : off==0x1120 || off==0x1078 || off==0x1098 || off==0x109c ? 1u : 0u;
        assert(mask && !((b[off/4]^value)&~mask));
        b[off/4]=value;
    }
    ++writes;
}
static uint32_t model_read(uintptr_t address) {
    uint32_t *banks[]={gcc,cc,gmu,gpu,smmu};
    size_t sizes[]={sizeof(gcc),sizeof(cc),sizeof(gmu),sizeof(gpu),sizeof(smmu)};
    assert(!(address&3));
    for(unsigned i=0;i<5;i++) {
        uintptr_t base=(uintptr_t)banks[i];
        if(address>=base && address-base<sizes[i]) {
            if(i==4) {++smmu_reads; if(address-base>=0x800)++context_reads;}
            return *(uint32_t *)address;
        }
    }
    assert(0); return 0;
}
static int tsleep(void *channel,int priority,const char *name,int ticks) {
    (void)channel; assert(priority==PZERO && (!strcmp(name,"gpucxlog") || !strcmp(name,"gpusmmulog") || !strcmp(name,"gmupreplog")) && ticks==3*hz); ++sleeps; return 0;
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
    unsigned buses[]={0x7100c,0x71018};
    for(unsigned i=0;i<2;i++) {
        uint32_t *v=&gcc[buses[i]/4];
        if((cc[0x1540/4]&(1u<<31)) && (*v&1) && !bus_fail)*v&=~(1u<<31);
        else *v|=1u<<31;
    }
    if((cc[0x1120/4]&1) && !((cc[0x1124/4]&0x371f)==0x602 ? rcg_fail : xo_fail))cc[0x1120/4]&=~1u;
    if((cc[0x1540/4]&(1u<<31)) && (cc[0x1098/4]&1) && !clock_fail)cc[0x1120/4]&=~(1u<<31);
    else cc[0x1120/4]|=1u<<31;
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
    case 0x2ca0000:
        assert(bytes==sizeof(smmu));
        if(model)assert((cc[0x1540/4]&(1u<<31)) && !(gcc[0x7100c/4]&(1u<<31)) && !(gcc[0x71018/4]&(1u<<31)));
        return smmu_failmap ? 0 : (uintptr_t)smmu;
    default: assert(0); return 0;
    }
}
''' + source + r'''
static uint32_t saved[sizeof(cc)/4];
static uint32_t saved_smmu[sizeof(smmu)/4];
static void reset_cx(void) {
    enabled=2; model=1; maps=writes=sleeps=delays=0;
    power_fail=clock_fail=off_fail=gmu_failmap=0; log_secs=1;
    bus_fail=smmu_failmap=smmu_reads=context_reads=0;
    alloc_fail=physical_fail=cleaned=freed=rcg_fail=xo_fail=tcm_fail=tcm_writes=0;assert(!allocated);
    gcc[0]=0xd010003d;gcc[4/4]=0x1f;gcc[0x40/4]=0x4000;gcc[0xc/4]=0x103;gcc[0x52004/4]=0x0160597f;
    gcc[0x7100c/4]=0x80000221; gcc[0x71018/4]=0x80000001;
    gmu[0x16000/4]=1; /* GMU remains held in reset throughout. */
    memset(smmu,0,sizeof(smmu));
    smmu[0x20/4]=(1u<<30)|(1u<<27)|128u;
    smmu[0x24/4]=(2u<<28)|8u; smmu[0x28/4]=(1u<<12)|0x55u;
    smmu[0x800/4]=0x84000005; smmu[0xc00/4]=1;
    memcpy(saved_smmu,smmu,sizeof(smmu));
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
    assert(maps==4 && writes>0 && sleeps==3 && context_reads>0 && !memcmp(saved,cc,sizeof(cc)));
    assert(cleaned==1 && freed==1 && tcm_writes==32 && gcc[0x52004/4]==0x0160597f);
    assert(!memcmp(saved_smmu,smmu,sizeof(smmu)));
    assert(gcc[0x7100c/4]==0x80000221 && gcc[0x71018/4]==0x80000001);
    reset_cx(); bus_fail=1; sweet_gpu_probe();
    assert(maps==3 && sleeps==2 && smmu_reads==0 && !memcmp(saved,cc,sizeof(cc)));
    assert(cleaned==0 && freed==0 && tcm_writes==32);
    reset_cx(); smmu_failmap=1; sweet_gpu_probe();
    assert(maps==4 && sleeps==3 && smmu_reads==0 && !memcmp(saved,cc,sizeof(cc)));
    reset_cx(); gmu[0x16000/4]=0; sweet_gpu_probe();
    assert(maps==3 && sleeps==1 && smmu_reads==0 && !memcmp(saved,cc,sizeof(cc)));
    unsigned bad_id1[]={0xffffffffu,0x80000008,0x30000008,0x20000000,0x20000009,0x20090008};
    for(unsigned i=0;i<sizeof(bad_id1)/sizeof(bad_id1[0]);i++) {
        reset_cx(); smmu[0x24/4]=bad_id1[i]; sweet_gpu_probe();
        assert(maps==4 && smmu_reads>0 && context_reads==0 && !memcmp(saved,cc,sizeof(cc)));
    }
    unsigned bad_id0[]={0,0xffffffffu,1u<<30,(1u<<27)|129u};
    for(unsigned i=0;i<sizeof(bad_id0)/sizeof(bad_id0[0]);i++) {
        reset_cx(); smmu[0x20/4]=bad_id0[i]; sweet_gpu_probe();
        assert(smmu_reads>0 && context_reads==0 && !memcmp(saved,cc,sizeof(cc)));
    }
    reset_cx(); smmu[0x28/4]=0xffffffffu; sweet_gpu_probe();
    assert(smmu_reads>0 && context_reads==0 && !memcmp(saved,cc,sizeof(cc)));
    reset_cx(); smmu[0]=8; sweet_gpu_probe(); /* Extended stream IDs use different valid bits. */
    assert(smmu_reads>0 && context_reads==0 && !memcmp(saved,cc,sizeof(cc)));
    reset_cx(); alloc_fail=1; sweet_gpu_probe();
    assert(!allocated && !cleaned && !freed && tcm_writes==32 && !memcmp(saved,cc,sizeof(cc)));
    reset_cx(); physical_fail=1; sweet_gpu_probe();
    assert(!allocated && !cleaned && freed==1 && !memcmp(saved,cc,sizeof(cc)));
    reset_cx(); smmu[0x28/4]=1u<<12; sweet_gpu_probe();
    assert(!allocated && !cleaned && !freed && tcm_writes==32 && !memcmp(saved,cc,sizeof(cc)));
    reset_cx(); rcg_fail=1; sweet_gpu_probe();
    assert(!tcm_writes && cleaned==1 && freed==1 && !memcmp(saved,cc,sizeof(cc)) && gcc[0x52004/4]==0x0160597f);
    reset_cx(); xo_fail=1; sweet_gpu_probe();
    assert(tcm_writes==32 && (cc[0x1120/4]&1) && (cc[0x1124/4]&0x371f)==0 && gcc[0x52004/4]==0x0160597f);
    reset_cx(); tcm_fail=1; sweet_gpu_probe();
    assert(tcm_writes>0 && !memcmp(saved,cc,sizeof(cc)));
    reset_cx(); gcc[4/4]=0x20; sweet_gpu_probe();
    assert(tcm_writes==0 && cleaned==1 && !memcmp(saved,cc,sizeof(cc)));
    reset_cx(); gcc[0x52004/4]|=1u<<16; sweet_gpu_probe();
    assert(tcm_writes==32 && gcc[0x52004/4]==(0x0160597f|1u<<16) && !memcmp(saved,cc,sizeof(cc)));
    reset_cx(); power_fail=1; sweet_gpu_probe();
    assert(maps==2 && sleeps==1 && !memcmp(saved,cc,sizeof(cc)));
    reset_cx(); clock_fail=1; sweet_gpu_probe();
    assert(maps==2 && sleeps==1 && !memcmp(saved,cc,sizeof(cc)));
    reset_cx(); gmu_failmap=1; sweet_gpu_probe();
    assert(maps==3 && !memcmp(saved,cc,sizeof(cc)));
    reset_cx(); off_fail=1; sweet_gpu_probe();
    assert(maps==4 && delays>2000 && (cc[0x106c/4]&0xfff007u)==(saved[0x106c/4]&0xfff007u));
    reset_cx(); log_secs=10; sweet_gpu_probe(); assert(writes==0 && sleeps==0);
    reset_cx(); cc[0x106c/4]|=2; sweet_gpu_probe(); assert(writes==0 && sleeps==0);
    reset_cx(); cc[0x1540/4]|=1u<<31; sweet_gpu_probe(); assert(writes==0 && sleeps==0);
    reset_cx(); cc[0x1124/4]=0x602; sweet_gpu_probe(); assert(writes==0 && sleeps==0);
    reset_cx(); cc[0x1540/4]=0xffffffffu; sweet_gpu_probe(); assert(writes==0 && sleeps==0);
    reset_cx(); cc[0x1098/4]=0xffffffffu; sweet_gpu_probe(); assert(writes==0 && sleeps==0);
    reset_cx(); gcc[0x52004/4]=0xffffffffu; sweet_gpu_probe(); assert(writes==0 && sleeps==0);
    reset_cx(); enabled=3; sweet_gpu_probe(); assert(maps==0 && writes==0);
    for(unsigned i=0;i<sizeof(gmu)/4;i++)assert(gmu[i]==(i==0x16000/4 ? 1u : 0u));
    for(unsigned i=0;i<sizeof(gpu)/4;i++)assert(!gpu[i]);
    assert(!memcmp(saved_smmu,smmu,sizeof(smmu)));
}
'''
with tempfile.TemporaryDirectory(prefix='raphael-gpu-') as tmp:
    c, exe = Path(tmp) / 'check.c', Path(tmp) / 'check'
    c.write_text(code)
    dev = Path(sys.argv[1]) / 'bsd/dev'
    subprocess.run([os.environ.get('CC', 'cc'), '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-g', '-I', str(dev), str(c), str(dev / 'ArmSmmu4K.c'), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, stdout=subprocess.DEVNULL)
print('PASS: A640 gates/rollback, SMMU geometry, owned 16K/4K tables, 200MHz/TCM restore and failure paths; no SMMU/GX/DMA writes (ASan/UBSan)')
