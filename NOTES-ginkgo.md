# ginkgo (Redmi Note 8, SM6125) — working notes

This file is the handoff for this port. Upstream's notes for `sweet` are in
`NOTES-sweet.md`; read them when you need the reference device's history, and
keep reading this one for anything about ginkgo.

## State at end of session 1

**Nothing has run on hardware. No image has been booted on the phone.**

### Done and verified locally

| Item | Evidence |
| --- | --- |
| Hardware map | Every address traced to a device tree node; see `devices/ginkgo/profile.py` and `devices/ginkgo/README.md` |
| `shim/board.h` | ginkgo and sweet blocks; both compile |
| `shim/mmu.c` | 4 KB walk (3 levels) and 16 KB walk (2 levels); both compile |
| `shim/fdt.c` | `fdt_memory_base_size()` added, reads `/memory` from the live FDT |
| `shim/shim.c` | Board constants come from `board.h`; UFS probe compiled out on ginkgo; probe prints `/memory`, granule and TG16 |
| `shim/build.sh` | Builds end to end; `out/shim-boot.img` is 565,248 B |
| Boot image layout | `tools/parse_bootimg.py` reports LAYOUT OK; DTB byte-identical to the source, ramdisk gzip at `0x38000`, DTB at `0x39000` |
| `tools/mkadt_ginkgo.py` | Emits a 9,900 B ADT; 8 cores with MPIDR `0x000-0x003` and `0x100-0x103`, GIC absolute `0xf200000`, no storage node |

### Not started

- XNU kernel build. **Needs a 4 KB-page build**, which is a change to the kernel
  configuration and the shared-cache mapping, not just to the ADT.
- SDHCI/eMMC driver for XNU. Nothing exists to port from.
- Touch (SPI), PMIC rail vote (RPM), buttons, USB device mode.
- `tools/qemu-ginkgo.py`. Upstream's `qemu-sweet.py` is untested here; the ADT
  has a `--qemu` path but nobody has run it.

### The two blockers, in the order they bite

1. **No eMMC driver for XNU.** `sdhci@4744000` is the storage. Every working port
   uses UFS because ios-sweet wrote a UFS driver. Without an eMMC driver there
   is no root device, so `launchd` cannot start. This is the largest piece of
   work in the port and the one that decides whether it can reach a lock screen.
2. **4 KB pages are mandatory.** All eight cores are ARMv8.0 and the A53 has no
   TGran16. The shim side is done; the kernel side is not.

## Next concrete action

**Run the hardware probe.** It is the only way to confirm the numbers the rest
of the port depends on, and it needs no kernel and no storage driver.

```bash
# 1. Get the stock DTB out of your own boot.img (not in this repo).
python3 tools/unpack_bootv2.py backup/boot.img dtb/boot_unpacked

# 2. Build the probe.
MKBOTIMG_PY=/path/to/mkbootimg.py ./shim/build.sh

# 3. Check the header before trusting it.
python3 tools/parse_bootimg.py shim/out/shim-boot.img

# 4. Boot it once, from RAM, flashing nothing.
fastboot boot shim/out/shim-boot.img
```

Then record, verbatim, the lines the probe prints. What each one settles:

| Line | What it settles |
| --- | --- |
| `MEM base_lo/base_hi`, `MEM size_lo/size_hi` | Whether `profile.PHYS_BASE`/`PHYS_SIZE` match the phone. If they do not, the ADT is wrong and the kernel would allocate over a carve-out. |
| `TG16` | `ABSENT` means the 4 KB kernel build is mandatory. This is expected. |
| `PARANGE`, `GRANULE`, `MMU rc` | Whether the 4 KB table walk actually runs on this core. |
| `PAR gic` | Whether `0x0f200000` is mapped and reachable. |
| `PSCI ver`, `SMCCC ver` | Which PSCI calls the Qualcomm TZ offers, which decides how secondaries start. |
| GIC timer interrupt count | Whether Group 1 IRQ delivery works with INTID 19 at 19.2 MHz. |

If the screen stays on the bootloader logo, the framebuffer address is wrong
before anything else can be blamed. If text appears and the phone resets, the
watchdog is still armed or the image overlaps a carve-out.

## Observations vs guesses

Recorded because the distinction matters when reading this file later.

**Observed (from artifacts):**
- `sdhci@4744000` is 8-bit and `sdhc_1`; `sdhci@4784000` is 4-bit with a
  `cd-gpios` on TLMM 98 and is the microSD slot.
- `ufshc@4804000` exists in `trinket.dtsi`, is `non-removable`, and is
  `status = "disabled"` in the base tree; the board overlay does not enable it.
- `CONFIG_SCSI_UFS_QCOM=y` in `vendor/ginkgo-perf_defconfig`, i.e. the vendor
  kernel builds a driver for a controller this board does not use.
- The GIC node is `interrupt-controller@f200000` with `redistributor-stride`
  `0x20000`, and `0x17a00000` appears zero times in the merged tree.
- `timer { clock-frequency = <0x124f800> }` = 19,200,000.
- Panel nodes declare 1080x2340 at 60 fps, video mode, three variants.
- Touch hangs off `spi@4a88000` (QUPv3 SE2) with two possible chips.

**Guesses (not confirmed on hardware):**
- That `PHYS_BASE = 0x61800000` is the first usable byte above the low-bank
  carve-outs. The unlabelled regions at `0x5e400000` and `0x5f800000` were
  treated as display/secure pools because they sit directly below the end of the
  3 GB bank; that interpretation is inferred from position, not from a label.
  The probe prints the real `/memory` node so this can be checked.
- That the DRAM base is `0x80000000`. Nothing in the trees read says so
  explicitly, and the carve-outs at `0x45700000` mean the first usable byte is
  not the base either. This is exactly why `fdt_memory_base_size()` exists.
- That the bootloader leaves `cont_splash_region` scanning out on this board.
  It is how every other Qualcomm port behaves and the region exists, but nobody
  has looked at the phone.
- That QUPv3 SE2 is powered and usable for touch without an RPM vote.

## Decisions taken

- **Base is `dipa-studio/ios-sweet` (MIT), not HackiOS.** ios-sweet is smaller,
  has no UEFI layer, and its notes are a day-by-day log of what each failure
  looked like — which is more useful for a board nobody has done than a more
  complete port whose device assumptions are further from this one.
- **A separate `mkadt_ginkgo.py` rather than editing `mkadt.py`.** Upstream's
  file is the reference for sweet and will keep changing; a copy that names its
  provenance can be diffed against it when upstream moves.
- **No storage node in the ADT.** Emitting `sweet-ufs`-style node would let the
  kernel match a driver that cannot work here, turning "no root device" into a
  crash somewhere less obvious.
- **`fastboot boot` only.** Nothing is flashed. `userdata` is untouched, so
  Android still boots after every attempt.
- **Board selection at compile time** (`-DBOARD_GINKGO`), not runtime. A 16 KB
  kernel image cannot be fixed up into a 4 KB one at boot, so the granule has to
  be a build-time fact.

## Credit

Device tree, overlay and kernel facts come from Xiaomi's published kernel source
for `trinket`/`ginkgo`. The port structure, the ADT generator, the shim and the
patch series are `dipa-studio/ios-sweet` (MIT). The 4 KB-page approach is
UniXNU's and the Redmi Note 12 port's. iOS itself is Apple's and is not
distributed here.
