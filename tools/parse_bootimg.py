#!/usr/bin/env python3
"""Parse an Android boot image v2 header the way the bootloader does.

Used to check that the shim image is laid out as intended, because a header
field read at the wrong offset produces a plausible-looking but wrong answer
(that mistake was made while writing this file: dtb_size is at 0x670 in a v2
header, not 0x18, because v0 and v1 fields come first).
"""
import struct, sys

def parse(path):
    d = open(path, 'rb').read()
    assert d[:8] == b'ANDROID!', 'not an Android boot image'
    g = lambda o, f='<I': struct.unpack(f, d[o:o+struct.calcsize(f)])[0]
    h = {}
    h['kernel_size'], h['kernel_addr'] = g(8), g(12, '<Q')
    h['ramdisk_size'], h['ramdisk_addr'] = g(16), g(20, '<Q')
    h['second_size'], h['second_addr'] = g(24), g(28, '<Q')
    h['tags_addr'], h['page_size'] = g(32, '<Q'), g(36)
    h['header_version'], h['os_version'] = g(40), g(44)
    h['name'] = d[48:48+16].split(b'\0')[0].decode(errors='replace')
    h['cmdline'] = d[64:64+512].split(b'\0')[0].decode(errors='replace')
    h['id'] = d[576:608].hex()
    h['extra_cmdline'] = d[608:608+1024].split(b'\0')[0].decode(errors='replace')
    assert h['header_version'] == 2, f"only v2 supported, got {h['header_version']}"
    h1 = 1632                                    # end of boot_img_hdr_v0
    h['recovery_dtbo_size'], h['recovery_dtbo_offset'] = g(h1), g(h1+4, '<Q')
    h['header_size'] = g(h1+12)
    h['dtb_size'], h['dtb_addr'] = g(h1+16), g(h1+20, '<Q')

    ps = h['page_size']
    pages = lambda n: (n + ps - 1) // ps
    off = ps
    h['kernel_off'] = off; off += pages(h['kernel_size']) * ps
    h['ramdisk_off'] = off; off += pages(h['ramdisk_size']) * ps
    h['second_off'] = off; off += pages(h['second_size']) * ps
    h['recovery_dtbo_off'] = off; off += pages(h['recovery_dtbo_size']) * ps
    h['dtb_off'] = off; off += pages(h['dtb_size']) * ps
    h['expected_size'] = off
    h['actual_size'] = len(d)
    h['ok'] = off == len(d)
    return h, d

if __name__ == '__main__':
    h, d = parse(sys.argv[1])
    for k, v in h.items():
        if k in ('kernel_addr', 'ramdisk_addr', 'second_addr', 'tags_addr', 'dtb_addr'):
            print(f'{k:20s} {v:#x}')
        elif 'off' in k or 'size' in k:
            print(f'{k:20s} {v} ({v:#x})' if isinstance(v, int) else f'{k:20s} {v}')
        else:
            print(f'{k:20s} {v}')
    print()
    print('LAYOUT OK' if h['ok'] else f"LAYOUT MISMATCH: expected {h['expected_size']}, got {h['actual_size']}")
    sys.exit(0 if h['ok'] else 1)
