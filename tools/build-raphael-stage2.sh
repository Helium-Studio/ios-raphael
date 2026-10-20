#!/bin/bash
# Build the userdata-backed raphael image. Deployment is a separate operation.
set -euo pipefail
kernel=$(realpath "${1:?usage: build-raphael-stage2.sh KERNEL RAPHAEL_DTB}")
dtb=$(realpath "${2:?usage: build-raphael-stage2.sh KERNEL RAPHAEL_DTB}")
cd "$(dirname "$0")/.."
mkdir -p shim/out
python3 tools/mkadt.py shim/out/raphael-stage2.adt --raphael
python3 tools/mkpayload.py "$kernel" shim/out/raphael-stage2.adt shim/out/raphael-stage2.bin \
    --cmdline 'debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 ufsroot=userdata unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1 sweetfb_noconsole=1 sweetfb_hz=30 sweetlog=1 sweetkeys=0 sweettouch=0 sweetusb=0 sweetbattery=0'
BOARD=raphael DTB="$dtb" bash shim/build.sh ../shim/out/raphael-stage2.bin
cp shim/out/shim-boot.img shim/out/raphael-stage2.img
python3 tools/check-raphael-stage2.py shim/out/raphael-stage2.img
