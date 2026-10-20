#!/bin/bash
# Build a RAM-only kernel/logging image. This script never invokes fastboot.
set -euo pipefail
kernel=$(realpath "${1:?usage: build-raphael-stage1.sh KERNEL RAPHAEL_DTB}")
dtb=$(realpath "${2:?usage: build-raphael-stage1.sh KERNEL RAPHAEL_DTB}")
cd "$(dirname "$0")/.."
mkdir -p shim/out
python3 tools/mkadt.py shim/out/raphael-stage1.adt --raphael-stage1
python3 tools/mkpayload.py "$kernel" shim/out/raphael-stage1.adt shim/out/raphael-stage1.bin \
    --cmdline 'debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress rd=md0 ufsrw=0 rootrw=0 sweetlog=0 sweetkeys=0 sweettouch=0 sweetusb=0 sweetbattery=0 wdt=-1'
BOARD=raphael DTB="$dtb" bash shim/build.sh ../shim/out/raphael-stage1.bin
cp shim/out/shim-boot.img shim/out/raphael-stage1.img
python3 tools/check-raphael-stage1.py shim/out/raphael-stage1.img
