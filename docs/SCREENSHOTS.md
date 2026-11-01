# BIOS reference screens

[简体中文](SCREENSHOTS.zh-CN.md)

Labels and available options vary by BIOS version. Preserve working storage/boot settings; do not copy every value shown.

| Screen | Purpose |
|---|---|
| [UEFI boot mode](images/uefi-boot-mode.png) | Required boot environment |
| [Above 4GB](images/above-4g.png) | Enable high MMIO decoding |
| [Legacy Option ROMs](images/legacy-option-roms.png) | Disable legacy option ROMs |
| [VT-d](images/iommu-reference.png) | GPU passthrough prerequisite |
| [Secure Boot](images/secure-boot-reference.png) | Unsigned Shell/tools require a compatible policy |
| [PVE rescue menu](images/pve-rescue-menu.png) | Boot the existing PVE root from USB |
| [BIOS recovery menu](images/bios-recovery-menu.png) | Entry tests use Exit |
| [SATA mode](images/storage-mode-reference.png) | Preserve the working storage mode |
| [VT-x](images/virtualization-reference.png) | VM prerequisite |
| [Memory limit](images/memory-limit-reference.png) | Reference; does not set GPU BAR size |
| [PCIe speed](images/pcie-speed-reference.png) | Auto permits supported link speed |
| [PCIe bus allocation](images/pcie-bus-allocation-reference.png) | Bus-number allocation, not BAR aperture size |

USB settings affect rescue access, not GPU BAR size. Review the MMIO fields from the exact firmware as described in [Firmware](FIRMWARE.md).
