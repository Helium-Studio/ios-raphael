#!/usr/bin/env python3
"""Exercise A640 gates/rollback (XNU_TREE [private a640_gmu.bin]); needs libcrypto headers."""
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
source = source.replace('*(volatile uint64_t *)(bank + off) = value;', 'model_write64(bank, off, value);')
source = source.replace('return *(const volatile uint64_t *)(bank + off);', 'return (uint64_t)model_read(bank + off) | (uint64_t)model_read(bank + off + 4) << 32;')
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <openssl/sha.h>
#include "ArmSmmu4K.h"
#include "ArmSmmu4KContext.h"
#include "AdrenoFirmware.h"
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
static _Alignas(16384) uint8_t fw_arena[0x94000];
static uint8_t *firmware;
static unsigned firmware_bytes, firmware_present, firmware_cleaned, smmu_writes, tlbi_commands, retained;
static uintptr_t allocation;
static size_t allocation_bytes;
static int context_bad_readback, context_bad_route, context_drain_fail, context_detach_fail, fw_tcm_fail;
static int fault_quirk, fault_unsupported, bypass_writes, route_publishes, unmatch_fail;
static kern_return_t kmem_alloc_contig(int map,uintptr_t *v,size_t n,uintptr_t mask,ppnum_t max,ppnum_t pmask,int flags,int tag) {
    assert(map==kernel_map && (n==sizeof(arena) || n==sizeof(fw_arena)) && mask==PAGE_MASK && max==(((1ull<<40)-1)>>PAGE_SHIFT) && !pmask && flags==(KMA_DATA|KMA_ZERO) && tag==VM_KERN_MEMORY_IOKIT && !allocated);
    if(alloc_fail)return 5;
    *v=n==sizeof(arena)?(uintptr_t)arena:(uintptr_t)fw_arena;
    memset((void *)*v,0,n);allocation=*v;allocation_bytes=n;allocated=1;return 0;
}
static ppnum_t pmap_find_phys(int pmap,uintptr_t v) {
    assert(pmap==kernel_pmap && allocated && v>=allocation && v-allocation<allocation_bytes && !((v-allocation)&PAGE_MASK));
    return ((0x104000000ull+v-allocation)>>PAGE_SHIFT) ^ ((physical_fail && v!=allocation) ? 8u : 0u);
}
static void clean_dcache64(uint64_t pa,size_t n,int phys) {
    assert(allocated && pa==0x104000000ull && n==allocation_bytes && phys==TRUE);
    if(n==sizeof(fw_arena)) {
        uint32_t *hfi=(uint32_t *)(fw_arena+0x90000);
        assert(hfi[1]==120 && hfi[4]==2 && hfi[5]==2 && hfi[7]==0x60009000 && hfi[19]==0x6000a000);
        uint64_t *tables=(uint64_t *)fw_arena;
        const uint64_t va[]={0x4000,0x44000,0x60000000,0x60004000,0x60008000};
        const unsigned offsets[]={0x8000,0x44000,0x88000,0x8c000,0x90000}, sizes[]={0x3c000,0x3c000,0x1000,0x4000,0x4000};
        for(unsigned r=0;r<5;r++)for(unsigned off=0;off<sizes[r];off+=4096) {
            uint64_t addr=va[r]+off,at=0,entry=0;
            for(unsigned level=1;level<=3;level++) {
                entry=tables[at*512+((addr>>(39-9*level))&511)];
                assert((entry&3)==3);uint64_t p=entry&0x0000fffffffff000ull;
                if(level<3) {assert(p>=pa && p-pa<5*4096);at=(p-pa)/4096;}
                else assert(p==pa+offsets[r]+off);
            }
            assert(!!(entry&(1u<<7))==(r==0));
            assert(!!(entry&(3ull<<53))==(r!=0));
        }
        ++firmware_cleaned;return;
    }
    const uint32_t *payload=(const uint32_t *)(arena+PAGE_SIZE);
    for(unsigned i=0;i<PAGE_SIZE/4;i++)assert(payload[i]==(0x64000000u^i));
    ++cleaned;
}
static void kmem_free(int map,uintptr_t v,size_t n) {
    assert(map==kernel_map && v==allocation && n==allocation_bytes && allocated);allocated=0;++freed;
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
    if(bank>=(uintptr_t)smmu && bank-(uintptr_t)smmu<sizeof(smmu)) {
        off+=(unsigned)(bank-(uintptr_t)smmu);
        assert((off>=0xc000 && off<=0xc03c) || off==0x1010 || off==0x1810 || off==0xc618 || off==0xc7f0 || off==0x800 || off==0x804 || off==0xc00 || off==0xc04);
        assert(gmu[0x16000/4]==1 && !(cc[0x100c/4]&(1u<<31)));
        if(off==0xc618) {assert(value==0);++tlbi_commands;return;}
        if(off==0xc7f0) {assert(value==0xffffffffu);return;}
        if(unmatch_fail && off==0x800 && value==0 && (smmu[off/4]&(1u<<31)))return;
        if(context_bad_readback && off==0xc030 && value!=0) value^=1;
        if(context_bad_route && off==0x800 && value==0x84000004u) value^=1;
        if(off==0xc00 || off==0xc04) {
            unsigned type=(value>>16)&3;
            if(context_detach_fail && off==0xc00 && (type==1 || type==2) && smmu[off/4]==4)return;
            if(type==2 && (fault_quirk || fault_unsupported))return;
            if(type==1) {assert(!(smmu[(off-0x400)/4]&(1u<<31)));++bypass_writes;if(fault_quirk)value=(value&~(3u<<16))|(2u<<16);}
        }
        if((off==0x800 || off==0x804) && (value&(1u<<31))) {assert(((smmu[(off+0x400)/4]>>16)&3)==2);++route_publishes;}
        smmu[off/4]=value;++smmu_writes;return;
    }
    if(bank==(uintptr_t)gmu+0x2000) {
        assert((off>=0x3000 && off<0xb000));
        if(!((cc[0x1540/4]&(1u<<31)) && (cc[0x1124/4]&0x371f)==0x602 && gmu[0x16000/4]==1)) {fprintf(stderr,"bad TCM write off=%x HW=%x cfg=%x reset=%x drain=%d\n",off,cc[0x1540/4],cc[0x1124/4],gmu[0x16000/4],context_drain_fail);abort();}
        if(!(tcm_fail && off==0x6fe0 && value==0xa6400000u) && !(fw_tcm_fail && off==0x3000 && value))gmu[(off+0x2000)/4]=value;
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
static void model_write64(uintptr_t bank,unsigned off,uint64_t value) {
    model_write(bank,off,(uint32_t)value);model_write(bank,off+4,(uint32_t)(value>>32));
}
static uint32_t model_read(uintptr_t address) {
    uint32_t *banks[]={gcc,cc,gmu,gpu,smmu};
    size_t sizes[]={sizeof(gcc),sizeof(cc),sizeof(gmu),sizeof(gpu),sizeof(smmu)};
    assert(!(address&3));
    for(unsigned i=0;i<5;i++) {
        uintptr_t base=(uintptr_t)banks[i];
        if(address>=base && address-base<sizes[i]) {
            if(i==4) {++smmu_reads; if(address-base>=0x800)++context_reads;}
            if(i==4 && address-base==0xc7f4 && context_drain_fail)return 1;
            return *(uint32_t *)address;
        }
    }
    assert(0); return 0;
}
static int tsleep(void *channel,int priority,const char *name,int ticks) {
    (void)channel; assert(priority==PZERO && (!strcmp(name,"gpucxlog") || !strcmp(name,"gpusmmulog") || !strcmp(name,"gmupreplog") || !strcmp(name,"gmufwlog") || !strcmp(name,"gmuctxlog")) && ticks==3*hz); ++sleeps; return 0;
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
static int SecureDTGetProperty(DTEntry r,const char *k,const void **p,unsigned *n) {
    (void)r;
    if(!strcmp(k,"raphael-gmu-firmware")) {if(!firmware_present)return 1;*p=firmware;*n=firmware_bytes;return 0;}
    assert(!strcmp(k,"compatible"));*p=compatible;*n=length;return 0;
}
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
static void reset_fw(void) {
    reset_cx();
    cc[0x106c/4]=(cc[0x106c/4]&~1u)|(1u<<31);cc[0x1540/4]|=1u<<31;cc[0x1124/4]=0x602;cc[0x1120/4]=0;
    smmu[0]=0x250406;smmu[0x20/4]=0x4c017e06;smmu[0x24/4]=0x20000005;smmu[0x28/4]=0x5555;smmu[0x800/4]=0;
    firmware_cleaned=smmu_writes=tlbi_commands=0;
    context_bad_readback=context_bad_route=context_drain_fail=context_detach_fail=fw_tcm_fail=0;
    fault_quirk=fault_unsupported=bypass_writes=route_publishes=unmatch_fail=0;
    memcpy(saved_smmu,smmu,sizeof(smmu));
}
int main(int argc,char **argv) {
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
    if(argc==2) {
        FILE *f=fopen(argv[1],"rb");assert(f);firmware=malloc(37680);assert(firmware);
        assert(fread(firmware,1,37680,f)==37680 && fgetc(f)==EOF);fclose(f);
        firmware_bytes=37680;firmware_present=1;
        reset_fw();gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);
        assert(firmware_cleaned==1 && !allocated && freed==1 && smmu_writes>0 && tlbi_commands==2 && !memcmp(saved_smmu,smmu,sizeof(smmu)));
        for(unsigned i=0;i<sizeof(gmu)/4;i++)assert(gmu[i]==(i==0x16000/4 ? 1u : 0u));
        assert(!bypass_writes && route_publishes==2);
        reset_fw();fault_quirk=1;smmu[0xc058/4]=0x400;memcpy(saved_smmu,smmu,sizeof(smmu));
        gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);
        assert(freed==1 && !allocated && tlbi_commands==2 && bypass_writes==4 && route_publishes==2 && !memcmp(saved_smmu,smmu,sizeof(smmu)));
        reset_fw();fault_quirk=1;smmu[0xc00/4]=0x20007;smmu[0xc04/4]=0x20008;memcpy(saved_smmu,smmu,sizeof(smmu));
        gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);
        assert(freed==1 && !allocated && tlbi_commands==2 && bypass_writes==4 && route_publishes==2 && !memcmp(saved_smmu,smmu,sizeof(smmu)));
        reset_fw();fault_unsupported=1;gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);
        assert(freed==1 && !allocated && !tlbi_commands && bypass_writes==2 && !route_publishes && !memcmp(saved_smmu,smmu,sizeof(smmu)));
        reset_fw();smmu[0x800/4]=1u<<31;assert(!gpu_stream_fault((uintptr_t)smmu,0) && !smmu_writes);
        unsigned faults[]={2,4,8,16,32,64,128,256,1u<<30,1u<<31};
        for(unsigned i=0;i<sizeof(faults)/sizeof(faults[0]);i++) {
            reset_fw();smmu[0xc058/4]=0x400|faults[i];gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);
            assert(freed==1 && !smmu_writes && !tlbi_commands && !route_publishes);
        }
        reset_fw();firmware[0]^=1;gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);firmware[0]^=1;
        assert(!allocated && !freed && !smmu_writes && !tcm_writes);
        reset_fw();--firmware_bytes;gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);++firmware_bytes;
        assert(!freed && !smmu_writes);
        reset_fw();alloc_fail=1;gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);assert(!freed && !smmu_writes);
        reset_fw();physical_fail=1;gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);assert(freed==1 && !smmu_writes && !tcm_writes);
        reset_fw();smmu[0x800/4]=0x80000007;gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);assert(firmware_cleaned==1 && freed==1 && !smmu_writes);
        reset_fw();smmu[0x9000/4]=1;gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);assert(freed==1 && !smmu_writes);
        reset_fw();context_bad_readback=1;gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);assert(freed==1 && tlbi_commands==2 && !memcmp(saved_smmu,smmu,sizeof(smmu)));
        reset_fw();context_bad_route=1;gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);assert(freed==1 && !memcmp(saved_smmu,smmu,sizeof(smmu)));
        reset_fw();fw_tcm_fail=1;gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);assert(freed==1 && !smmu_writes);
        reset_cx();smmu[0]=0x250406;smmu[0x20/4]=0x4c017e06;smmu[0x24/4]=0x20000005;smmu[0x28/4]=0x5555;smmu[0x800/4]=0;
        memcpy(saved_smmu,smmu,sizeof(smmu));sweet_gpu_probe();
        assert(firmware_cleaned && freed==2 && !allocated && !memcmp(saved_smmu,smmu,sizeof(smmu)) && !memcmp(saved,cc,sizeof(cc)));
        reset_fw();context_detach_fail=1;gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);assert(allocated && !freed);allocated=0;++retained;
        reset_fw();unmatch_fail=1;gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);assert(allocated && !freed && !bypass_writes);allocated=0;++retained;
        reset_fw();context_drain_fail=1;gpu_firmware_test((uintptr_t)smmu,(uintptr_t)gmu+0x2000);assert(allocated && !freed && tlbi_commands==2);++retained;
        /* Model teardown only: production keeps this allocation until reboot. */
        allocated=0;free(firmware);
    }
}
'''
with tempfile.TemporaryDirectory(prefix='raphael-gpu-') as tmp:
    c, exe = Path(tmp) / 'check.c', Path(tmp) / 'check'
    c.write_text(code)
    dev = Path(sys.argv[1]) / 'bsd/dev'
    subprocess.run([os.environ.get('CC', 'cc'), '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-Wno-deprecated-declarations', '-g', '-I', str(dev), str(c),
                    str(dev / 'ArmSmmu4K.c'), str(dev / 'ArmSmmu4KContext.c'), str(dev / 'AdrenoFirmware.c'),
                    '-lcrypto', '-o', str(exe)], check=True)
    result = subprocess.run([str(exe), *sys.argv[2:]], check=True, capture_output=True, text=True)
    if len(sys.argv) > 2:
        assert any("programmed=1 routed=1" in line and "FSR=0x400 GFSR=0" in line for line in result.stdout.splitlines())
print('PASS: A640 gates/rollback and owned tables; optional firmware fixture exercises load/CB4/routes/drain/retention (ASan/UBSan)')
