#!/bin/bash
# Build raphael userdata boot; opt in to touch, PM8150 keys and 1/4/8 CPU tests.
set -euo pipefail
kernel=$(realpath "${1:?usage: build-raphael-stage2.sh KERNEL RAPHAEL_DTB [--touch] [--keys] [--cpus N]}")
dtb=$(realpath "${2:?usage: build-raphael-stage2.sh KERNEL RAPHAEL_DTB}")
shift 2
profile=raphael-stage2
touch_args=sweettouch=0
touch=0
keys=0
cpus=1
check_args=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --touch) touch=1; shift ;;
        --keys) keys=1; shift ;;
        --cpus)
            [ "$#" -ge 2 ] || { echo '--cpus requires 1, 4 or 8' >&2; exit 1; }
            cpus=$2; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 1 ;;
    esac
done
case "$cpus" in 1|4|8) ;; *) echo '--cpus requires 1, 4 or 8' >&2; exit 1 ;; esac
if [ "$touch" = 1 ]; then
    profile=raphael-stage3
    touch_args='sweettouch=1 sweettouchdelay=45'
    check_args=(--touch --cpus "$cpus")
elif [ "$keys" != 0 ] || [ "$cpus" != 1 ]; then
    echo '--keys and SMP require --touch' >&2
    exit 1
fi
[ "$keys" = 0 ] || check_args+=(--keys)
cd "$(dirname "$0")/.."
mkdir -p shim/out
python3 tools/mkadt.py "shim/out/$profile.adt" --raphael --raphael-cpus "$cpus"
python3 tools/mkpayload.py "$kernel" "shim/out/$profile.adt" "shim/out/$profile.bin" \
    --cmdline "debug=0xc serial=3 cpus=$cpus keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 ufsroot=userdata unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1 sweetfb_noconsole=1 sweetfb_hz=30 sweetlog=1 sweetkeys=$keys $touch_args sweetusb=0 sweetbattery=0"
BOARD=raphael DTB="$dtb" bash shim/build.sh "../shim/out/$profile.bin"
cp shim/out/shim-boot.img "shim/out/$profile.img"
python3 tools/check-raphael-stage2.py "shim/out/$profile.img" "${check_args[@]}"
