/*
 * Per-board constants for the shim.
 *
 * Everything the shim needs to know about a specific phone lives here, so that
 * "port this to another device" is a matter of adding a block rather than
 * editing the driver and MMU code. The values themselves are documented in
 * devices/<name>/profile.py; this header is the compiled form of the subset the
 * shim touches before it can print anything.
 *
 * Select with -DBOARD_GINKGO or -DBOARD_SWEET. Default is ginkgo, because this
 * repository is the ginkgo port; sweet is kept so the shim can still be built
 * for the reference device and compared against upstream.
 */
#pragma once

#if defined(BOARD_SWEET)

/* Redmi Note 10 Pro (sweet, SM7150) -- the upstream reference device. */
#define BOARD_NAME		"sweet"
#define BOARD_SOC		"sm7150"

#define BOARD_FB_BASE		0x9c000000UL	/* cont_splash_region */
#define BOARD_FB_SIZE		0x1700000UL
#define BOARD_FB_W		1080
#define BOARD_FB_H		2400

#define BOARD_GICD		0x17a00000UL
#define BOARD_GICR		0x17a60000UL
#define BOARD_GICR_STRIDE	0x20000UL

#define BOARD_TIMEBASE		19200000UL	/* CNTFRQ */
#define BOARD_VTIMER_INTID	19		/* DT: <GIC_PPI 3 ...> */

#define BOARD_IMEM_RESTART	0x146aa65cUL
#define BOARD_PSHOLD		0x0c264000UL

#define BOARD_HAS_UFS		1
#define BOARD_UFS_BASE		0x01d84000UL
#define BOARD_UFS_SIZE		0x3000UL

/* 16K granule: all cores are ARMv8.2 and support TGran16. */
#define BOARD_GRANULE_4K	0

#elif defined(BOARD_GINKGO) || 1

/*
 * Redmi Note 8 (ginkgo, SM6125 / Snapdragon 665).
 *
 * Two values here are the ones most likely to be wrong if someone re-derives
 * them from memory instead of from the device tree, and both would show up as
 * "kernel text appears, then nothing":
 *
 *   - the GIC distributor is at 0x0f200000, not the 0x17a00000 used by every
 *     SM7xx/SM8xx board. The redistributor is 0x0f300000 with a 0x20000 stride.
 *   - the framebuffer is the board's cont_splash_region at 0x5c000000, which is
 *     inside the low DRAM bank, not a separate high carve-out.
 */
#define BOARD_NAME		"ginkgo"
#define BOARD_SOC		"sm6125"

#define BOARD_FB_BASE		0x5c000000UL	/* cont_splash_region@5c000000 */
#define BOARD_FB_SIZE		0x00f00000UL	/* 15 MiB */
#define BOARD_FB_W		1080
#define BOARD_FB_H		2340

#define BOARD_GICD		0x0f200000UL	/* interrupt-controller@f200000 */
#define BOARD_GICR		0x0f300000UL
#define BOARD_GICR_STRIDE	0x20000UL

#define BOARD_TIMEBASE		19200000UL	/* timer clock-frequency */
#define BOARD_VTIMER_INTID	19		/* DT: <GIC_PPI 3 ...> = 16 + 3 */

#define BOARD_IMEM_RESTART	0x146aa65cUL	/* msm-imem restart_reason@65c */
#define BOARD_PSHOLD		0x0440b000UL	/* restart@440b000, "qcom,pshold" */

/*
 * The SoC tree has ufshc@4804000 and the vendor kernel builds the driver, but
 * this board does not populate it: storage is eMMC on sdhci@4744000. The shim
 * has no UFS code to run, and a UFS probe would touch a controller that is not
 * there. Set to 0 and let the eMMC path be written separately.
 */
#define BOARD_HAS_UFS		0

/* All eight cores are ARMv8.0 (4x A53 + 4x A73); the A53 has no TGran16. */
#define BOARD_GRANULE_4K	1

#endif

/* Derived, not per-board: the two cannot disagree if they come from one place. */
#define BOARD_FB_STRIDE		(BOARD_FB_W * 4)	/* a8r8g8b8 */
