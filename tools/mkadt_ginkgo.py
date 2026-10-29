#!/usr/bin/env python3
"""Build the minimal Apple Device Tree that XNU needs to boot on ginkgo.

This is a port of ios-sweet's tools/mkadt.py (MIT, dipa-studio). The structure,
the properties and the comments explaining why each one exists are theirs; what
changed is every address, the core layout and the page size, plus a few nodes
that only exist because this board is not sweet.

  mkadt.py OUT.adt [--dump] [--qemu]

Read devices/ginkgo/profile.py first: it is the source of the numbers, with the
device tree node each one came from.
"""
import hashlib, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'devices', 'ginkgo'))
import profile as gk  # noqa: E402

# Kernel-managed RAM. Read from /memory at boot by the shim (see
# shim/fdt.c:fdt_memory_base_size), and these are the values it is expected to
# find: the window above the last low-bank carve-out. They are not a
# preference, and the boot probe prints what the phone actually reports so the
# two can be compared.
PHYS_BASE = gk.PHYS_BASE
MEM_SIZE = gk.PHYS_SIZE

# Panic log buffer, carved from the TOP of the dram range and exposed to XNU as
# /pram + /chosen/embedded-panic-log-size. Without it, pe_init.c's
# check_for_panic_log() leaves gPanicBase == 0, debug_log_init() bails out twice
# and the kernel hangs right after "kdp_core zlib memory".
PANIC_LOG_SIZE = 0x100000

# /arm-io children are relative to this; it must not be 0 (serial_init bails)
SOC_BASE = 0x01000000

# GICv3. The distributor is at 0x0f200000 on this SoC, not the 0x17a00000 that
# every SM7xx/SM8xx board uses. A wrong value here shows up as "kernel text,
# then nothing" because the timer interrupt never arrives.
GICD, GICD_SIZE = gk.GICD, gk.GICD_SIZE
GICR, GICR_SIZE = gk.GICR, gk.GICR_SIZE

# The splash framebuffer ABL leaves scanning out.
FB, FB_SIZE = gk.FB_BASE, gk.FB_SIZE
SWEET_ECID = 0x47494e4b474f0001   # 'GINKGO' + 1, synthetic
FB_W, FB_H, FB_STRIDE = gk.FB_WIDTH, gk.FB_HEIGHT, gk.FB_STRIDE

TIMEBASE = gk.TIMEBASE
VTIMER_INTID = gk.VTIMER_INTID

# QEMU virt (-M virt,gic-version=3 -cpu cortex-a72): GICD/GICR and CNTFRQ differ.
QEMU_GICD, QEMU_GICR, QEMU_TIMEBASE = 0x08000000, 0x080a0000, 62500000
QEMU_VTIMER_INTID = 27

BOOT_MANIFEST_HASH = hashlib.sha384(b'ginkgo boot manifest').digest()

# The iOS userland is the iPhone X (iPhone10,3 / D22AP) IPSW. MobileGestalt
# derives product type, device class, home-button-less UI, artwork etc. from
# the root identity and /product of the real D22AP device tree. That tree is
# an Apple artifact (kept out of git): extract it from the IPSW with
#   tools/remotezip.py URL DeviceTree.d22ap.im4p DIR
#   ipsw img4 im4p extract DIR/Firmware/all_flash/DeviceTree.d22ap.im4p -o d22ap.adt
D22AP_ADT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         '../research/ipsw-x/d22ap.adt')


def d22ap_product(path=D22AP_ADT):
    """/product properties of the real D22AP tree, without the syscfg
    placeholders iBoot would fill in (flag bit set) and the node bookkeeping."""
    if not os.path.exists(path):
        print(f'warning: {path} missing, no /product node', file=sys.stderr)
        return None
    root, _ = adt.parse(open(path, 'rb').read())
    for c in root.children:
        if dict((k, v) for k, f, v in c.props).get('name') == b'product\0':
            return [(k, v) for k, f, v in c.props if not f and k not in ('name', 'AAPL,phandle')]
    raise SystemExit(f'{path}: no /product node')

u32 = lambda *v: struct.pack('<%dI' % len(v), *v)
u64 = lambda *v: struct.pack('<%dQ' % len(v), *v)
cstr = lambda s: s.encode() + b'\0'


def node(name, props=(), children=()):
    n = adt.Node()
    n.props = [('name', 0, cstr(name))] + [(k, 0, v) for k, v in props]
    n.children = list(children)
    return n


def cpu_nodes(timebase, qemu):
    """ginkgo's eight cores, in physical-core order.

    Four Cortex-A53 at MPIDR Aff1=0 (cpu@0..3, capacity 1024) then four
    Cortex-A73 at MPIDR Aff1=1 (cpu@100..103, capacity 1638). MPIDR carries the
    cluster, so the register value is (cluster << 8) | core, not a logical
    index -- writing a plain 0..7 here makes XNU start the wrong cores.

    Every core is ARMv8.0. The A53 has no 16K granule, so the kernel this tree
    is consumed by has to be a 4 KB-page build; `smp` here describes topology
    only and cannot paper over the granule.
    """
    out = []
    idx = 0
    for cl in gk.CPU_CLUSTERS:
        for core in range(cl['count']):
            if qemu and idx > 0:
                continue                    # QEMU test boots a single core
            mpidr = cl['mpidr_base'] + core
            out.append(node(f'cpu{idx}', [
                ('AAPL,phandle', u32(idx + 1)),
                ('device_type', cstr('cpu')),
                ('compatible', cstr('qcom,kryo260') + cstr('ARM,v8')),
                ('reg', u32(mpidr)),        # MPIDR Aff1:Aff0, NOT logical id
                ('cpu-id', u32(idx)),       # descriptive: XNU assigns by DT order
                ('cluster-id', u32(0)),     # homogeneous SMP cluster
                ('cluster-type', u32(0)),
                ('die-cluster-id', u32(0)),
                ('cluster-core-id', u32(core)),
                ('l2-cache-id', u32(idx)),
                ('l3-cache-id', u32(0)),
                ('state', cstr('running' if idx == 0 else 'stopped')),
                ('timebase-frequency', u32(timebase)),
                ('clock-frequency', u32(cl['max_mhz'] * 1000000)),
                ('bus-frequency', u32(100000000)),
                ('memory-frequency', u32(1866000000)),
                ('peripheral-frequency', u32(timebase)),
                ('fixed-frequency', u32(timebase)),
            ]))
            idx += 1
    return out


def build(seed=None, qemu=False):
    """qemu=True: same tree with QEMU virt's GIC and CNTFRQ (tools/qemu-ginkgo.py)."""
    phys_base, mem_size = PHYS_BASE, MEM_SIZE
    panic_base = phys_base + mem_size - PANIC_LOG_SIZE
    mem_size -= PANIC_LOG_SIZE
    gicd, gicr, timebase = (QEMU_GICD, QEMU_GICR, QEMU_TIMEBASE) if qemu else (GICD, GICR, TIMEBASE)
    seed = seed if seed is not None else os.urandom(64)
    phandle = iter(range(100, 1000))
    ph = lambda: ('AAPL,phandle', u32(next(phandle)))

    chosen = node('chosen', [
        ph(),
        ('dram-base', u64(phys_base)),
        ('dram-size', u64(mem_size)),
        ('random-seed', seed),
        ('debug-enabled', u32(1)),
        ('embedded-panic-log-size', u32(PANIC_LOG_SIZE)),
        ('firmware-version', cstr('ginkgo-shim')),
        ('system-firmware-version', cstr('ginkgo-shim')),
        # iBoot's SHA-384 of the boot manifest; /sbin/mount -P 1 exits unless
        # it exists (bind mounts /private/preboot/<hex>/usr/standalone/firmware,
        # tolerating a missing directory). Fixed stand-in value.
        ('boot-manifest-hash', BOOT_MANIFEST_HASH),
        # libimg4 (cryptexd) aborts "failed to get crypto algorithm" without
        # it; real A11+ device trees say sha2-384.
        ('crypto-hash-method', cstr('sha2-384')),
        # MobileGestalt's screen class. 1080x2340 at scale 3 would be 360x780
        # points, which is not an iPhone size; the iPhone X canvas is claimed
        # instead (1125x2436 at scale 3 = 375x812) and the framebuffer scales.
        ('display-scale', u32(gk.DISPLAY_SCALE)),
        # XNU derives IOPlatformUUID (gethostuuid) from these on arm; without
        # them CFPreferences cannot use kCFPreferencesCurrentHost (no ByHost
        # files), so e.g. DataMigration never records LastSystemVersion and
        # migrates on every boot. Synthetic ECID (not the phone's); chip-id
        # of the A11 that the iPhone X userland expects.
        ('unique-chip-id', struct.pack('<Q', SWEET_ECID)),
        ('chip-id', u32(0x8015)),
        # Security status as on a dev-fused, undemoted board (tuple 0,0,1,1):
        # MobileGestalt reads these from /chosen, and mobileactivationd's
        # DeviceType then takes its native "Hactivation" branch (state
        # Activated without an activation record; no SEP, no baseband here).
        ('certificate-production-status', u32(0)),
        ('effective-production-status-ap', u32(0)),
        ('certificate-security-mode', u32(1)),
        ('effective-security-mode-sep', u32(1)),
    ], [node('memory-map', [ph()]),
        # Local boot policy (kern_csr.c): SIP relaxed like `csrutil disable`
        # (lp-sip0: untrusted kexts, unrestricted FS, task_for_pid, kernel
        # debugger, dtrace, nvram), lp-sip1: unauthenticated (unsealed) root.
        # The iOS shared cache is in no trust cache, so dyld can only map it
        # with CSR_ALLOW_UNRESTRICTED_FS (vm_unix.c shared region checks).
        node('asmb', [ph(), ('lp-sip0', u64(0x6f)), ('lp-sip1', u32(1))])])

    cpus = node('cpus', [ph(), ('#address-cells', u32(1)),
                         ('#size-cells', u32(0))], cpu_nodes(timebase, qemu))

    gic = node('gic', [
        ph(),
        ('compatible', cstr('arm,gic-v3')),
        ('interrupt-controller', b''),
        ('virtual-timer-intid', u32(QEMU_VTIMER_INTID if qemu else VTIMER_INTID)),
        ('reg', u64(gicd - SOC_BASE, GICD_SIZE, gicr - SOC_BASE, GICR_SIZE)),
    ])
    arm_io = node('arm-io', [
        ph(),
        ('device_type', cstr('ginkgo-io')),
        ('compatible', cstr('ginkgo-io') + cstr('arm-io')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
        ('ranges', u64(0, SOC_BASE, 0x100000000 - SOC_BASE)),
    ], [gic,
        # No hardware: watchdogd checks IODeviceTree:/arm-io/wdt for no-pmu and
        # otherwise crashes trying to set the PMU boot stage.
        node('wdt', [ph(), ('no-pmu', u32(1))]),
        # Main display: IOMobileFramebuffer.framework counts /arm-io children
        # with this device_type and reads the canvas size from the node
        # (the presented iPhone X size); the kernel's AppleCLCD matches the
        # compatible string.
        node('disp0', [
            ph(),
            ('device_type', cstr('display-subsystem')),
            ('compatible', cstr('ginkgo,display')),
            ('canvas-width', u32(gk.CANVAS_WIDTH)),
            ('canvas-height', u32(gk.CANVAS_HEIGHT)),
        ])])

    fbcon = node('ginkgo-fbcon', [
        ph(),
        ('reg', u64(FB, FB_SIZE)),
        ('width', u32(FB_W)),
        ('height', u32(FB_H)),
        ('stride', u32(FB_STRIDE)),
    ])

    # pmap_compute_max_asids requires the node even when no overrides are set.
    # An absent pmap-max-asids property selects XNU's own MAX_ASIDS default.
    # No effaceable storage: keybagd then reads /private/var/keybags/systembag.kb
    # as a plain plist instead of decrypting it with the effaceable key.
    defaults = node('defaults', [ph(), ('no-effaceable-storage', u32(1))])

    # MobileGestalt HomeButtonType = IODeviceTree:/buttons home-button-type
    # (D22AP: 2, no Home button; absent = 0 = Home-button device).
    buttons = node('buttons', [
        ph(),
        ('button-names', cstr('volup') + cstr('voldown') + cstr('hold')),
        ('home-button-type', u32(2)),
        ('opposed-power-vol-buttons', u32(1)),
    ])

    product_props = d22ap_product()
    product = [node('product', [ph()] + product_props)] if product_props else []

    # Panic log region. /pram reg = <phys size>; it sits just above the
    # dram-size we expose, so XNU maps it but never allocates into it.
    pram = node('pram', [ph(), ('reg', u64(panic_base) + u64(PANIC_LOG_SIZE))])

    #
    # No storage node.
    #
    # ios-sweet emits `sweet-ufs` here, consumed by bsd/dev/sweet_ufs.c. This
    # board's storage is eMMC on sdhci@4744000 and no XNU driver for it exists
    # in any public port, so there is nothing to point a node at. Emitting one
    # anyway would let the kernel match a driver that cannot work, which turns
    # "no root device" into a crash somewhere less obvious.
    #
    # When an SDHCI driver exists, its node goes here with compatible
    # "ginkgo,emmc" and reg = <0x4744000 0x1000>.
    #

    # Identity of the iPhone X whose userland runs here: compatible[0] is
    # hw.model/hw.target (D22AP), model is hw.machine/hw.product (iPhone10,3).
    # 'xiaomi,ginkgo' stays for GinkgoPlatformExpert matching.
    return node('device-tree', [
        ph(),
        ('compatible', cstr('D22AP') + cstr('iPhone10,3') + cstr('xiaomi,ginkgo') +
                       cstr('qcom,sm6125') + cstr('AppleARM')),
        ('model', cstr('iPhone10,3')),
        ('target-type', cstr('D22')),
        ('target-sub-type', cstr('D22AP')),
        ('manufacturer', cstr('Apple Inc.')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
    ], [chosen, defaults, cpus, arm_io, fbcon, buttons, pram] + product)


if __name__ == '__main__':
    root = build(qemu='--qemu' in sys.argv)
    blob = adt.serialize(root)
    open(sys.argv[1], 'wb').write(blob)
    if '--dump' in sys.argv:
        adt.dump(adt.parse(blob)[0])
    print(f'{sys.argv[1]}: {len(blob)} bytes', file=sys.stderr)
