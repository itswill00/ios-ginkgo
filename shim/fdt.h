#pragma once
#include <stdint.h>

/* Read a u32/u64 (cell-size agnostic) property of /chosen. Returns 0 if absent. */
int fdt_chosen_u64(uintptr_t fdt, const char *prop, uint64_t *out);

/*
 * Read the first <base size> pair of /memory's reg property. Returns 1 on
 * success, 0 if the node or property is missing.
 *
 * This exists because the base of DRAM is not something to hardcode. On this
 * SoC family the reserved-memory carve-outs (smem at 0x46000000, hyp at
 * 0x45700000) sit well below 0x80000000, which means the first usable byte is
 * not where a reader would guess, and a wrong guess makes the kernel allocate
 * over a region the bootloader still owns. ABL writes the real values into
 * /memory before handing over, so read them instead of assuming.
 *
 * reg is <base size> in cells whose width is given by the node's own
 * #address-cells/#size-cells (2/2 on every Qualcomm arm64 board so far, but
 * the widths are read rather than assumed).
 */
int fdt_memory_base_size(uintptr_t fdt, uint64_t *base, uint64_t *size);
