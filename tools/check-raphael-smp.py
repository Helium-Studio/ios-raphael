#!/usr/bin/env python3
"""Check raphael CPU profiles against the Recovery MPIDR/frequency survey."""
import struct
import adt
import mkadt


def cpus(root):
    return next(n for n in root.children if n.name == 'cpus').children


for count in (1, 4, 8):
    root = mkadt.build(seed=b'\0' * 64, raphael=True, raphael_cpus=count)
    blob = adt.serialize(root)
    parsed, _ = adt.parse(blob)
    nodes = cpus(parsed)
    assert len(nodes) == count
    assert [struct.unpack('<I', n.prop('reg'))[0] for n in nodes] == [i * 256 for i in range(count)]
    expected = [1785600000] * 4 + [2419200000] * 3 + [2841600000]
    assert [struct.unpack('<I', n.prop('clock-frequency'))[0] for n in nodes] == expected[:count]
    for core, n in enumerate(nodes):
        assert n.prop('l2-cache-id') == struct.pack('<I', core)
        assert n.prop('l3-cache-id') == n.prop('cluster-type') == struct.pack('<I', 0)
        assert n.prop('state') == (b'running\0' if core == 0 else b'stopped\0')
        assert n.prop('compatible').split(b'\0')[0] == b'qcom,kryo485'

for options, count in (({}, 8), ({'highmem': True}, 8), ({'qemu': True}, 1),
                       ({'raphael_stage1': True}, 1)):
    assert len(cpus(mkadt.build(seed=b'\0' * 64, **options))) == count

for options in ({'raphael': True, 'raphael_cpus': 2}, {'raphael_cpus': 8},
                {'raphael_stage1': True, 'raphael_cpus': 4},
                {'raphael': True, 'qemu': True, 'raphael_cpus': 8}):
    try:
        mkadt.build(**options)
    except ValueError:
        pass
    else:
        raise AssertionError(f'invalid profile accepted: {options}')
print('PASS: raphael 1/4/8 CPUs, measured frequency groups, MPIDRs, cache IDs and profile isolation')
