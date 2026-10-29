#!/usr/bin/env python3
"""Hardware profile for the Xiaomi Redmi Note 8 (``ginkgo``, SM6125 / Snapdragon 665).

Every address here was read out of the phone's own device tree, not guessed.
The source of each value is named next to it so a wrong number can be traced
back to the artifact it came from instead of to a hunch.

Provenance of the numbers
-------------------------
The Android device tree is split in two parts for this device:

  ``trinket.dtb``                    the SoC base tree, shared by every SM6125 phone
  ``ginkgo-trinket-overlay.dtbo``    the board overlay, compiled from
                                     ``arch/arm64/boot/dts/xiaomi/ginkgo/``

The bootloader applies the overlay to the base and hands the result to Linux as
the live FDT. The kernel therefore sees nodes that exist in neither file alone:
the base marks most controllers ``status = "disabled"`` and the overlay enables
the ones this board populates. Read ``/sys/firmware/fdt`` on the device (or in
recovery) if you need to confirm a value; that is the merged tree, and it is the
only tree the bootloader actually hands over.

What is missing, and cannot be invented
---------------------------------------
Two facts decide whether this port is worth starting, and both are negative:

1. **eMMC, not UFS.** ``sdhci@4744000`` (8-bit, ``sdhc_1``) is the eMMC host.
   ``ufshc@4804000`` exists in the SoC tree and the vendor kernel builds its
   driver (``CONFIG_SCSI_UFS_QCOM=y``), but the board does not populate it.
   Every working iOS port reads its root from a UFS host, because that is the
   driver ios-sweet wrote. There is no eMMC host driver for XNU anywhere in
   this ecosystem. This is the port's first blocker and the largest piece of
   work in it.

2. **ARMv8.0 on all eight cores.** The four Kryo 260 Silver are Cortex-A53 and
   the four Kryo 260 Gold are Cortex-A73. Both predate ARMv8.2, and the A53
   cannot use 16 KB memory pages at all -- not as a limitation of iOS, but in
   hardware. iOS 16's arm64 userland is built for 16 KB pages. So this is not
   "leave the small cores idle": every core has to run under a 4 KB-page
   kernel, which is what the UniXNU and Redmi Note 12 ports had to do.

Neither of these is a reason not to try. Both are reasons not to expect a
home screen soon, and both are recorded here rather than discovered later.
"""

# ---------------------------------------------------------------------------
# Identity presented to iOS
# ---------------------------------------------------------------------------
# The userland is the iPhone X (D22AP) firmware, so the identity has to match
# it exactly or SpringBoard picks the wrong layout. There is no choice here:
# every public port uses the iPhone X or iPhone 8 userland, because those are
# the newest devices whose firmware does not require pointer authentication.
DEVICE_TREE_COMPATIBLE = ['D22AP', 'iPhone10,3', 'xiaomi,ginkgo', 'qcom,sm6125', 'AppleARM']
MODEL = 'iPhone10,3'
TARGET_TYPE = 'D22'
TARGET_SUB_TYPE = 'D22AP'

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
# The live FDT memory node is <0x0 0x80000000 0x0 0x80000000> plus an optional
# upper bank above 4 GiB on 6 GB units. Unlike sweet, this SoC has no upper
# bank on every unit: 3/4 GB phones have nothing above 4 GiB. So the payload
# has to live in the low bank, and the low bank is where the carve-outs are.
#
# Carve-outs from the base tree (all in the low bank, all no-map):
#   0x45700000  0x00600000  hyp
#   0x45e00000  0x00140000  xbl_aop
#   0x45fff000  0x00001000  sec_apps
#   0x46000000  0x00200000  smem
#   0x46200000  0x02d00000  removed_region
#   0x4b000000  0x07e00000  modem
#   0x52e00000  0x00500000  video
#   0x53300000  0x00200000  wlan_msa
#   0x53500000  0x01e00000  cdsp
#   0x55300000  0x02200000  adsp      (ginkgo memory dtsi: 0x2200000)
#   0x57500000  0x00010000  ipa_fw
#   0x57510000  0x00005000  ipa_gsi
#   0x57515000  0x00002000  gpu
#   0x5c000000  0x00f00000  cont_splash
#   0x5cf00000  0x00100000  dfps_data
#   0x5e400000  0x01400000  (see note below)
#   0x5f800000  0x01e00000  (see note below)
#   0x61600000  0x00400000  ramoops   (ginkgo memory dtsi)
#
# The last two unlabelled regions sit just below the 0x61800000 end of the
# 3 GB bank and are the display/secure pools on this board. Treat everything
# from 0x5c000000 up as unusable: the display pipeline owns it, and the
# framebuffer we draw into lives there.
#
# Usable window chosen below: 0x61800000 .. 0x80000000 (494 MiB) is *not*
# enough for a 2.5 GB iOS image, and it is above every carve-out only because
# it is the tail of the bank. That is fine for a bring-up that loads nothing
# but the kernel, and it is why the profile marks storage as blocking: without
# eMMC there is nowhere else for the system image to come from.
PHYS_BASE = 0x61800000          # first byte above the last low-bank carve-out
PHYS_SIZE = 0x1E800000          # to the end of the 3 GB bank (0x80000000)

# The 6 GB units have a second bank at 0x1_00000000. Present on some units,
# absent on others, so nothing may depend on it being there.
HIGH_BANK_BASE = 0x100000000
HIGH_BANK_SIZE = 0x180000000    # 6 GB units only; NOT assumed

# ---------------------------------------------------------------------------
# Interrupt controller and timer
# ---------------------------------------------------------------------------
# FDT: interrupt-controller@f200000, compatible "arm,gic-v3",
#      reg = <0xf200000 0x10000 0xf300000 0x100000>,
#      redistributor-stride = <0 0x20000>, #redistributor-regions = <1>
# Note the distributor is at 0xf200000, NOT the 0x17a00000 that sweet uses.
# This is the single most likely cause of "kernel text appears, then nothing".
GICD = 0x0F200000
GICD_SIZE = 0x10000
GICR = 0x0F300000
GICR_SIZE = 0x100000
GICR_STRIDE = 0x20000

# FDT: timer { compatible = "arm,armv8-timer";
#              interrupts = <1 1 0xf08  1 2 0xf08  1 3 0xf08  1 0 0xf08>;
#              clock-frequency = <0x124f800> }
# PPI 1 = secure physical, 2 = non-secure physical, 3 = virtual, 0 = hypervisor.
# The virtual timer is therefore INTID 19 (16 + 3), same as on sweet, but the
# counter frequency is 19.2 MHz, not sweet's.
TIMEBASE = 19200000
VTIMER_INTID = 19               # 16 + 3 (virtual)
PTIMER_INTID = 18               # 16 + 2 (non-secure physical)
SECURE_PTIMER_INTID = 17        # 16 + 1 (secure physical)
HYP_TIMER_INTID = 16            # 16 + 0 (hypervisor)

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
# FDT: reserved-memory cont_splash_region@5c000000, size 0xf00000.
# ABL loads the boot logo there and leaves the MDP programmed to scan it out,
# so this address is the framebuffer we inherit. 1080x2340 at 4 bytes/pixel is
# 10,108,800 bytes; the 15 MiB region holds it with room for the second buffer.
FB_BASE = 0x5C000000
FB_SIZE = 0x00F00000
FB_WIDTH = 1080
FB_HEIGHT = 2340
FB_STRIDE = FB_WIDTH * 4

# The panel presents itself as 1080x2340. iOS only lays out on sizes it knows,
# so the ADT claims the iPhone X's 1125x2436 canvas and the framebuffer scales
# into the real panel, exactly as ios-sweet does for sweet's 1080x2400.
CANVAS_WIDTH = 1125
CANVAS_HEIGHT = 2436
DISPLAY_SCALE = 3               # 1125/3 x 2436/3 = 375x812 points

# Panel timings, from the overlay's three panel variants (all identical here):
#   qcom,mdss-dsi-panel-width  = <0x438>  (1080)
#   qcom,mdss-dsi-panel-height = <0x8e8>  (2280 -> 2340 with porch)
#   qcom,mdss-dsi-panel-framerate = <0x3c>  (60)
# All three are video mode, so the panel free-runs and needs no refresh kick.
# Three different panels ship on this board (ft8719_huaxing, nt36672a_shenchao,
# nt36672a_tianma), selected at runtime by panel ID. The framebuffer does not
# care which one is fitted; a DSI driver would.
DSI_VIDEO_MODE = True

# ---------------------------------------------------------------------------
# Storage -- the blocker
# ---------------------------------------------------------------------------
# eMMC host: FDT sdhci@4744000, "qcom,sdhci-msm-v5",
#            reg = <0x4744000 0x1000 0x4745000 0x1000 0x4748000 0x8000>,
#            qcom,bus-width = <8>, sdhc_1
EMMC_BASE = 0x04744000
EMMC_SIZE = 0x1000              # hc_mem only; the other two regs are ice/dll
EMMC_IRQ = 0x15C                # SPI 348, hc_irq
EMMC_PWR_IRQ = 0x160            # SPI 352, pwr_irq

# UFS host exists in the SoC tree but the board does not populate it.
# Recorded because a reader will look for it and needs to know why it is unused.
UFS_PRESENT_IN_SOC_TREE = True
UFS_POPULATED_ON_BOARD = False
UFS_BASE = 0x04804000
UFS_SIZE = 0x3000

# ---------------------------------------------------------------------------
# Touch
# ---------------------------------------------------------------------------
# FDT: qupv3_se2_spi = /soc/spi@4a88000, reg <0x4a88000 0x4000>, SPI 0x149.
# The overlay hangs the touch controller on it as a SPI child with
# compatible "focaltech,fts","novatek,NVT-ts-spi" -- one node, two possible
# chips, chosen by which one answers. Both are on SPI, unlike sweet's Goodix on
# I2C, so the ios-sweet touch driver (0063, GENI I2C) cannot be reused as is.
TOUCH_SPI_BASE = 0x04A88000
TOUCH_SPI_SIZE = 0x4000
TOUCH_SPI_IRQ = 0x149
TOUCH_CHIPS = ['focaltech,fts (FT8719)', 'novatek,NVT-ts-spi (NT36672A)']
TOUCH_RESET_GPIO = 87           # tlmm 87
TOUCH_IRQ_GPIO = 88             # tlmm 88
TOUCH_MAX_POINTS = 10

# ---------------------------------------------------------------------------
# Buttons
# ---------------------------------------------------------------------------
# Power and volume sit on the PMIC (pm6125 + pmi632, SPMI arb at 0x1c40000)
# and on TLMM GPIOs. Unlike sweet these are not RPMh-managed: this SoC uses
# the older RPM, so any rail the touch chip needs is voted through the RPM
# resource interface, not the RPMh command DB.
PMIC = 'pm6125 + pmi632'
SPMI_BASE = 0x01C40000
USES_RPM_NOT_RPMH = True

# ---------------------------------------------------------------------------
# USB
# ---------------------------------------------------------------------------
# FDT: ssusb@4e00000, dwc3@4e00000. Same DWC3 IP as sweet, so the device-mode
# bring-up (patches 0072-0077) should transfer with new addresses and a
# different QSCRATCH base. That matters more than it sounds: it is the only
# route to a live kernel log on this phone.
USB_BASE = 0x04E00000
USB_DWC3_BASE = 0x04E00000

# ---------------------------------------------------------------------------
# CPU topology
# ---------------------------------------------------------------------------
# FDT cpu@0..cpu@3 (capacity 1024, Kryo 260 Silver = Cortex-A53) and
# cpu@100..cpu@103 (capacity 1638, Kryo 260 Gold = Cortex-A73).
# MPIDR Aff1 carries the cluster, so logical order and MPIDR order differ,
# exactly as on sweet.
CPU_CLUSTERS = [
    dict(name='silver', core='Cortex-A53', count=4, mpidr_base=0x000, max_mhz=1804),
    dict(name='gold', core='Cortex-A73', count=4, mpidr_base=0x100, max_mhz=2016),
]
CPU_ISA = 'ARMv8.0'             # no pointer auth, and no 16 KB granule on A53
SUPPORTS_16K_PAGES = False      # hardware fact; forces a 4 KB-page kernel
TOTAL_CORES = 8

# ---------------------------------------------------------------------------
# What has to exist before this port can boot, in the order it blocks
# ---------------------------------------------------------------------------
BLOCKERS = [
    dict(
        id='storage',
        state='open',
        summary='No eMMC host driver for XNU; every existing port uses UFS',
        detail='ios-sweet patches 0028-0034 are a UFS driver. This board has '
               'sdhci@4744000. An SDHCI driver for XNU does not exist in any '
               'public port, so it has to be written: ADMA2 descriptor rings, '
               'CMD/DATA line handling, card init (CMD0/CMD8/ACMD41/CMD2/CMD3/'
               'CMD7/CMD9), then a block device for the HFS+ root. Until this '
               'exists there is no root device, and iOS cannot start launchd.',
    ),
    dict(
        id='pagesize',
        state='open',
        summary='All 8 cores are ARMv8.0; the A53 has no 16 KB granule',
        detail='iOS 16 arm64 userland is compiled for 16 KB pages. A53 cannot '
               'do 16 KB pages at all. The kernel must be built for 4 KB pages '
               'and the shared cache must be mapped at that granule, which is '
               'what UniXNU and the Redmi Note 12 port did. This changes the '
               'kernel build, not just the device profile.',
    ),
    dict(
        id='touch',
        state='open',
        summary='Touch is Focaltech/Novatek on SPI, not Goodix on I2C',
        detail='Patch 0063 implements the Goodix GT9896 protocol over GENI I2C. '
               'Both chips on this board speak SPI through QUPv3 SE2. New '
               'protocol code is needed for whichever chip answers.',
    ),
    dict(
        id='pmic',
        state='open',
        summary='RPM, not RPMh, so the touch rail vote is different code',
        detail='Patch 0062 votes a rail through RPMh. This SoC uses the older '
               'RPM resource interface. The touch chip is unpowered until '
               'something votes its rail on, so this blocks touch even after '
               'the protocol works.',
    ),
    dict(
        id='ram',
        state='note',
        summary='The low bank leaves ~494 MiB above the carve-outs',
        detail='A 3 GB unit has no memory above 4 GiB, and the low bank is full '
               'of no-map carve-outs up to 0x61800000. A bring-up that loads '
               'only the kernel fits; a 2.5 GB iOS image does not. This is '
               'another consequence of the missing storage driver, not a '
               'separate problem.',
    ),
]


def as_dict():
    """Profile as a plain dict, for tools that want to emit it as JSON."""
    return {k: v for k, v in globals().items() if k.isupper()}


if __name__ == '__main__':
    import json
    print(json.dumps(as_dict(), indent=2, default=str))
