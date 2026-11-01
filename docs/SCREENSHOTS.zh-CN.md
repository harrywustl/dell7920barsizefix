# BIOS界面参考

[English](SCREENSHOTS.md)

不同BIOS版本的标签和选项可能不同。保留现有存储/引导设置，不要照搬全部界面数值。

| 界面 | 用途 |
|---|---|
| [UEFI启动模式](images/uefi-boot-mode.png) | 所需引导环境 |
| [Above 4GB](images/above-4g.png) | 开启高位MMIO解码 |
| [Legacy Option ROMs](images/legacy-option-roms.png) | 关闭Legacy Option ROMs |
| [VT-d](images/iommu-reference.png) | GPU直通前提 |
| [Secure Boot](images/secure-boot-reference.png) | 未签名Shell/工具需要相应启动策略 |
| [PVE救援菜单](images/pve-rescue-menu.png) | 从USB引导原PVE根系统 |
| [BIOS恢复菜单](images/bios-recovery-menu.png) | 入口演练选择Exit |
| [SATA模式](images/storage-mode-reference.png) | 保留现有可工作的存储模式 |
| [VT-x](images/virtualization-reference.png) | 虚拟机前提 |
| [内存限制](images/memory-limit-reference.png) | 参考；不控制GPU BAR大小 |
| [PCIe速率](images/pcie-speed-reference.png) | Auto允许协商支持的链路速率 |
| [PCIe总线分配](images/pcie-bus-allocation-reference.png) | 分配总线编号，不是BAR窗口大小 |

USB设置影响救援入口，不控制GPU BAR大小。MMIO字段按[固件审核](FIRMWARE.zh-CN.md)从准确版本提取核对。
