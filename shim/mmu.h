#pragma once
#include <stdint.h>
#include "board.h"

/* Splash framebuffer inherited from the bootloader (per-board, see board.h). */
#define FB_PHYS	BOARD_FB_BASE

struct mmu_info {
	uint64_t img_lo, img_hi, ttbr;
	uint64_t sctlr_before, sctlr_after;
	int n_l3;
	uint64_t granule;	/* page size the tables were built for */
};

int mmu_enable(struct mmu_info *info);
uint64_t mmu_probe(uintptr_t va);

/*
 * Does this core implement the 16K granule? 0 means it does not, and an XNU
 * built for 16K pages cannot run here. Reported at boot because it is the
 * single fact that decides whether the kernel build has to change.
 */
int mmu_granule_16k(void);
