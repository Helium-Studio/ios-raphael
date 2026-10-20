#!/usr/bin/env python3
"""Check a raphael boot image before deploying the userdata-backed iOS root."""
import argparse
import hashlib
import shlex
import struct
from pathlib import Path

import adt


def check(image, touch=False, keys=False, cpus=1):
    assert cpus in (1, 4, 8), 'unsupported CPU bring-up profile'
    assert touch or (not keys and cpus == 1), 'keys/SMP profiles must retain touch'
    assert image[:8] == b'ANDROID!', 'not an Android boot image'
    kernel_size, _, ramdisk_size = struct.unpack_from('<3I', image, 8)
    page, version = struct.unpack_from('<2I', image, 36)
    assert (page, version) == (4096, 2), 'expected boot header v2 / 4K pages'
    offset = page + (kernel_size + page - 1) // page * page
    payload = image[offset:offset + ramdisk_size]
    assert len(payload) == ramdisk_size and payload[:8] == b'SWEETXNU', 'invalid payload'
    adt_off, adt_size = struct.unpack_from('<2Q', payload, 0x20)
    assert adt_off + adt_size <= len(payload), 'truncated ADT'
    root, _ = adt.parse(payload[adt_off:adt_off + adt_size])
    nodes = {c.name: c for c in root.children}
    assert root.prop('model') == b'iPhone10,3\0'
    assert b'xiaomi,raphael' in root.prop('compatible').split(b'\0'), 'wrong board'
    assert 'product' in nodes and len(nodes['product'].props) > 50, 'missing d22ap identity'
    chosen = nodes['chosen']
    assert chosen.prop('no-storage') is None, 'storage interlock still present'
    assert struct.unpack('<2Q', nodes['sweet-ufs'].prop('reg')) == (0x1d84000, 0x3000)
    phys, size = struct.unpack_from('<2Q', payload, 0x38)
    assert (phys, size) == (0x100000000, 0xfcc00000), 'unexpected RAM aperture'
    assert chosen.prop('dram-base') == struct.pack('<Q', phys)
    assert chosen.prop('dram-size') == struct.pack('<Q', size)
    cpu_nodes = nodes['cpus'].children
    assert len(cpu_nodes) == cpus, 'CPU tree and requested profile disagree'
    for core, cpu in enumerate(cpu_nodes):
        assert b'qcom,kryo485' in cpu.prop('compatible').split(b'\0')
        assert cpu.prop('reg') == struct.pack('<I', core << 8), 'wrong MPIDR order'
        assert cpu.prop('cluster-type') == struct.pack('<I', 0), 'expected homogeneous SMP'
        if cpus != 1:
            frequency = 1785600000 if core < 4 else 2419200000 if core < 7 else 2841600000
            assert cpu.prop('clock-frequency') == struct.pack('<I', frequency), 'wrong Kryo 485 frequency metadata'
    assert nodes['sweet-fbcon'].prop('height') == struct.pack('<I', 2340)
    assert struct.unpack('<2Q', nodes['sweet-fbcon'].prop('reg')) == (0x9c000000, 0x9a4000)
    displays = [c for c in nodes['arm-io'].children if c.name == 'disp0']
    assert len(displays) == 1 and displays[0].prop('compatible') == b'sweet,display\0'
    args = shlex.split(payload[0x48:0x2a8].split(b'\0')[0].decode())
    pairs = [arg.split('=', 1) for arg in args if '=' in arg]
    assert len({key for key, _ in pairs}) == len(pairs), 'duplicate boot arguments'
    options = dict(pairs)
    required = dict(rd='ufsroot0', ufsroot='userdata', ufsrw='1', rootrw='1', cpus=str(cpus),
                    sweetlog='1', sweetkeys='1' if keys else '0', sweettouch='1' if touch else '0', sweetusb='0',
                    sweetbattery='0', sweetfb_noconsole='1', ignition_level='1',
                    launchd_unsecure_cache='1')
    assert all(options.get(key) == value for key, value in required.items()), 'wrong root/write/driver arguments'
    if touch:
        assert options.get('sweettouchdelay') == '45', 'unexpected touch probe delay'
    return hashlib.sha256(image).hexdigest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--touch', action='store_true', help='require the stage-three touch test')
    parser.add_argument('--keys', action='store_true', help='require the raphael PM8150 key driver')
    parser.add_argument('--cpus', type=int, choices=(1, 4, 8), default=1)
    args = parser.parse_args()
    print(f'PASS: raphael / userdata rw / touch={args.touch} / keys={args.keys} / cpus={args.cpus}; SHA256 {check(args.image.read_bytes(), args.touch, args.keys, args.cpus)}')
