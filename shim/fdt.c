/*
 * Just enough flattened-device-tree parsing to find what ABL put in
 * /chosen (initrd location) and what DRAM actually looks like (/memory).
 * Big-endian, 4-byte aligned tokens.
 */
#include "fdt.h"

#define FDT_MAGIC	0xd00dfeed
#define FDT_BEGIN_NODE	1
#define FDT_END_NODE	2
#define FDT_PROP	3
#define FDT_NOP		4
#define FDT_END		9

static uint32_t be32(uintptr_t a)
{
	return __builtin_bswap32(*(volatile uint32_t *)a);
}

static int streq(const char *a, const char *b)
{
	while (*a && *a == *b)
		a++, b++;
	return *a == *b;
}

static int streq_n(const char *a, const char *b, int n)
{
	for (int i = 0; i < n; i++)
		if (a[i] != b[i])
			return 0;
	return 1;
}

static uintptr_t align4(uintptr_t a)
{
	return (a + 3) & ~3UL;
}

static uintptr_t skip_str(uintptr_t p)
{
	/* byte loads are fine on Device memory as long as they are aligned to 1 */
	while (*(volatile char *)p)
		p++;
	return p + 1;
}

int fdt_chosen_u64(uintptr_t fdt, const char *prop, uint64_t *out)
{
	if (!fdt || be32(fdt) != FDT_MAGIC)
		return 0;
	uintptr_t p = fdt + be32(fdt + 8);		/* off_dt_struct */
	uintptr_t strings = fdt + be32(fdt + 12);	/* off_dt_strings */
	int depth = 0, in_chosen = 0;

	for (;;) {
		uint32_t tok = be32(p);
		p += 4;
		switch (tok) {
		case FDT_BEGIN_NODE: {
			const char *name = (const char *)p;
			depth++;
			in_chosen = depth == 2 && streq(name, "chosen");
			p = align4(skip_str(p));
			break;
		}
		case FDT_END_NODE:
			if (in_chosen)
				return 0;
			depth--;
			break;
		case FDT_PROP: {
			uint32_t len = be32(p), nameoff = be32(p + 4);
			uintptr_t val = p + 8;
			if (in_chosen && streq((const char *)(strings + nameoff), prop)) {
				if (len == 4)
					*out = be32(val);
				else if (len == 8)
					*out = (uint64_t)be32(val) << 32 | be32(val + 4);
				else
					return 0;
				return 1;
			}
			p = align4(val + len);
			break;
		}
		case FDT_NOP:
			break;
		default:	/* FDT_END or garbage */
			return 0;
		}
	}
}

/*
 * /memory: the one node whose contents must never be guessed.
 *
 * The walk is the same shape as fdt_chosen_u64, but it has to read the node's
 * own #address-cells/#size-cells first, because reg is a sequence of cells
 * whose width those properties define. Qualcomm boards are 2/2 today; reading
 * the widths means a 1/1 or 2/1 board would not silently produce a wrong
 * address by concatenating the wrong number of cells.
 */
static int be32_n(uintptr_t a, int ncells, uint64_t *out)
{
	uint64_t v = 0;
	for (int i = 0; i < ncells; i++)
		v = (v << 32) | be32(a + 4 * i);
	*out = v;
	return 1;
}

int fdt_memory_base_size(uintptr_t fdt, uint64_t *base, uint64_t *size)
{
	if (!fdt || be32(fdt) != FDT_MAGIC)
		return 0;
	uintptr_t p = fdt + be32(fdt + 8);		/* off_dt_struct */
	uintptr_t strings = fdt + be32(fdt + 12);	/* off_dt_strings */
	int depth = 0, in_memory = 0;
	int ac = 2, sc = 2;				/* arm64 default if absent */
	uintptr_t reg = 0;
	uint32_t reglen = 0;

	for (;;) {
		uint32_t tok = be32(p);
		p += 4;
		switch (tok) {
		case FDT_BEGIN_NODE: {
			const char *name = (const char *)p;
			depth++;
			/* match "memory" and "memory@<addr>", not "memory-controller" */
			in_memory = depth == 2 &&
				    (streq(name, "memory") ||
				     (name[0] == 'm' && name[6] == '@' &&
				      name[7] != '\0' && streq_n(name, "memory", 6)));
			p = align4(skip_str(p));
			break;
		}
		case FDT_END_NODE:
			if (in_memory) {
				if (!reg || reglen < (uint32_t)(4 * (ac + sc)))
					return 0;
				be32_n(reg, ac, base);
				be32_n(reg + 4 * ac, sc, size);
				return 1;
			}
			depth--;
			break;
		case FDT_PROP: {
			uint32_t len = be32(p), nameoff = be32(p + 4);
			uintptr_t val = p + 8;
			if (in_memory) {
				const char *pn = (const char *)(strings + nameoff);
				if (streq(pn, "reg")) {
					reg = val;
					reglen = len;
				} else if (streq(pn, "#address-cells") && len == 4) {
					ac = (int)be32(val);
				} else if (streq(pn, "#size-cells") && len == 4) {
					sc = (int)be32(val);
				}
			}
			p = align4(val + len);
			break;
		}
		case FDT_NOP:
			break;
		default:	/* FDT_END or garbage */
			return 0;
		}
	}
}
