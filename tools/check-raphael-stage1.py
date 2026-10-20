#!/usr/bin/env python3
"""Check the storage-off contract in a packaged raphael stage-one boot image."""
import hashlib
import shlex
import struct
import sys
from pathlib import Path

import adt


def check(image):
    assert image[:8] == b'ANDROID!', 'not an Android boot image'
    kernel_size, _, ramdisk_size = struct.unpack_from('<3I', image, 8)
    page, version = struct.unpack_from('<2I', image, 36)
    assert page == 4096 and version == 2, 'expected boot header v2 / 4K pages'
    offset = page + (kernel_size + page - 1) // page * page
    payload = image[offset:offset + ramdisk_size]
    assert len(payload) == ramdisk_size, 'truncated payload'
    assert payload[:8] == b'SWEETXNU', 'missing XNU payload'
    adt_off, adt_size = struct.unpack_from('<2Q', payload, 0x20)
    root, _ = adt.parse(payload[adt_off:adt_off + adt_size])
    nodes = {c.name: c for c in root.children}
    assert root.prop('compatible').split(b'\0')[0] == b'xiaomi,raphael'
    assert 'sweet-ufs' not in nodes, 'UFS must not be described'
    chosen = nodes['chosen']
    assert chosen.prop('no-storage') == struct.pack('<I', 1), 'missing storage interlock'
    assert next(c for c in chosen.children if c.name == 'memory-map').prop('RAMDisk') is None, 'stage one has no userland root'
    phys, size = struct.unpack_from('<2Q', payload, 0x38)
    assert (phys, size) == (0xb2000000, 0x1e000000), 'unexpected RAM aperture'
    assert chosen.prop('dram-base') == struct.pack('<Q', phys)
    assert chosen.prop('dram-size') == struct.pack('<Q', size)
    assert len(nodes['cpus'].children) == 1, 'stage one must be single-core'
    assert [c.name for c in nodes['arm-io'].children] == ['gic'], 'unexpected hardware drivers'
    assert nodes['sweet-fbcon'].prop('height') == struct.pack('<I', 2340)
    fb_phys, fb_size = struct.unpack('<2Q', nodes['sweet-fbcon'].prop('reg'))
    assert fb_phys == 0x9c000000 and 1080 * 2340 * 4 <= fb_size <= 0x2000000, 'framebuffer must fit the early I/O aperture'
    args = shlex.split(payload[0x48:0x2a8].split(b'\0')[0].decode())
    pairs = [arg.split('=', 1) for arg in args if '=' in arg]
    assert len({key for key, _ in pairs}) == len(pairs), 'ambiguous duplicate boot arguments'
    options = dict(pairs)
    required = dict(rd='md0', cpus='1', ufsrw='0', rootrw='0', sweetlog='0',
                    sweetkeys='0', sweettouch='0', sweetusb='0', sweetbattery='0')
    assert all(options.get(key) == value for key, value in required.items()), 'unsafe boot arguments'
    assert 'sweetfb_noconsole=1' not in args, 'screen console must remain enabled'
    return hashlib.sha256(image).hexdigest()


if __name__ == '__main__':
    path = Path(sys.argv[1])
    print(f'PASS: raphael single-core / storage disabled / screen logs; SHA256 {check(path.read_bytes())}')
