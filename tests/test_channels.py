#!/usr/bin/env python3
"""Exercise the actual channel callbacks with mocked kernel/hardware operations."""
from pathlib import Path
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] / "src/r8127_n.c").read_text()
start = source.index("static void rtl8127_get_channels(")
end = source.index("#endif /* LINUX_VERSION_CODE >= KERNEL_VERSION(3,0,0) */", start)
callbacks = source[start:end]

prelude = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define ENABLE_RSS_SUPPORT
#define ENABLE_MULTIPLE_TX_QUEUE
#define RTL_FEATURE_MSIX 1
#define RTL8127_MAX_INDIRECTION_TABLE_ENTRIES 128
#define ASSERT_RTNL() ((void)0)
#define netdev_err(dev, ...) ((void)(dev))
typedef uint8_t u8;
struct rtl8127_private {
    unsigned int num_rx_rings, num_tx_rings, HwSuppNumRxQueues, HwSuppNumTxQueues;
    unsigned int HwCurrIsrVer, features, irq_nvecs, min_irq_nvecs;
    unsigned int EnableRss, rtk_enable_diag, HwSuppIndirTblEntries;
    u8 rss_indir_tbl[128];
};
struct net_device { struct rtl8127_private tp; bool running, present; };
struct ethtool_channels {
    unsigned int max_rx, max_tx, rx_count, tx_count, combined_count, other_count;
};
static unsigned int real_rx, real_tx, allocated_rx, allocated_tx;
static int opens, closes, masks, sets, open_failures, fail_set_at;
static void *netdev_priv(struct net_device *d) { return &d->tp; }
static bool netif_running(struct net_device *d) { return d->running; }
static bool netif_device_present(struct net_device *d) { return d->present; }
static bool is_power_of_2(unsigned int n) { return n && !(n & (n-1)); }
static unsigned int ethtool_rxfh_indir_default(unsigned int i, unsigned int n)
{ assert(n); return i % n; }
static int rtl8127_close(struct net_device *d) {
    /* In particular, close must see the old counts, before they are changed. */
    assert(!allocated_rx || allocated_rx == d->tp.num_rx_rings);
    assert(!allocated_tx || allocated_tx == d->tp.num_tx_rings);
    allocated_rx = allocated_tx = 0;
    closes++;
    return 0;
}
static void dev_close(struct net_device *d) {
    rtl8127_close(d);
    d->running = false;
}
static void rtl8127_setup_interrupt_mask(struct rtl8127_private *tp)
{ (void)tp; masks++; }
static int rtl8127_set_real_num_queue(struct rtl8127_private *tp) {
    assert(!allocated_rx && !allocated_tx);
    real_tx = tp->num_tx_rings;
    if (++sets == fail_set_at) return -ENOMEM; /* Partial TX-only update. */
    real_rx = tp->num_rx_rings;
    return 0;
}
static int rtl8127_open(struct net_device *d) {
    assert(!allocated_rx && !allocated_tx);
    assert(real_rx == d->tp.num_rx_rings && real_tx == d->tp.num_tx_rings);
    for (unsigned int i = 0; i < 128; i++)
        assert(d->tp.rss_indir_tbl[i] < real_rx);
    opens++;
    if (open_failures) { open_failures--; return -ENOMEM; }
    allocated_rx = real_rx;
    allocated_tx = real_tx;
    return 0;
}
"""

tests = r"""
static struct net_device fresh(bool running) {
    struct net_device d = { .running = running, .present = true,
        .tp = { .num_rx_rings = 8, .num_tx_rings = 8,
                .HwSuppNumRxQueues = 8, .HwSuppNumTxQueues = 8,
                .HwCurrIsrVer = 6, .features = RTL_FEATURE_MSIX,
                .irq_nvecs = 32, .min_irq_nvecs = 30,
                .EnableRss = 1, .HwSuppIndirTblEntries = 128 } };
    for (unsigned int i = 0; i < 128; i++) d.tp.rss_indir_tbl[i] = i % 8;
    opens = closes = masks = sets = open_failures = fail_set_at = 0;
    real_rx = real_tx = 8;
    allocated_rx = allocated_tx = running ? 8 : 0;
    return d;
}
static int change(struct net_device *d, unsigned int rx, unsigned int tx) {
    struct ethtool_channels c = { .rx_count = rx, .tx_count = tx };
    return rtl8127_set_channels(d, &c);
}
int main(void) {
    struct net_device d;
    struct ethtool_channels c;
    /* All transitions, including asymmetric TX/RX and up/down interfaces. */
    for (int up = 0; up <= 1; up++) {
        d = fresh(up);
        for (unsigned int rx = 1; rx <= 8; rx *= 2)
            for (unsigned int tx = 1; tx <= 8; tx *= 2) {
                assert(change(&d, rx, tx) == 0);
                assert(d.tp.num_rx_rings == rx && d.tp.num_tx_rings == tx);
                assert(real_rx == rx && real_tx == tx);
                for (unsigned int i = 0; i < 128; i++)
                    assert(d.tp.rss_indir_tbl[i] == i % rx);
                assert(allocated_rx == (up ? rx : 0));
                assert(allocated_tx == (up ? tx : 0));
            }
        assert(up || (!opens && !closes));
    }
    d = fresh(true);
    assert(change(&d, 8, 8) == 0 && !opens && !closes && !sets);
    unsigned int invalid[] = { 0, 3, 5, 6, 7, 9, 16, UINT32_MAX };
    for (unsigned int i = 0; i < sizeof(invalid)/sizeof(invalid[0]); i++) {
        assert(change(&d, invalid[i], 4) == -EINVAL);
        assert(change(&d, 4, invalid[i]) == -EINVAL);
    }
    c = (struct ethtool_channels){ .rx_count = 4, .tx_count = 4, .combined_count = 1 };
    assert(rtl8127_set_channels(&d, &c) == -EINVAL);
    c.combined_count = 0; c.other_count = 1;
    assert(rtl8127_set_channels(&d, &c) == -EINVAL);
    assert(!closes && !sets);
    d.tp.rtk_enable_diag = 1;
    assert(change(&d, 4, 4) == -EBUSY);
    d.tp.rtk_enable_diag = 0; d.present = false;
    assert(change(&d, 4, 4) == -ENODEV);
    assert(!closes);

    for (int fallback = 0; fallback < 3; fallback++) {
        d = fresh(true);
        if (fallback == 0) d.tp.features = 0;
        if (fallback == 1) d.tp.HwCurrIsrVer = 1;
        if (fallback == 2) d.tp.irq_nvecs = 1;
        c = (struct ethtool_channels){0};
        rtl8127_get_channels(&d, &c);
        assert(c.max_rx == 1 && c.max_tx == 1);
        assert(change(&d, 4, 4) == -EINVAL && !closes);
    }

    /* Preserve custom mappings and reject removing referenced queues. */
    d = fresh(true);
    memset(d.tp.rss_indir_tbl, 2, 128);
    assert(change(&d, 4, 4) == 0);
    for (int i = 0; i < 128; i++) assert(d.tp.rss_indir_tbl[i] == 2);
    assert(change(&d, 2, 4) == -EINVAL);
    assert(d.tp.num_rx_rings == 4 && closes == 1);
    assert(change(&d, 4, 2) == 0);
    for (int i = 0; i < 128; i++) assert(d.tp.rss_indir_tbl[i] == 2);

    /* Roll back both a partial queue update and a failed ring allocation. */
    for (int failure = 0; failure < 2; failure++) {
        d = fresh(true);
        if (failure) open_failures = 1; else fail_set_at = 1;
        assert(change(&d, 4, 4) == -ENOMEM);
        assert(d.tp.num_rx_rings == 8 && d.tp.num_tx_rings == 8);
        assert(real_rx == 8 && real_tx == 8);
        assert(allocated_rx == 8 && allocated_tx == 8 && d.running);
        for (int i = 0; i < 128; i++) assert(d.tp.rss_indir_tbl[i] == i % 8);
        assert(masks == 2);
    }
    d = fresh(false); fail_set_at = 1;
    assert(change(&d, 4, 4) == -ENOMEM);
    assert(real_rx == 8 && real_tx == 8 && !opens && !closes);
    d = fresh(true); open_failures = 2;
    assert(change(&d, 4, 4) == -ENOMEM);
    assert(!d.running && !allocated_rx && !allocated_tx);
    puts("Channel validation, transitions, RSS preservation and rollback tests passed");
}
"""

with tempfile.TemporaryDirectory(prefix="r8127-channels-test-") as directory:
    path = Path(directory)
    (path / "test.c").write_text(prelude + callbacks + tests)
    subprocess.run(
        ["cc", "-std=c99", "-Wall", "-Wextra", "-Werror",
         "-fsanitize=undefined", "-o", str(path / "test"), str(path / "test.c")],
        check=True,
    )
    subprocess.run([str(path / "test")], check=True)
