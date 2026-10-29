# ginkgo — Xiaomi Redmi Note 8 (SM6125 / Snapdragon 665)

Port of ios-sweet to the Redmi Note 8. This directory holds what the port needs
to know about the board; the code lives in `shim/` and `tools/`.

**Status: hardware probe only. Nothing boots iOS, and two blockers are open.**

## Read this before anything else

Two facts decide what this port can become, and both were established from the
phone's own device tree rather than assumed:

### 1. Storage is eMMC, and no XNU eMMC driver exists

`soc/sdhci@4744000` (8-bit, `sdhc_1`) is the eMMC host. The SoC tree also has
`ufshc@4804000` and the vendor kernel builds `CONFIG_SCSI_UFS_QCOM=y`, but this
board does not populate that controller — confirmed three ways: the base tree
marks every storage controller `status = "disabled"`, the board overlay enables
only `sdhc_2` (the microSD slot), and the public specification says eMMC 5.1.

Every working port in this ecosystem reads its root from a **UFS** host, because
ios-sweet wrote a UFS driver (patches 0028–0034). An SDHCI driver for XNU does
not exist in any public port. Writing one means ADMA2 descriptors, CMD/DATA
handling, card init, and a block device — and until it exists there is no root
device, so `launchd` cannot start and iOS cannot reach a lock screen.

This is the port's first blocker and the largest piece of work in it.

### 2. All eight cores are ARMv8.0, and the A53 has no 16 KB granule

Four Kryo 260 Silver are Cortex-A53, four Kryo 260 Gold are Cortex-A73. Both
predate ARMv8.2, and `ID_AA64MMFR0_EL1.TGran16` on an A53 reads 0 — the
hardware cannot map 16 KB pages at all.

iOS 16's arm64 userland is compiled for 16 KB pages. So this is not "leave the
small cores idle": **every** core has to run under a 4 KB-page kernel, which
changes the kernel build and the shared-cache mapping. UniXNU and the Redmi
Note 12 port are the two that have done this; both are worth reading before
starting.

The shim already handles the granule at compile time (`BOARD_GRANULE_4K` in
`shim/board.h`, and the 4 KB walk in `shim/mmu.c`), and the boot probe prints
what the core actually reports so the assumption is checked rather than trusted.

## What is done

| Piece | State |
| --- | --- |
| Hardware map | Complete, every value traced to a device tree node |
| `devices/ginkgo/profile.py` | Done, including the open blockers |
| `shim/board.h` | Done, ginkgo and sweet side by side |
| `shim/mmu.c` | Done, 4 KB and 16 KB granule, selected at compile time |
| `shim/fdt.c` | Done, reads `/memory` base and size from the live FDT |
| `shim/build.sh` | Done, builds and wraps a boot image; layout verified |
| `tools/parse_bootimg.py` | Done, checks the image header the way the bootloader reads it |
| `tools/mkadt_ginkgo.py` | Done, generates the ADT; no storage node on purpose |
| `shim` boot image | **Builds.** Not yet run on hardware |
| XNU kernel | Not started — needs a 4 KB-page build |
| SDHCI driver | Not started — the blocker |
| Touch / PMIC / buttons | Not started |

## Hardware facts worth keeping

Every one of these is a place where copying a value from a sweet port produces a
silent hang instead of an error:

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
| PMIC | pm6125 + pmi632 | PM6150 family |
| `pshold` | `0x0440b000` | `0x0c264000` |
| DRAM (low bank) | carve-outs to `0x61800000`; ~494 MiB usable above | upper bank above 4 GiB |

The GIC address is the one most likely to be copied wrong, and it fails in the
least helpful way: the kernel prints text and then stops, because the timer
interrupt never arrives.

## Building the probe

```bash
# The shim needs the stock DTB, which is not in this repository.
python3 tools/unpack_bootv2.py backup/boot.img dtb/boot_unpacked

# Build. MKBOTIMG_PY points at AOSP's mkbootimg.py if it is not in PATH.
MKBOTIMG_PY=/path/to/mkbootimg.py ./shim/build.sh

# Check the header the way the bootloader will read it.
python3 tools/parse_bootimg.py shim/out/shim-boot.img
```

Then, with the phone in fastboot:

```bash
fastboot boot shim/out/shim-boot.img
```

Nothing is flashed. The probe draws onto the screen the bootloader leaves behind
and prints:

- `/memory` base and size, read from the live FDT — compare against
  `profile.py`'s `PHYS_BASE`/`PHYS_SIZE`, because those are what the ADT claims
- `TG16`: `supported: 16K kernel ok` or `ABSENT: kernel must use 4K pages`
- `PARANGE`, and the MMU table setup at the board's granule
- `PSCI`/`SMCCC` versions, and the GIC Group 1 timer interrupt count

**The `TG16` line is the first real result.** If it says ABSENT, the 4 KB-page
kernel build is mandatory and the kernel work starts there.

## Order of work

1. **Run the probe.** Confirm the GIC base, `/memory`, granule and PSCI answers
   on the actual phone. Everything below depends on those being right.
2. **Decide on storage.** Either write the SDHCI driver, or stop at "kernel
   boots to a panic log" and publish the hardware map as research. There is no
   third option that reaches a lock screen.
3. **4 KB-page XNU build**, following UniXNU and the Redmi Note 12 port.
4. **Touch** (SPI protocol, then the RPM rail vote).
5. **Buttons**, then USB device mode for a live log.

## Safety

- `fastboot boot` only. Nothing is flashed to `boot`, `dtbo` or `vbmeta`.
- Back up `persist`, `modemst1`, `modemst2`, `fsg`, `fsc` before anything else;
  they hold per-device calibration that cannot be downloaded.
- The iOS root, when there is one, would go into `userdata` and erase Android's
  data. That step has not been taken and needs an explicit decision.
