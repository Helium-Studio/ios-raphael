# raphael: XNU kernel and screen logs, without storage access

This stage uses the existing SWEET arm64 kernel configuration with patch
0082 and a raphael-specific ADT/shim. It starts one CPU and keeps the screen
console enabled. There is no iOS root filesystem or userspace in this image.

Hardware reference: `$HOME/kernel/zundamon_raphael`, branch
`zundamon-miui-6.12`, commit `1b97d061c384`, with the local
`zundamon-miui-5.4` branch as a downstream reference. No Linux source changes
are needed.

- Framebuffer: `0x9c000000`, 1080x2340, stride 4320, BGRA, reservation 36 MiB.
  The console maps only the visible pixels, rounded to 16 KiB; mapping the
  entire reservation crosses an unpopulated early I/O L2 table and panics.
- Panel: Samsung EA8076 command mode. The shim retains ABL's configuration;
  when PP0 tear-check is enabled it enables one-frame autorefresh and starts
  CTL0. Register offsets come from the reference tree's SDE driver.
- Kernel RAM aperture: `0x100000000 + 0x20000000` (512 MiB). The live
  Recovery FDT reports RAM from `0xc0000000` to `0x200000000`; all its fixed
  carve-outs and dynamic pools are below 4 GiB. This avoids the live RAM
  hole at `0xbcc00000..0xbfffffff`, which the original source-based window
  crossed. The successful 0082b trial used the earlier window.
- GICD/GICR: `0x17a00000` / `0x17a60000`; virtual timer INTID 19.
- Platform/CPU matching: `xiaomi,raphael` / `qcom,kryo485`.

## Build

Build the XNU kernel through `.github/workflows/xnu.yml` with
`machine_config=SWEET`, then download the `xnu-kernel` artifact using `gh`.
Use a kernel built with 0082 or later. The exact build and phone observations
are recorded at the top of `NOTES.md`.

The shim requires an AArch64 compiler, objcopy/readelf/nm, host GCC, Python 3
and `mkbootimg`. For the existing Android LLVM toolchain:

```sh
export CC="$HOME/toolchains/r596125/bin/clang --target=aarch64-none-elf"
export OBJCOPY="$HOME/toolchains/r596125/bin/llvm-objcopy"
export READELF="$HOME/toolchains/r596125/bin/llvm-readelf"
export NM="$HOME/toolchains/r596125/bin/llvm-nm"
bash tools/build-raphael-stage1.sh \
  xnu/out-0082/kernel.development.sweet \
  "$HOME/kernel/zundamon_raphael/out/arch/arm64/boot/dts/qcom/sm8150-xiaomi-raphael.dtb"
```

Output: `shim/out/raphael-stage1.img`. The script checks the packaged ADT,
single-core configuration, screen height and storage-off arguments. It does
not boot or flash the phone. With GNU tools the compiler overrides can be
omitted.

## Temporary test

```sh
fastboot boot shim/out/raphael-stage1.img
```

On this WSL host, USB is visible to Windows `fastboot.exe`, so copy the image
to a Windows-accessible location and pass its Windows path. Select the one
verified device explicitly. Never run `fastboot flash` for this stage.

The image contains no RAM root, so reaching BSD root selection with `rd=md0`
produces the expected "specified root memory device ... has not been
configured" panic. That is an explicit boundary of this kernel/logging test,
not a successful userspace boot. A physical observation of XNU messages is
required; fastboot's OKAY only proves bootloader acceptance.

## Confirmed result (2026-10-20)

Kernel 0082, CI run [39387632116](https://github.com/Helium-Studio/ios-raphael/actions/runs/39387632116),
with the corrected framebuffer ADT (0082b), reached normal screen logs and
BSD root selection on the phone. The user observed `VM bootstrap done` and
`IOFindBSDRoot: specified root memory device, md0, has not been configured`.
The missing RAMDisk is the expected end of this stage. The `dlil_init`
message below it does not establish a scheduling hang. The corrected upper-RAM
image 0082c was then temporarily booted and the user confirmed the same
panic, validating the current RAM window as well.

## Local iOS root image

After the stage-one result, the user supplied `$HOME/20H392.ipsw` and
requested the README root-image workflow. Its manifest identifies
16.7.16 / 20H392, iPhone X / d22ap. Extract the OS, SystemOS and AppOS DMGs,
then follow README section 2 (`mkiosroot.sh`, root tweaks, `img2simg`).
These commands create host files; they do not deploy a root to the phone.

On a host without an HFS+ kernel driver, install `guestmount`, `guestfish`
and the libguestfs HFS+ support, and set `MKIOSROOT_GUESTMOUNT=1` for
`mkiosroot.sh`. The copy is streamed as tar inside the appliance, preserving
numeric owners, modes, symlinks and hard links. Guestmount is used only for
the final filesystem changes. A working libguestfs appliance kernel/modules
are required; WSL without KVM can use `LIBGUESTFS_BACKEND=direct` and
`LIBGUESTFS_BACKEND_SETTINGS=force_tcg`. If the host has no suitable kernel,
point `SUPERMIN_KERNEL`, `SUPERMIN_MODULES` and `SUPERMIN_KERNEL_VERSION`
at an unpacked distribution kernel, without changing the running kernel.

Run root tweaks on the mounted local image, unmount it, wait for guestmount
to exit, and check the filesystem before creating the sparse image. Do not
ignore a failed final read-only filesystem check. Exact local tools,
artifacts and checks are recorded in `NOTES.md`.
The root-tweaks writer explicitly truncates rewritten plists: some FUSE
backends retain old trailers when a shorter file is written with `O_TRUNC`.
A fresh image has no mobileactivationd system container yet, so the existing
tweaks script reports that it skipped the data-ark seed; first-boot activation
needs validation in the userspace stage.

The raphael storage driver, GUI display path and inputs are not validated
by the stage-one result. A packaged root image alone does not establish
that iOS userspace boots on raphael. The user subsequently authorized
userdata writes **after a complete verified backup**; that authorization
does not change the storage-off contract of the stage-one boot image.

## Storage contract

The raphael shim does not link the UFS probe. A missing/invalid payload or
shim exception leaves the diagnostic screen in place. Its ADT contains no
`sweet-ufs` node and has `/chosen/no-storage=1`, which patch 0082 checks before
UFS MMIO or DMA allocation. Boot arguments also set `ufsrw=0 rootrw=0
sweetlog=0`, and disable keys/touch/USB/real battery. There is no recovery
installation, root-image deployment, partition change or persistent log.

Kernel and screen progress must be collected from the visible console during
this stage. The existing userdata log-pull workflow is not used.
