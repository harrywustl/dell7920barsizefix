# 固件审核与可复用调查

[English](FIRMWARE.md) · [入口](../README.zh-CN.md)

## 已核实：只适用于2.52.2

以下数值仅适用于**2.52.2**，不能泛用于所有“2.52”。以安装版本/日期和ESRT匹配官方固件，再提取Socket Configuration PE32/IFR。研究用BIOS区域不能当SPI全片备份或恢复镜像。

| 项目 | 已核实值 |
|---|---|
| 变量 | `SocketCommonRcConfig` |
| 通用固件GUID | `4402ca38-808f-4279-bcec-5baf8d59092f` |
| 属性 / payload | `7` / `0x72`，114字节 |
| Base | payload `0x00`，**4字节**；枚举0=56TiB |
| Granularity | payload `0x04`，**2字节**；0=1GiB，1=4GiB，2=16GiB，**3=64GiB**，4=256GiB，5=1024GiB |
| `0x08` | Isoc Mode，不是旧帖子假定的字段 |
| Socket Configuration FFS | `6b6fd380-2c55-42c6-98bf-cbbc5a9aa666` |
| PE32 SHA256 | `f5d6fd18c1fcbca3df0cb5e2e4a79b2553701110b0900ccebbbe1c8fd1d09e47` |

将这些固件结构GUID与准确镜像及实机VarStore核对。

原帖V100与支持调整BAR的R9700能力不同。不要复制别人的完整变量、无效Base值`0x0200`、固定大BAR假设或无关设置。[原讨论](https://github.com/xCuri0/ReBarUEFI/discussions/331)。

## 修改前调查

```sh
cat /sys/class/dmi/id/bios_version
cat /sys/class/dmi/id/bios_date
lscpu
lspci -Dnn
sudo python3 -B scripts/rebar_audit.py --private-output "$USB/before.json"
```

原始输出只保存在私有位置。检查目标GPU全部功能、上游桥/根总线、`resource0_resize`支持位图、VFIO绑定、IOMMU成员和可对齐的高位根窗口。移动插槽后不能继续按旧BDF找卡。任何解绑前正常关闭VM；调整脚本发现同分支其他设备或QEMU/VFIO占用会拒绝操作。

## 离线提取准确版本并核对

1. 从Dell或微软取得与安装版本准确匹配的官方固件；记录链接、校验和、版本/日期及ESRT对应关系。调查时不执行更新程序。
2. 按[BIOSUtilities](https://github.com/platomav/BIOSUtilities)当前支持格式使用Dell PFS提取；例如在其源码目录：

   ```sh
   python3 main.py "$FIRMWARE" -e -u DellPfsExtract -o "$USB/firmware-extracted"
   ```

3. 核对容器/数据块CRC、偏移及边界。BIOS Guard/PFAT可能要按元数据重组，**不能直接拼接数据块**；无法验证产物就停止。
4. 用[UEFITool/UEFIExtract A76](https://github.com/LongSoft/UEFITool/releases/tag/A76)，根据通用FFS GUID或HII字符串定位Socket Configuration，提取**PE32 section body**，不是整段FFS。新版模块/GUID可能变化，必须搜索实际镜像。
5. 用[IFRExtractor1.6.1](https://github.com/LongSoft/IFRExtractor-RS/releases/tag/v1.6.1)导出文本；CLI以所用版本的`--help`为准。保留准确的PE32和完整IFR。

   ```sh
   python3 -B scripts/ifr_review.py "$IFR_TEXT" --pe32 "$PE32" > "$USB/ifr-facts.json"
   ```

6. 必须只有一个匹配的VarStore，其GUID、属性、长度与实机一致；文本与原始OneOf操作码的QuestionId、偏移、宽度、合法枚举必须一致。枚举标签仍要读完整IFR确认；脚本不会推断未说明语义。默认`approved=false`是刻意的保护。
7. 核对`Base + 最大MMIO范围 <= 2^物理地址位宽`。例如56TiB + 32×64GiB = 58TiB，符合46位/64TiB上限。读取实际IFR帮助和CPU位宽，不能假定倍率/枚举标签不变。

## 记录私有配置并生成Shell操作单

完成上述审核后，显式确认准确版本：

```sh
python3 -B scripts/make_profile.py \
  --baseline "$USB/before.json" --facts "$USB/ifr-facts.json" \
  --firmware "$FIRMWARE" --official-sha256 "$OFFICIAL_SHA256" \
  --confirm-reviewed-version "$EXACT_BIOS_VERSION" \
  --output "$USB/prechange-profile.json" \
  --approved-facts-output "$USB/approved-facts.json"

sudo python3 -B scripts/uefi_plan.py --usb "$USB" \
  --profile "$USB/prechange-profile.json" --facts "$USB/approved-facts.json" \
  --efivar "$LIVE_EFIVAR_PATH"
```

`LIVE_EFIVAR_PATH`是调查发现的唯一实机`SocketCommonRcConfig-*`文件。生成器检查当前BIOS、GUID、属性、长度和基线哈希，仅向新建`REBAR-PLAN`目录写文件，不写NVRAM。已经是目标枚举时不需要固件写入计划。它不会自动为无关隐藏设置生成操作。

在USB Shell选择正确U盘文件系统并位于根目录：

```text
REBAR-PLAN\CHECK.nsh
REBAR-PLAN\ROUNDTRIP.nsh RUN
REBAR-PLAN\APPLY.nsh RUN
```

CHECK及救援启动必须先在独立恢复检查点完成；下一次改动会话才执行ROUNDTRIP，看到`ROUNDTRIP_PASS`后才能APPLY。写入脚本拒绝覆盖旧证据，保存完整变量并与预期完整文件比较，不自动重启。出错就停，不要重启或删保护文件盲目重试。同名变量歧义必须停止。计划记录BIOS版本，但Shell脚本不能证明生成后BIOS没变，因此升级后不能复用旧计划。

2.52.2的版本特定写入/读回语法，须先完成上述核验：

```text
setup_var.efi SocketCommonRcConfig:0x04(2)=0x0003
setup_var.efi SocketCommonRcConfig:0x04(2)
```

payload `00 00`→`03 00`，只有byte4变化。Linux efivarfs前置4字节属性，因此是文件offset8。EDK2保存格式：头8+UTF16名称42+GUID16+属性4=payload起点70（`0x46`）；改变字节74（`0x4a`），CRC位置184（`0xb8`），总长188。写入前将生成文件与新保存的EDK2文件比较；不能把Linux118字节文件当EDK2备份导入。

## Linux分配与持久化

启动PVE后生成**新**私有基线，完整比较新旧变量，确认只改了计划中的字节。实际根窗口必须容纳可对齐的32GiB BAR，64GiB窗口可以容纳它；尚未请求调整时，下游桥仍小并不代表失败。

使用同一套已审核固件/IFR，从改动后快照生成新的运行配置。本R9700固件默认BAR0为256MiB；其他硬件用`--initial-bar0-mib`指定实际默认值。

```sh
sudo python3 -B scripts/rebar_audit.py --private-output "$USB/postchange.json"
# 重跑make_profile，输入postchange.json，输出使用新文件名。
sudo python3 -B scripts/rebar_resize.py --profile "$USB/runtime-profile.json"
sudo python3 -B scripts/rebar_resize.py --profile "$USB/runtime-profile.json" --execute
```

Linux BAR大小为`2^(20+n)`字节，n15=32GiB，n8=256MiB。标准接口由内核重分配桥窗口，不手写PCI寄存器偏移。确认BAR2大小未变，再测试一台GPU VM。

手动成功后才安装服务；以下命令会改变宿主文件：

只启用一个调整服务；安装替代方案前先审核并停用已有实现。

```sh
sudo install -d -m 755 /opt/rebar-kit
sudo install -m 644 scripts/rebar_audit.py scripts/rebar_resize.py /opt/rebar-kit/
sudo install -d -m 700 /etc/rebar-kit
sudo install -m 600 "$USB/runtime-profile.json" /etc/rebar-kit/profile.json
sudo install -m 644 examples/rebar-resize.service /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/rebar-resize.service
sudo systemctl daemon-reload
sudo systemctl enable --now rebar-resize.service
```

服务不依赖U盘；失败不会阻止宿主启动，但真实重启检查通过前不要开启GPU VM自启动。脚本不会解绑正在被VM占用的显卡。重启后检查`journalctl -b -u rebar-resize.service`。
