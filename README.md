# ios-ginkgo

Apple's XNU kernel on the **Xiaomi Redmi Note 8** (`ginkgo`, SM6125 /
Snapdragon 665).

> **Status: hardware probe only.** The shim builds and produces a boot image
> that can be started with `fastboot boot`. Nothing boots iOS on this phone yet,
> and two blockers stand between here and a lock screen. They are documented
> below rather than discovered later.

This is a port of [`dipa-studio/ios-sweet`](https://github.com/dipa-studio/ios-sweet)
(MIT), which brought iOS 16 to the Redmi Note 10 Pro (`sweet`, SM7150). The
structure, the ADT generator, the boot shim and the patch series are theirs.
What this repository adds is the device layer for a board nobody has done, and
an honest record of why it is harder than the existing ports.

## Why this board is different

Two facts decide everything, both read out of the phone's own device tree:

### Storage is eMMC, and no XNU eMMC driver exists

`soc/sdhci@4744000` (8-bit, `sdhc_1`) is the eMMC host. The SoC tree also carries
`ufshc@4804000` and the vendor kernel builds `CONFIG_SCSI_UFS_QCOM=y`, but this
board does not populate that controller. Confirmed three ways: the base tree
marks every storage controller `status = "disabled"`, the board overlay enables
only `sdhc_2` (the microSD slot), and the public specification says eMMC 5.1.

Every working port in this ecosystem reads its root from a **UFS** host, because
ios-sweet wrote a UFS driver (patches 0028–0034). An SDHCI driver for XNU does
not exist in any public port. Until one exists there is no root device, so
`launchd` cannot start and iOS cannot reach a lock screen. This is the port's
first blocker and its largest piece of work.

### All eight cores are ARMv8.0, and the A53 has no 16 KB granule

Four Kryo 260 Silver are Cortex-A53, four Kryo 260 Gold are Cortex-A73. Both
predate ARMv8.2, and `ID_AA64MMFR0_EL1.TGran16` reads 0 on an A53: the hardware
cannot map 16 KB pages at all.

iOS 16's arm64 userland is compiled for 16 KB pages. So this is not a matter of
leaving the small cores idle — **every** core has to run under a 4 KB-page
kernel, which changes the kernel build and the shared-cache mapping. UniXNU and
the Redmi Note 12 port are the two that have done this.

## What works today

```bash
python3 tools/unpack_bootv2.py backup/boot.img dtb/boot_unpacked
MKBOTIMG_PY=/path/to/mkbootimg.py ./shim/build.sh
python3 tools/parse_bootimg.py shim/out/shim-boot.img   # -> LAYOUT OK
fastboot boot shim/out/shim-boot.img
```

Nothing is flashed. The probe draws onto the framebuffer the bootloader leaves
behind and prints what the board actually offers:

| Printed | What it settles |
| --- | --- |
| `MEM base_lo/base_hi`, `MEM size_lo/size_hi` | `/memory` from the live FDT — whether the ADT's claimed DRAM window matches the phone |
| `TG16` | `ABSENT: kernel must use 4K pages` (expected) or `supported` |
| `PARANGE`, `GRANULE`, `MMU rc` | Whether the 4 KB table walk runs on this core |
| `PAR gic` | Whether `0x0f200000` is reachable |
| `PSCI`, `SMCCC` | Which PSCI calls the Qualcomm TZ offers |
| GIC timer interrupt count | Whether Group 1 IRQ works with INTID 19 at 19.2 MHz |

## Hardware map

Every address below came from the device tree, and every one is a place where
copying a value from a sweet port produces a silent hang rather than an error.

| Fact | ginkgo | sweet (for contrast) |
| --- | --- | --- |
| GIC distributor | `0x0f200000` | `0x17a00000` |
| GIC redistributor | `0x0f300000`, stride `0x20000` | `0x17a60000` |
| Framebuffer | `0x5c000000` (`cont_splash_region`, 15 MiB) | `0x9c000000` |
| Panel | 1080x2340, video mode | 1080x2400 |
| Storage | eMMC, `sdhci@4744000` | UFS, `ufshc@1d84000` |
| Touch | Focaltech FT8719 / Novatek NT36672A, **SPI** SE2 | Goodix GT9896, I²C |
| Power controller | **RPM** (`rpm-smd`) | RPMh |
| Cores | 4x A53 + 4x A73, ARMv8.0 | A55 + A76, ARMv8.2 |
| 16 KB pages | No | Yes |
| `pshold` | `0x0440b000` | `0x0c264000` |

The GIC address is the one most likely to be copied wrong, and it fails in the
least helpful way: kernel text appears, then nothing, because the timer
interrupt never arrives.

## Repository layout

| Path | What |
| --- | --- |
| `devices/ginkgo/profile.py` | The hardware map as data, with the device tree node behind each value |
| `devices/ginkgo/README.md` | The port's situation, blockers and order of work |
| `shim/board.h` | Per-board constants; ginkgo and sweet side by side |
| `shim/mmu.c` | Identity map at the board's granule: 4 KB (3 levels) or 16 KB (2 levels) |
| `shim/fdt.c` | Reads `/memory` from the live FDT instead of assuming it |
| `tools/mkadt_ginkgo.py` | Generates the Apple Device Tree XNU boots with |
| `tools/parse_bootimg.py` | Parses a boot image v2 header the way the bootloader does |
| `NOTES-ginkgo.md` | The active handoff: what is observed, what is still a guess |
| `NOTES-sweet.md` | Upstream's notes for the reference device, kept for context |

## Order of work

1. **Run the probe** and record what it prints. Everything below depends on those
   numbers being right.
2. **Decide on storage.** Write the SDHCI driver, or stop at "kernel boots to a
   panic log" and publish the hardware map as research. There is no third option
   that reaches a lock screen.
3. **4 KB-page XNU build**, following UniXNU and the Redmi Note 12 port.
4. **Touch**: the SPI protocol, then the RPM rail vote.
5. **Buttons**, then USB device mode for a live kernel log.

## Safety

- `fastboot boot` only. Nothing is written to `boot`, `dtbo` or `vbmeta`, so
  Android still starts after every attempt.
- Back up `persist`, `modemst1`, `modemst2`, `fsg` and `fsc` first. They hold
  per-device calibration that cannot be downloaded.
- An iOS root would eventually go into `userdata` and erase Android's data. That
  step has not been taken and needs an explicit decision.
- Apple's security model is off in these ports by construction: permissive AMFI,
  relaxed sandbox, a stub AppleKeyStore, no data protection. Do not put anything
  personal on a device running it.

## Credit and licence

MIT, inherited from `dipa-studio/ios-sweet`; see [`LICENSE`](LICENSE).

- Boot shim, ADT generator, XNU patch series, and the notes that made this port
  startable: [`dipa-studio/ios-sweet`](https://github.com/dipa-studio/ios-sweet)
- 4 KB-page kernel approach: UniXNU and the Redmi Note 12 4G port
- Hardware facts: Xiaomi's published kernel source for `trinket`/`ginkgo`
- XNU itself: Apple's open-source releases (APSL 2.0)

iOS is Apple's software and is not distributed here. No iOS binary, image,
cache, font or screenshot is in this repository; the system image is built on
your own machine from a firmware file you download from Apple.
