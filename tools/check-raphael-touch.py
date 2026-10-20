#!/usr/bin/env python3
"""Host checks for the actual GT9886 report decoder: check-raphael-touch.py XNU_TREE."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

source = (Path(sys.argv[1]) / 'bsd/dev/sweet_touch.c').read_text()
start = source.index('static int\ntouch_normandy_decode(')
end = source.index('\nstatic int\n', start + 1)
decoder = source[start:end]
harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#define TOUCH_MAX 10u
''' + decoder + r'''
static void checksum(uint8_t *b, unsigned n) {
    unsigned sum = 0;
    for (unsigned i = 0; i < n - 1; i++) sum += b[i];
    b[n - 1] = (uint8_t)-sum;
}
static void point(uint8_t *b, unsigned i, unsigned id, unsigned x, unsigned y) {
    uint8_t *p = b + 2 + 8 * i;
    p[0] = id; p[1] = x; p[2] = x >> 8; p[3] = y; p[4] = y >> 8;
}
int main(void) {
    uint8_t b[84] = {0x80, 0};
    int x[10] = {0}, y[10] = {0}; uint32_t mask = 0x3ff;
    checksum(b, 4);
    assert(!touch_normandy_decode(b, 4, false, &mask, x, y) && mask == 0);
    b[1] = 1; point(b, 0, 9, 1079, 2339); checksum(b, 12);
    assert(!touch_normandy_decode(b, 12, false, &mask, x, y));
    assert(mask == (1u << 9) && x[9] == 1079 && y[9] == 2339);
    assert(!touch_normandy_decode(b, 12, true, &mask, x, y));
    assert(x[9] == 0 && y[9] == 0);
    for (unsigned len = 0; len < 12; len++)
        assert(touch_normandy_decode(b, len, false, &mask, x, y));
    b[11] ^= 1;
    assert(touch_normandy_decode(b, 12, false, &mask, x, y) == EIO);
    checksum(b, 12); b[0] = 0;
    assert(touch_normandy_decode(b, 12, false, &mask, x, y)); b[0] = 0x80;
    point(b, 0, 10, 0, 0); checksum(b, 12);
    assert(touch_normandy_decode(b, 12, false, &mask, x, y));
    point(b, 0, 0x80, 0, 0); checksum(b, 12);
    assert(touch_normandy_decode(b, 12, false, &mask, x, y));
    point(b, 0, 0, 1080, 0); checksum(b, 12);
    assert(touch_normandy_decode(b, 12, false, &mask, x, y));
    point(b, 0, 0, 0, 2340); checksum(b, 12);
    assert(touch_normandy_decode(b, 12, false, &mask, x, y));
    b[1] = 2; point(b, 0, 0, 0, 0); point(b, 1, 0, 10, 20); checksum(b, 20);
    assert(touch_normandy_decode(b, 20, false, &mask, x, y));
    b[1] = 10;
    for (unsigned i = 0; i < 10; i++) point(b, i, i, 100 + i, 200 + i);
    checksum(b, 84);
    assert(!touch_normandy_decode(b, 84, false, &mask, x, y) && mask == 0x3ff);
    assert(x[0] == 100 && y[9] == 209);
    b[1] = 11; checksum(b, 84);
    assert(touch_normandy_decode(b, 84, false, &mask, x, y));
}
'''
with tempfile.TemporaryDirectory(prefix='raphael-touch-') as tmp:
    c, exe = Path(tmp) / 'check.c', Path(tmp) / 'check'
    c.write_text(harness)
    subprocess.run([os.environ.get('CC', 'cc'), '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-g', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('PASS: actual Normandy decoder, 0–10 fingers, mirror, bounds, checksum and malformed frames (ASan/UBSan)')
