# Dell Precision 7920 Tower：在 Proxmox 使用 32GiB GPU BAR

[English](README.md)

参考配置：**BIOS 2.52.2**、Radeon AI PRO R9700、PVE内核7.0.14-26-pve、QEMU11.0.3，主客机使用**32GiB BAR0**。其他BIOS版本必须重新审核固件；BAR变大本身不证明推理性能提升。

## 真正起作用的修改

1. UEFI启动、Above 4GB，以及足够的高位MMIO地址空间。
2. 在这个准确版本的BIOS中，**只把 MMIO High Granularity 从枚举0改为3**，让根窗口达到64GiB；Base不变。
3. 启动GPU虚拟机之前，临时解绑空闲的VFIO显卡/音频功能，向Linux `resource0_resize`写入**大小位号15**，核对分配后重新绑定VFIO。
4. 后续开机在`pve-guests.service`之前执行经过检查的调整。

本方案使用隐藏固件设置和Linux标准调整接口，无需注入ReBarDxe或刷写BIOS代码。64GiB MMIO窗口是设备地址空间，**不占用64GiB系统RAM**。PCIe Bus Allocation、VMD和USB设置不控制BAR大小。

## 按顺序操作

使用本地Linux控制台或你自己的SSH连接。下列命令均在**宿主机**运行。原始报告留私有位置，恢复备份放U盘；按[资料规则](docs/PRIVACY.zh-CN.md)存放。Python3.10以上，仅需标准库；只读检查也可能需要root。

```sh
sudo python3 -B scripts/rebar_audit.py --private-output "$USB/before.json"
# 返回2表示需要复核；初始根窗口过小属于预期发现。
```

stdout不含实例标识；显式选择生成的JSON含设备身份、拓扑和资源地址，必须保密。有多个候选GPU时需根据本机发现结果明确指定`--gpu`。

| 顺序 | 操作 | 必须通过的检查 |
|---|---|---|
| 1 | [审核固件和硬件](docs/FIRMWARE.zh-CN.md) | 准确版本镜像/IFR、实机变量和CPU物理地址上限一致 |
| 2 | [制作恢复U盘及备份](docs/USB.zh-CN.md) | 哈希、解压与离线恢复文件检查通过 |
| 3 | 从USB启动；只读CHECK，再启动PVE救援 | 使用USB的引导器/内核/initrd启动原PVE/ZFS |
| 4 | 再进USB；执行精确往返测试，再APPLY | 测试完整恢复原变量；正式应用仅改变已审核字段 |
| 5 | 启动PVE；验证变量和根窗口；调整空闲GPU | 宿主BAR0=32GiB，各级桥覆盖BAR |
| 6 | 测一台GPU VM，再安装开机服务 | 客机BAR、AMDGPU、ROCm/HIP通过；正常关闭VM |
| 7 | 正常重启宿主并验收 | 开机服务实际从256MiB调至32GiB，先于PVE启动VM |

**通常三个正常启动循环**；若未验证过恢复菜单，另做首次冷启动入口检查。必要的F2设置一次性记录；部分机型退出F2会额外重启，须另计。不能为了减少重启，在救援启动尚未验证时就保留固件改动。[验证检查点](docs/VALIDATION.zh-CN.md)。

## 相关BIOS设置

![Above 4GB已开启](docs/images/above-4g.png)

![Legacy Option ROMs已关闭](docs/images/legacy-option-roms.png)

使用UEFI，开启Above 4GB，关闭Legacy Option ROMs；直通需要开启VT-d。这些未签名工具要求关闭Secure Boot。保留现有可工作的存储和引导设置。[BIOS界面参考](docs/SCREENSHOTS.zh-CN.md)。

## 升级BIOS或移动GPU之后

```sh
sudo python3 -B scripts/rebar_audit.py \
  --baseline "$USB/before.json" --private-output "$USB/after.json"
```

脚本自动发现当前GPU路径，并比较BIOS版本/日期、设备身份、桥拓扑、同分支设备、IOMMU隔离、BAR支持和根窗口对齐空间。**它不会批准新BIOS的写入偏移**。必须重新提取并独立核对IFR，才能生成下一次固件操作单。移动插槽后还需检查PVE PCI映射并替换旧的私有运行配置。

## 脚本

| 脚本 | 默认行为 |
|---|---|
| `rebar_audit.py` | 只读发现；stdout隐私化，可选私有JSON |
| `ifr_review.py` | 解析IFR文本；`--pe32`独立核对原始操作码宽度/偏移/枚举 |
| `make_profile.py` | 显式确认准确版本已审核后生成私有配置 |
| `uefi_plan.py` | 生成有保护的CHECK/ROUNDTRIP/APPLY/ROLLBACK，不自行写固件 |
| `rebar_resize.py` | 默认只检查；`--execute`才解绑空闲VFIO、调整并重新绑定 |
| `guest_check.py` | 客机内运行；等待AMDGPU并核对BAR/VRAM/ROCm，可选`--hip-test` |
| `prepare_usb.py` | 填充**已格式化且空白**的U盘；不会格式化磁盘 |
| `esp_backup.py` | 只向USB备份/校验；恢复还需准确的目标PARTUUID确认 |
| `usb_archive.py` | 明确选择恢复文件；FAT32容得下时用单ZIP，否则≤2GiB分卷；校验重建U盘 |
| `recovery_manifest.py` | 选择启动/工具/实际备份，排除截图和测试镜像副本 |
| `privacy_check.py` | 检查文本/PNG元数据；可选私有图片哈希清单 |

从当前机器生成配置，手动调整验证成功后才启用自动化。只启用一个调整服务；替换已有实现前先审核。

## 回滚与BIOS升级

**升级前建议：**停用自动BAR服务；仍在旧版、已审核BIOS时，只把本次隐藏字段恢复到记录的原值并验证。记录好SATA/UEFI/VT-d。没有必要仅为本方案把全部BIOS设置恢复默认；目标固件有额外要求时，以其说明为准。升级后先保持自动化停用，直到新的调查与IFR审核通过。[回滚、升级及无法POST的边界](docs/RECOVERY.zh-CN.md)。

原始日志/截图和本机配置放用户自建私有仓库；恢复镜像及完整U盘包离线放U盘/NAS。凭据不能进入任何Git仓库。[隐私边界](docs/PRIVACY.zh-CN.md)。

## Agent提示词、测试和来源

[可复用提示词](prompt.zh-CN.md) · [安全检查测试](tests/test_safety.py)

```sh
python3 -B -m unittest discover -s tests -v
python3 -B scripts/privacy_check.py .
```

[原V100讨论](https://github.com/xCuri0/ReBarUEFI/discussions/331) · [Linux7.0实现](https://github.com/torvalds/linux/blob/v7.0/drivers/pci/pci-sysfs.c) · [QEMU11.0.3 VFIO](https://github.com/qemu/qemu/blob/v11.0.3/hw/vfio/pci.c) · [Dell恢复说明](https://www.dell.com/support/kbdoc/en-us/000132453/how-to-recover-the-bios-on-a-dell-computer-or-tablet)
