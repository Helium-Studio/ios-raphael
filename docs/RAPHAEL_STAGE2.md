# raphael stage two: userdata root and Apple-logo bring-up

The target is an actual iOS startup screen using the prepared iPhone X root.
Stage one already reached BSD on raphael. This stage enables the UFS backend
and IOMobileFramebuffer, retaining one CPU and disabling the unported input,
USB and real battery paths. AppleCLCD reads the actual 1080x2340 boot-video
geometry and presents the existing iPhone X logical canvas.

## Prerequisites

Keep a verified full userdata backup and the original boot image. The current
phone has userdata on UFS LUN 0, 4096-byte device blocks, GPT start LBA507904
and29136891 blocks. Detect the GPT partition by its name; do not replace the
partition table or reuse another phone's partition numbers. Use the installed
Recovery with `fastboot oem reboot-recovery` for inspection and log collection.

`NOTES.md` records actual checks, hashes, flashes and physical observations.
A successful image build does not establish an Apple-logo result.

## Build

Use the same compiler overrides as stage one and a kernel with patch0082 or
later:

```sh
bash tools/build-raphael-stage2.sh \
  xnu/out-0082/kernel.development.sweet \
  "$HOME/kernel/zundamon_raphael/out/arch/arm64/boot/dts/qcom/sm8150-xiaomi-raphael.dtb"
```

Output: `shim/out/raphael-stage2.img`. Its checker requires:

- `--raphael` ADT, real d22ap product properties and a single Kryo485;
- upper RAM at0x100000000+0xfcc00000 and the corrected console mapping;
- `/sweet-ufs` at0x1d84000 and no `/chosen/no-storage` interlock;
- `rd=ufsroot0 ufsroot=userdata ufsrw=1 rootrw=1`;
- enabled display and persistent log, with unported hardware disabled.

The shim still halts if payload loading fails; it does not probe storage
itself. The kernel performs the bounded accesses to the named userdata
partition. The early console is muted after the first framebuffer swap;
panics remain visible, and the console ring is stored at userdata's end,
outside the16GiB filesystem.

## Deploy the two explicitly authorized partitions

Verify the exact sparse image and boot image against their checksums and
partition sizes. Keep USB attached during the root flash. With the phone in
Bootloader and after the required backup/authorization:

```sh
fastboot -S 512M flash userdata ios16-root-20H392-raphael-v1.simg
fastboot flash boot shim/out/raphael-stage2.img
fastboot reboot
```

The user explicitly requested boot-partition installation for this stage;
Recovery, bootloaders, modem, persist, vbmeta and GPT remain intact. On this
WSL host use Windows fastboot with Windows-accessible file paths and the
verified device selected explicitly. If ABL stops responding after the large
flash, return to Bootloader manually before the next operation. Do not infer
success from a stalled command or keep retrying against a hung bootloader.

First test the UFS path with writes/logging disabled. Before flashing HFS+,
the original userdata is F2FS; reaching its GPT entry followed by an unsupported
root-filesystem error establishes a read probe, not an iOS boot.

## Observe and diagnose

Require a physical observation of the Apple logo. Do not draw a substitute
logo in the shim. If startup fails, preserve the panic or re-enter installed
Recovery and read the last1025 blocks of the actual userdata block device.
`tools/sweet-log.py` decodes the SWEETLOG ring; `sweet-log-pull.sh` discovers
userdata by-name, but its adb executable must be reachable on the current host.

The fresh root did not contain a mobileactivationd system container, so its
data-ark seed was skipped by the README tweaks. Activation, input, full GUI
and normal app operation are later validation tasks.
