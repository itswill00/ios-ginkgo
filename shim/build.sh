#!/bin/bash
# Build the shim and wrap it in a boot.img v2.
#
#   ./build.sh [PAYLOAD] [BOARD]
#
#   PAYLOAD  an xnu payload from tools/mkpayload.py; omit it to build the
#            hardware probe, which prints what the board actually offers
#            (granule, /memory, GIC, PSCI) and then reboots.
#   BOARD    ginkgo (default) or sweet. Selects the per-board block in
#            board.h and the stock DTB to embed.
set -euo pipefail
cd "$(dirname "$0")"

BOARD="${2:-ginkgo}"
case "$BOARD" in
	ginkgo) BOARD_DEF=-DBOARD_GINKGO ;;
	sweet)  BOARD_DEF=-DBOARD_SWEET  ;;
	*) echo "unknown board: $BOARD (expected ginkgo or sweet)" >&2; exit 1 ;;
esac

CC=aarch64-linux-gnu-gcc
OBJCOPY=aarch64-linux-gnu-objcopy
CFLAGS="-O2 -ffreestanding -nostdlib -fno-pic -mgeneral-regs-only -mstrict-align -fno-stack-protector -Wall -Wextra $BOARD_DEF"

mkdir -p out
# ufs.c only builds on boards that have a UFS host to drive.
SRCS="start.S shim.c console.c mmu.c fdt.c loader.c"
if [ "$BOARD" = sweet ]; then
	SRCS="$SRCS ufs.c"
fi

# shellcheck disable=SC2086  # CFLAGS and SRCS are deliberately word-split
for f in $SRCS; do
	$CC $CFLAGS -c "$f" -o "out/${f%.*}.o"
done

OBJS=""
C_OBJS=""
for f in $SRCS; do
	OBJS="$OBJS out/${f%.*}.o"
	# start.o is excluded from the relocation check on purpose: its header
	# carries image_size as an absolute address, which is the one place that
	# is allowed because the header is read before anything is relocated.
	[ "$f" = "start.S" ] || C_OBJS="$C_OBJS out/${f%.*}.o"
done

# The image runs wherever ABL puts it with no relocation pass, so no C object
# may contain an absolute relocation: a pointer baked in at link time would
# point at the wrong place once ABL chooses where to load us.
# shellcheck disable=SC2086  # C_OBJS is a list of objects, split on purpose
abs=$(aarch64-linux-gnu-readelf -r $C_OBJS | grep -c ABS64 || true)
[ "$abs" = 0 ] || { echo "error: $abs absolute relocations in C objects" >&2; exit 1; }

# shellcheck disable=SC2086
$CC $CFLAGS -static -T shim.ld -Wl,--build-id=none -Wl,--no-warn-rwx-segments -Wl,-N \
	$OBJS -o out/shim.elf
$OBJCOPY -O binary out/shim.elf out/Image
# ABL copies the file; pad to image_size so .bss/stacks exist as zeroed bytes.
size=$(aarch64-linux-gnu-nm out/shim.elf | awk '$3=="_end"{print strtonum("0x"$1)}')
truncate -s "$size" out/Image

# Ramdisk: an xnu payload (tools/mkpayload.py) if given as $1, else an empty
# newc cpio (ABL dislikes a zero-size ramdisk on some builds) -> diagnostics.
if [ -n "${1:-}" ]; then
	cp "$1" out/ramdisk.bin
else
	(cd out && rm -rf rd && mkdir rd && cd rd && find . | cpio -o -H newc --quiet | gzip -9 > ../ramdisk.bin)
fi

# The stock DTB comes from the phone, not from this repository: unpack your own
# boot.img into dtb/boot_unpacked/dtb at the repository root. See
# devices/<board>/README.md. This script runs from shim/, hence the ../
DTB="../dtb/boot_unpacked/dtb"
if [ ! -f "$DTB" ]; then
	echo "error: $DTB missing." >&2
	echo "  The shim needs the stock DTB to boot: unpack your own boot.img with" >&2
	echo "  tools/unpack_bootv2.py and put the result at $DTB." >&2
	echo "  Without it, fastboot will accept the image and the phone will not start." >&2
	exit 1
fi

# mkbootimg: AOSP's mkbootimg.py works unmodified and is what the CI uses.
# Override with MKBootIMG=/path/to/mkbootimg if yours is installed elsewhere.
if [ -z "${MKBOTIMG_CMD:-}" ]; then
	if command -v mkbootimg >/dev/null 2>&1; then
		MKBOTIMG_CMD=mkbootimg
	elif [ -f "${MKBOTIMG_PY:-/nonexistent}" ]; then
		MKBOTIMG_CMD="python3 $MKBOTIMG_PY"
	else
		echo "error: mkbootimg not found." >&2
		echo "  Install AOSP's system/tools/mkbootimg and put it in PATH, or set" >&2
		echo "  MKBOTIMG_PY=/path/to/mkbootimg.py" >&2
		exit 1
	fi
fi

$MKBOTIMG_CMD --header_version 2 --kernel out/Image --ramdisk out/ramdisk.bin \
	--dtb "$DTB" --base 0 --kernel_offset 0x8000 --ramdisk_offset 0x1000000 \
	--tags_offset 0x100 --dtb_offset 0x1f00000 --pagesize 4096 \
	--os_version 17.0.0 --os_patch_level 2035-06 \
	--cmdline "console=null" -o out/shim-boot.img

# Host render of the console layout (geometry comes from board.h).
# Host render of the console layout. Failure here is not fatal: it only checks
# that the text fits the panel, which the target build cannot tell us.
if gcc -O1 -Wall -D"BOARD_$(echo "$BOARD" | tr '[:lower:]' '[:upper:]')" \
	-o out/host_test console.c host_test.c; then
	./out/host_test || true
fi
ls -l out/Image out/shim-boot.img
