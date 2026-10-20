#!/bin/bash
# Build the shim and wrap it in a boot.img v2 that mirrors the stock PixelOS header.
set -euo pipefail
cd "$(dirname "$0")"
CC=${CC:-aarch64-linux-gnu-gcc}
OBJCOPY=${OBJCOPY:-aarch64-linux-gnu-objcopy}
READELF=${READELF:-aarch64-linux-gnu-readelf}
NM=${NM:-aarch64-linux-gnu-nm}
DTB=${DTB:-../dtb/boot_unpacked/dtb}
BOARD=${BOARD:-sweet}
BOARD_FLAGS=
CFLAGS="-O2 -ffreestanding -nostdlib -fno-pic -fno-jump-tables -mgeneral-regs-only -mstrict-align -fno-stack-protector -Wall -Wextra"
case "$BOARD" in
	sweet) ;;
	raphael) BOARD_FLAGS=-DRAPHAEL_STAGE1 ;;
	*) echo "unsupported board: $BOARD" >&2; exit 1 ;;
esac
CFLAGS="$CFLAGS $BOARD_FLAGS"
mkdir -p out
sources=(start.S shim.c console.c mmu.c fdt.c loader.c)
[ "$BOARD" = raphael ] || sources+=(ufs.c)
objects=()
for f in "${sources[@]}"; do
	$CC $CFLAGS -c $f -o out/${f%.*}.o
	objects+=(out/${f%.*}.o)
done
# The image runs wherever ABL puts it with no relocation pass: only the
# header's image_size (start.o, linked at 0) may be an absolute address.
abs=$($READELF -r "${objects[@]:1}" | grep -c ABS64 || true)
[ "$abs" = 0 ] || { echo "error: $abs absolute relocations in C objects" >&2; exit 1; }
$CC $CFLAGS -static -T shim.ld -Wl,--build-id=none -Wl,-N \
	"${objects[@]}" -o out/shim.elf
$OBJCOPY -O binary out/shim.elf out/Image
# ABL copies the file; pad to image_size so .bss/stacks exist as zeroed bytes.
size=$($NM out/shim.elf | python3 -c 'import sys; print(next(int(s.split()[0], 16) for s in sys.stdin if s.split()[-1] == "_end"))')
truncate -s "$size" out/Image
# Ramdisk: an xnu payload (tools/mkpayload.py) if given as $1, else an empty
# newc cpio (ABL dislikes a zero-size ramdisk on some builds) -> diagnostics.
if [ -n "${1:-}" ]; then
	cp "$1" out/ramdisk.bin
else
	if [ "$BOARD" = raphael ]; then
		printf 'RAPHAEL-PROBE' > out/ramdisk.bin
	else
	(cd out && rm -rf rd && mkdir rd && cd rd && find . | cpio -o -H newc --quiet | gzip -9 > ../ramdisk.bin)
	fi
fi
mkbootimg --header_version 2 --kernel out/Image --ramdisk out/ramdisk.bin \
	--dtb "$DTB" --base 0 --kernel_offset 0x8000 --ramdisk_offset 0x1000000 \
	--tags_offset 0x100 --dtb_offset 0x1f00000 --pagesize 4096 \
	--os_version 17.0.0 --os_patch_level 2035-06 \
	--cmdline "console=null" -o out/shim-boot.img
# Host render of the console layout.
gcc -O1 -Wall $BOARD_FLAGS -o out/host_test console.c host_test.c && ./out/host_test
ls -l out/Image out/shim-boot.img
