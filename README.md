# r8127-dkms

This repository contains the Linux device driver for Realtek 10 Gigabit PCI-Express Ethernet controllers, packaged for use with DKMS.

## Installation

Two installation methods are provided. The recommended method for Debian-based systems is using the pre-built DKMS package. For other systems, a manual installation script is available.

### Method 1: Using the .deb Package (Recommended)

This method is recommended for all Debian/Ubuntu-based distributions that support DKMS, including but not limited to Linux Mint, Proxmox VE, TrueNAS SCALE, and Openmediavault.

The primary advantage of this method is that the kernel module will be automatically rebuilt and installed whenever the system kernel is updated.

1.  Navigate to the [Releases](https://github.com/minisforum-repo/r8127-dkms/releases) page.
2.  Download the latest `.deb` package.
3.  Install the package using `apt`:
    ```bash
    sudo apt install ./r8127-dkms_*.deb
    ```

If dkms is not automatically compiled, it may be due to the lack of kernel header. Please manually install `sudo apt install linux-headers-$(uname -r)` and then reinstall r8127-dkms

### Method 2: Using autorun.sh

This method is suitable for Linux distributions that do not use the DEB package format or do not have DKMS support.

**Important:** If you use this method, you must manually re-run the script every time your system's kernel is updated to ensure the driver remains compatible.

1.  Install the necessary build tools for your distribution (e.g., kernel headers, gcc, make).
2.  Clone the repository and navigate into the directory.
3.  Run the installation script with root privileges:
    ```bash
    sudo ./autorun.sh
    ```

## Installation Verification

After installation, you can perform the following checks to ensure the driver is installed and loaded correctly.

1.  **Check if the RTL8127 PCIe device is recognized:**
    ```bash
    lspci -k | grep -i "realtek" -A3
    ```

2.  **Verify that the `r8127.ko` module file exists.**
    `find /lib/modules/$(uname -r) -name 'r8127*'`

3.  **Confirm that the `r8127` kernel module is loaded:**
    ```bash
    lsmod | grep r8127
    ```
    If the command returns output, the module is loaded. If not, you can try to load it manually:
    ```bash
    sudo modprobe r8127
    ```

## Building the DKMS .deb Package

If you wish to build the `.deb` package from the source yourself, follow these steps.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/minisforum-repo/r8127-dkms.git
    cd r8127-dkms
    ```

2.  **Install build dependencies:**
    ```bash
    sudo apt update
    sudo apt build-dep .
    ```

3.  **Build the package:**
    ```bash
    dpkg-buildpackage -b --no-sign
    ```
    The resulting `.deb` file will be located in the parent directory.

## License

Both the upstream source code and this Debian packaging are licensed under the **GPL-2.0**.

## References

This project is based on the official Debian repository for the `r8125-dkms` package: [https://salsa.debian.org/debian/r8125](https://salsa.debian.org/debian/r8125).
