#!/bin/bash
# Build the userdata-backed raphael image; --touch enables the stage-three test.
set -euo pipefail
kernel=$(realpath "${1:?usage: build-raphael-stage2.sh KERNEL RAPHAEL_DTB [--touch]}")
dtb=$(realpath "${2:?usage: build-raphael-stage2.sh KERNEL RAPHAEL_DTB}")
profile=raphael-stage2
touch_args=sweettouch=0
check_args=()
if [ "${3:-}" = --touch ] && [ "$#" = 3 ]; then
    profile=raphael-stage3
    touch_args='sweettouch=1 sweettouchdelay=45'
    check_args=(--touch)
elif [ "$#" != 2 ]; then
    echo 'usage: build-raphael-stage2.sh KERNEL RAPHAEL_DTB [--touch]' >&2
    exit 1
fi
cd "$(dirname "$0")/.."
mkdir -p shim/out
python3 tools/mkadt.py "shim/out/$profile.adt" --raphael
python3 tools/mkpayload.py "$kernel" "shim/out/$profile.adt" "shim/out/$profile.bin" \
    --cmdline "debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 ufsroot=userdata unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1 sweetfb_noconsole=1 sweetfb_hz=30 sweetlog=1 sweetkeys=0 $touch_args sweetusb=0 sweetbattery=0"
BOARD=raphael DTB="$dtb" bash shim/build.sh "../shim/out/$profile.bin"
cp shim/out/shim-boot.img "shim/out/$profile.img"
python3 tools/check-raphael-stage2.py "shim/out/$profile.img" "${check_args[@]}"
