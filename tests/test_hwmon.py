#!/usr/bin/env python3
"""Test actual hwmon callbacks with mocked PHY and device state."""
from pathlib import Path
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] / "src/r8127_n.c").read_text()
start = source.index("static umode_t rtl8127_hwmon_is_visible")
end = source.index("static const struct hwmon_ops rtl8127_hwmon_ops", start)
callbacks = source[start:end]

prelude = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <stdio.h>
typedef unsigned int umode_t;
typedef uint32_t u32;
enum hwmon_sensor_types { hwmon_temp, hwmon_in };
enum { hwmon_temp_input, hwmon_temp_max };
enum { R8127_FLAG_DOWN, R8127_FLAG_SUSPEND, R8127_FLAG_SHUTDOWN };
#define PCI_D0 0
struct net_device { bool running, present; };
struct pci_dev { int current_state; };
struct rtl8127_private {
    struct net_device *dev;
    struct pci_dev *pci_dev;
    unsigned long task_flags[1];
    int phy_lock, rtk_enable_diag;
};
struct device { struct rtl8127_private *data; };
static bool can_lock = true, locked;
static int raw, reads;
static void *dev_get_drvdata(struct device *d) { return d->data; }
static bool rtnl_trylock(void) { assert(!locked); return locked = can_lock; }
static void rtnl_unlock(void) { assert(locked); locked = false; }
static bool netif_running(struct net_device *d) { return d->running; }
static bool netif_device_present(struct net_device *d) { return d->present; }
static bool test_bit(int n, unsigned long *p) { return (*p >> n) & 1; }
#define r8127_spin_lock(p, f) do { assert(locked && !*(p)); *(p) = 1; (f) = 0; } while (0)
#define r8127_spin_unlock(p, f) do { assert(*(p)); *(p) = 0; (void)(f); } while (0)
static int _rtl8127_read_thermal_sensor(struct rtl8127_private *tp) {
    assert(locked && tp->phy_lock);
    reads++;
    return raw;
}
"""
tests = r"""
int main(void) {
    struct net_device net = { true, true };
    struct pci_dev pci = { PCI_D0 };
    struct rtl8127_private tp = { .dev = &net, .pci_dev = &pci };
    struct device dev = { &tp };
    long value = 123;
    assert(rtl8127_hwmon_is_visible(&tp, hwmon_temp, hwmon_temp_input, 0) == 0444);
    assert(!rtl8127_hwmon_is_visible(&tp, hwmon_temp, hwmon_temp_max, 0));
    assert(!rtl8127_hwmon_is_visible(&tp, hwmon_in, hwmon_temp_input, 0));
    assert(!rtl8127_hwmon_is_visible(&tp, hwmon_temp, hwmon_temp_input, 1));
    /* Full 10-bit range: positive, half-degree and negative temperatures. */
    for (int signed_raw = -512; signed_raw < 512; signed_raw++) {
        raw = signed_raw & 1023;
        assert(!rtl8127_hwmon_read(&dev, hwmon_temp, hwmon_temp_input, 0, &value));
        assert(value == signed_raw * 500L && !locked && !tp.phy_lock);
    }
    reads = 0;
    assert(rtl8127_hwmon_read(&dev, hwmon_in, hwmon_temp_input, 0, &value) == -EOPNOTSUPP);
    assert(rtl8127_hwmon_read(&dev, hwmon_temp, hwmon_temp_max, 0, &value) == -EOPNOTSUPP);
    assert(rtl8127_hwmon_read(&dev, hwmon_temp, hwmon_temp_input, 1, &value) == -EOPNOTSUPP);
    can_lock = false;
    assert(rtl8127_hwmon_read(&dev, hwmon_temp, hwmon_temp_input, 0, &value) == -EBUSY);
    can_lock = true;
    tp.rtk_enable_diag = 1;
    assert(rtl8127_hwmon_read(&dev, hwmon_temp, hwmon_temp_input, 0, &value) == -EBUSY);
    tp.rtk_enable_diag = 0;
    for (int state = 0; state < 6; state++) {
        net.running = state != 0;
        net.present = state != 1;
        pci.current_state = state == 2 ? 3 : PCI_D0;
        tp.task_flags[0] = state >= 3 ? 1UL << (state - 3) : 0;
        value = 123;
        assert(rtl8127_hwmon_read(&dev, hwmon_temp, hwmon_temp_input, 0, &value) == -ENODATA);
        assert(value == 123 && !reads && !locked && !tp.phy_lock);
    }
    puts("hwmon conversion, permissions, locking and inactive-device tests passed");
}
"""

with tempfile.TemporaryDirectory(prefix="r8127-hwmon-test-") as directory:
    path = Path(directory)
    (path / "test.c").write_text(prelude + callbacks + tests)
    subprocess.run(
        ["cc", "-std=c99", "-Wall", "-Wextra", "-Werror",
         "-Wno-unused-parameter", "-fsanitize=undefined",
         "-o", str(path / "test"), str(path / "test.c")], check=True,
    )
    subprocess.run([str(path / "test")], check=True)
