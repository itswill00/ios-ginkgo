/*
 * EL1 stage-1 MMU, identity mapped (VA == PA).
 *
 * Two granules, chosen at compile time by BOARD_GRANULE_4K:
 *
 *   16K (sweet)   T0SZ=28 -> 36-bit VA, walk starts at level 2, one table of
 *                 2048 x 32MB blocks covers 64GB.
 *   4K  (ginkgo)  T0SZ=25 -> 39-bit VA, walk starts at level 1, one table of
 *                 512 x 1GB blocks covers 512GB.
 *
 * The 4K mode is not a preference. The A53 and A73 on SM6125 are ARMv8.0 and
 * the A53 has no 16K granule at all, so a 16K mapping faults on that core and
 * an XNU built for 16K pages cannot run on it. Everything downstream -- the
 * kernel build and the shared-cache mapping -- has to follow the granule the
 * hardware actually offers, which is why this is a compile-time choice and not
 * a runtime fallback: a 16K kernel image cannot be fixed up at boot.
 *
 * Qualcomm XPUs fault on speculative reads of protected carve-outs (TZ, hyp,
 * modem...), so nothing is mapped cacheable except our own image:
 *   - default: Device-nGnRnE, execute-never (same as MMU off)
 *   - the block(s) holding the image get page tables: image pages are
 *     Normal write-back, the rest of the block stays Device
 *   - the splash framebuffer block is Normal non-cacheable (write-combining)
 */
#include <stdint.h>
#include "mmu.h"
#include "board.h"

#if BOARD_GRANULE_4K

#define PG_SHIFT	12
#define NENT		512			/* entries per table, 4K granule */
#define BLK_SHIFT	30			/* level-1 block = 1GB */
#define BLK_SIZE	(1UL << BLK_SHIFT)
#define T0SZ		25			/* 39-bit VA, start at level 1 */
#define TCR_TG0		0UL			/* 4K */
#define N_BLK		512			/* 512GB of identity map */
#define MAX_L3		16			/* 16 x 2MB = 32MB of image */

#else

#define PG_SHIFT	14
#define NENT		2048			/* entries per table, 16K granule */
#define BLK_SHIFT	25			/* level-2 block = 32MB */
#define BLK_SIZE	(1UL << BLK_SHIFT)
#define T0SZ		28			/* 36-bit VA, start at level 2 */
#define TCR_TG0		2UL			/* 16K */
#define N_BLK		256			/* 8GB of identity map */
#define MAX_L3		2

#endif

#define PG_SIZE		(1UL << PG_SHIFT)

#define ATTR_DEV	0	/* MAIR attr0 = 0x00 Device-nGnRnE */
#define ATTR_WB		1	/* MAIR attr1 = 0xff Normal WB RW-alloc */
#define ATTR_NC		2	/* MAIR attr2 = 0x44 Normal non-cacheable */
#define MAIR_VAL	0x44ff00UL

#define D_BLOCK		1UL
#define D_TABLE		3UL
#define D_PAGE		3UL
#define D_ATTR(i)	((uint64_t)(i) << 2)
#define D_SH_OUTER	(2UL << 8)
#define D_SH_INNER	(3UL << 8)
#define D_AF		(1UL << 10)
#define D_PXN		(1UL << 53)
#define D_UXN		(1UL << 54)

#define DEV_FLAGS	(D_ATTR(ATTR_DEV) | D_AF | D_PXN | D_UXN)
#define WB_FLAGS	(D_ATTR(ATTR_WB) | D_SH_INNER | D_AF | D_UXN)
#define NC_FLAGS	(D_ATTR(ATTR_NC) | D_SH_OUTER | D_AF | D_PXN | D_UXN)

/* TCR: T0SZ, IRGN0/ORGN0=WBWA, SH0=inner, TG0 as selected, EPD1, IPS=36 bit */
#define TCR_VAL		((uint64_t)T0SZ | (1UL << 8) | (1UL << 10) | (3UL << 12) | \
			 (TCR_TG0 << 14) | ((uint64_t)T0SZ << 16) | (1UL << 23) | \
			 (1UL << 30) | (1UL << 32))

#define SCTLR_M		(1UL << 0)
#define SCTLR_A		(1UL << 1)
#define SCTLR_C		(1UL << 2)
#define SCTLR_I		(1UL << 12)
#define SCTLR_WXN	(1UL << 19)

#define rsr(r) ({ uint64_t _v; __asm__ volatile("mrs %0, " r : "=r"(_v)); _v; })
#define wsr(r, v) __asm__ volatile("msr " r ", %0" : : "r"((uint64_t)(v)))

extern char _head[], _end[];

/*
 * One level-1 (or level-2) table plus up to MAX_L3 page tables. Each table is
 * one page of its own granule; the extra page is slack for runtime alignment.
 */
static uint64_t pt_pool[1 + MAX_L3 + 1][NENT] __attribute__((aligned(4096)));

static void dcache_inval_range(uintptr_t start, uintptr_t end)
{
	uint64_t line = 4UL << ((rsr("ctr_el0") >> 16) & 0xf);

	for (uintptr_t a = start & ~(line - 1); a < end; a += line)
		__asm__ volatile("dc ivac, %0" : : "r"(a) : "memory");
	__asm__ volatile("dsb sy" ::: "memory");
}

static void zero_table(uint64_t *t)
{
	for (int i = 0; i < NENT; i++)
		t[i] = 0;
}

/* Which granule does this core actually implement? */
int mmu_granule_16k(void)
{
	/* ID_AA64MMFR0_EL1.TGran16 = bits 23:20; 0b0001 means 16K is supported. */
	return ((rsr("id_aa64mmfr0_el1") >> 20) & 0xf) == 1;
}

int mmu_enable(struct mmu_info *info)
{
	uintptr_t img_lo = (uintptr_t)_head & ~(PG_SIZE - 1);
	uintptr_t img_hi = ((uintptr_t)_end + PG_SIZE - 1) & ~(PG_SIZE - 1);
	uintptr_t pool = (uintptr_t)pt_pool;
	uint64_t *l1 = (uint64_t *)pool;
	int n_l3 = 0;

	info->img_lo = img_lo;
	info->img_hi = img_hi;
	info->ttbr = pool;
	info->granule = PG_SIZE;

	/* Default: everything Device, execute-never. */
	zero_table(l1);
	for (uint64_t i = 0; i < N_BLK; i++)
		l1[i] = (i << BLK_SHIFT) | DEV_FLAGS | D_BLOCK;

	/* The splash framebuffer is scanned out, so it must not be Device. */
	l1[BOARD_FB_BASE >> BLK_SHIFT] =
		(BOARD_FB_BASE & ~(BLK_SIZE - 1)) | NC_FLAGS | D_BLOCK;

	/*
	 * Page-granular mapping for the blocks that hold our image.
	 *
	 * 16K: the image occupies at most two 32MB blocks, and a level-3 table
	 *      per block is all that is needed (one extra level).
	 * 4K:  the image occupies at most MAX_L3 2MB chunks, and each needs a
	 *      level-2 table to point at a level-3 table (two extra levels).
	 */
#if BOARD_GRANULE_4K
	uint64_t blk_lo = img_lo >> BLK_SHIFT, blk_hi = (img_hi - 1) >> BLK_SHIFT;
	if (blk_hi - blk_lo > 1)
		return -1;			/* one L2 table per 1GB block */
	for (uint64_t blk = blk_lo; blk <= blk_hi; blk++) {
		uint64_t *l2 = (uint64_t *)pt_pool[1];
		if (blk != blk_lo)
			l2 = (uint64_t *)pt_pool[1 + MAX_L3 - 1];
		zero_table(l2);
		for (int i = 0; i < NENT; i++)
			l2[i] = ((blk << BLK_SHIFT) + ((uint64_t)i << 21)) |
				DEV_FLAGS | D_BLOCK;
		/* Now split the 2MB chunks that hold the image into 4K pages. */
		uint64_t sub_lo = img_lo >> 21, sub_hi = (img_hi - 1) >> 21;
		for (uint64_t sub = sub_lo; sub <= sub_hi; sub++) {
			if (n_l3 >= MAX_L3)
				return -1;
			uint64_t *l3 = (uint64_t *)pt_pool[2 + n_l3++];
			uint64_t base = sub << 21;
			for (int i = 0; i < NENT; i++) {
				uint64_t pa = base + ((uint64_t)i << PG_SHIFT);
				int ours = pa >= img_lo && pa < img_hi;
				l3[i] = pa | (ours ? WB_FLAGS : DEV_FLAGS) | D_PAGE;
			}
			l2[sub & (NENT - 1)] = (uintptr_t)l3 | D_TABLE;
		}
		l1[blk] = (uintptr_t)l2 | D_TABLE;
	}
#else
	if (((img_hi - 1) >> BLK_SHIFT) - (img_lo >> BLK_SHIFT) > 1)
		return -1;	/* only room for two L3 tables */
	for (uint64_t blk = img_lo >> BLK_SHIFT; blk <= (img_hi - 1) >> BLK_SHIFT; blk++) {
		uint64_t *l3 = (uint64_t *)pt_pool[1 + n_l3++];
		uint64_t base = blk << BLK_SHIFT;
		for (int i = 0; i < NENT; i++) {
			uint64_t pa = base + ((uint64_t)i << PG_SHIFT);
			int ours = pa >= img_lo && pa < img_hi;
			l3[i] = pa | (ours ? WB_FLAGS : DEV_FLAGS) | D_PAGE;
		}
		l1[blk] = (uintptr_t)l3 | D_TABLE;
	}
#endif
	info->n_l3 = n_l3;

	/* Image lines may be stale in the cache from ABL; we wrote memory directly. */
	dcache_inval_range(img_lo, img_hi);
	__asm__ volatile("ic iallu; dsb sy; isb" ::: "memory");

	wsr("mair_el1", MAIR_VAL);
	wsr("tcr_el1", TCR_VAL);
	wsr("ttbr0_el1", pool);
	__asm__ volatile("isb; tlbi vmalle1; dsb nsh; isb" ::: "memory");

	uint64_t sctlr = rsr("sctlr_el1");
	info->sctlr_before = sctlr;
	sctlr &= ~(SCTLR_A | SCTLR_WXN);
	sctlr |= SCTLR_M | SCTLR_C | SCTLR_I;
	wsr("sctlr_el1", sctlr);
	__asm__ volatile("isb" ::: "memory");
	info->sctlr_after = rsr("sctlr_el1");
	return 0;
}

/* Translate a VA with AT S1E1R; returns PAR_EL1. */
uint64_t mmu_probe(uintptr_t va)
{
	__asm__ volatile("at s1e1r, %0; isb" : : "r"(va) : "memory");
	return rsr("par_el1");
}
