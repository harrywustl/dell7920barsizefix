# Firmware review and repeatable investigation

[简体中文](FIRMWARE.zh-CN.md) · [Start](../README.md)

## Verified facts: 2.52.2 only

The values below apply to **2.52.2**, not every “2.52” release. Match the installed version/date and ESRT information to official firmware, then extract its Socket Configuration PE32/IFR. A research BIOS region is not a full SPI backup or a recovery image.

> [!CAUTION]
> **The table below is only for BIOS 2.52.2 and this GPU.** Do not copy the `0x04` offset, the `3` enum or the full variable to another BIOS/machine; re-extract the IFR and re-audit first. Writing the wrong field can make the machine unbootable.

| Item | Verified value |
|---|---|
| Variable | `SocketCommonRcConfig` |
| Shared firmware GUID | `4402ca38-808f-4279-bcec-5baf8d59092f` |
| Attributes / payload | `7` / `0x72` (114 bytes) |
| Base | payload `0x00`, **4 bytes**, enum0=56TiB |
| Granularity | payload `0x04`, **2 bytes**, enum0=1GiB; 1=4GiB; 2=16GiB; **3=64GiB**; 4=256GiB; 5=1024GiB |
| Offset `0x08` | Isoc Mode; not the old discussion's assumed field |
| Socket Configuration FFS | `6b6fd380-2c55-42c6-98bf-cbbc5a9aa666` |
| Extracted PE32 SHA256 | `f5d6fd18c1fcbca3df0cb5e2e4a79b2553701110b0900ccebbbe1c8fd1d09e47` |

Match these firmware structure GUIDs against the exact image and live VarStore.

The V100 in the linked discussion has different BAR capabilities from the resizable R9700. Do not copy its entire variable, invalid Base value `0x0200`, fixed-BAR assumptions or unrelated settings. [Original discussion](https://github.com/xCuri0/ReBarUEFI/discussions/331).

## Collect before changing anything

Set `USB` to your mounted USB path and `TARGET_GIB` to the target BAR size (32 here; must be a power of two). All `$...` names below are placeholders for your own paths/values.

```sh
cat /sys/class/dmi/id/bios_version
cat /sys/class/dmi/id/bios_date
lscpu
lspci -Dnn
sudo python3 -B scripts/rebar_audit.py --target-gib "$TARGET_GIB" --private-output "$USB/before.json"
```

Keep raw outputs private. Inspect the selected GPU, all its functions, upstream bridges and root bus, supported `resource0_resize` mask, VFIO binding, IOMMU members and aligned high root window. Do not identify a GPU by an old bus address after moving it. Stop VMs normally before any unbind. The resize tool refuses other devices in the branch or any running QEMU/VFIO holder.

## Extract and check the exact firmware offline

1. Download the exact installed version from Dell or the matching official Microsoft firmware capsule. Record source URL, checksum, version/date and ESRT correspondence. Do not execute the updater to inspect it.
2. Use [BIOSUtilities](https://github.com/platomav/BIOSUtilities) Dell PFS extraction, following its current supported input format. Record the version/commit and the extracted region size/offset; extraction behavior can change between releases. For example, from its checked-out source:

   ```sh
   python3 main.py "$FIRMWARE" -e -u DellPfsExtract -o "$USB/firmware-extracted"
   ```

3. Confirm container/block CRCs, offsets and output boundaries. BIOS Guard/PFAT chunks may require reconstruction based on their metadata; **do not blindly concatenate them**. Stop if the resulting image cannot be validated.
4. In [UEFITool/UEFIExtract A76](https://github.com/LongSoft/UEFITool/releases/tag/A76), locate Socket Configuration by the shared FFS GUID or matching HII strings. Extract the **PE32 section body**, not the entire FFS wrapper. With a new BIOS, the module/GUID may change; search the actual image.
5. Use [IFRExtractor 1.6.1](https://github.com/LongSoft/IFRExtractor-RS/releases/tag/v1.6.1) to export that PE32 to text; consult its `--help` for the installed build's CLI. Keep the exact binary and full text together.

   ```sh
   python3 -B scripts/ifr_review.py "$IFR_TEXT" --pe32 "$PE32" > "$USB/ifr-facts.json"
   ```

6. Require a unique matching VarStore, the same GUID/attributes/length as the live variable, and agreement between extracted text and raw OneOf opcodes for question IDs, offsets, widths and legal enum values. Check labels against the full IFR; the tool does not infer undocumented semantics. Its default `approved=false` is deliberate.
7. Verify `Base + maximum MMIO range <= 2^physical_address_bits`. The audit's private JSON reports `physical_address_bits`; use that value rather than guessing. For example, 56TiB + 32×64GiB = 58TiB fits a 46-bit/64TiB ceiling. Read the actual IFR help and CPU width; do not assume the multiplier or enum labels are unchanged.

## Record a reviewed private profile and prepare the Shell plan

Only after the review above, make the explicit version confirmation. Set `FIRMWARE` to the downloaded Dell EXE, `OFFICIAL_SHA256` to its published hash, `EXACT_BIOS_VERSION` to the installed version (for example `2.52.2`), and `INITIAL_BAR0_MIB` to the observed starting BAR0 (256 for this R9700). `LIVE_EFIVAR_PATH` is the unique live `SocketCommonRcConfig-*` file found by the audit.

```sh
python3 -B scripts/make_profile.py \
  --baseline "$USB/before.json" --facts "$USB/ifr-facts.json" \
  --firmware "$FIRMWARE" --official-sha256 "$OFFICIAL_SHA256" \
  --confirm-reviewed-version "$EXACT_BIOS_VERSION" \
  --initial-bar0-mib "$INITIAL_BAR0_MIB" \
  --output "$USB/prechange-profile.json" \
  --approved-facts-output "$USB/approved-facts.json"

sudo python3 -B scripts/uefi_plan.py --usb "$USB" \
  --profile "$USB/prechange-profile.json" --facts "$USB/approved-facts.json" \
  --efivar "$LIVE_EFIVAR_PATH"
```

The generator checks live BIOS, GUID, attributes, length and baseline hash. It writes only new files in `REBAR-PLAN`; it does not write NVRAM. If already at the target enum, no firmware write plan is needed. It does not automatically generate plans for unrelated hidden settings. Keep `TARGET_GIB` identical to the baseline; the resize tool rejects a changed target.

In USB Shell, select the correct USB filesystem and root directory. Run:

```text
REBAR-PLAN\CHECK.nsh
REBAR-PLAN\ROUNDTRIP.nsh RUN
REBAR-PLAN\APPLY.nsh RUN
```

Run CHECK and rescue boot first, in the separate recovery checkpoint. Run ROUNDTRIP only in the later change session. Require `ROUNDTRIP_PASS` before APPLY. Each write script refuses to overwrite prior evidence, saves the full variable, compares complete expected files, and never resets automatically. If any check fails, stop; do not reboot or delete guard files to retry blindly. Name ambiguity is a stop condition. The Shell plan has a BIOS version record, but cannot prove the BIOS has not changed since generation: never reuse it after updating firmware.

> [!CAUTION]
> **Manual fallback for 2.52.2 only.** Do not reuse this `0x04`/`0x0003` command on another BIOS/GPU. It bypasses the generated full-variable comparison; prefer `CHECK`/`ROUNDTRIP`/`APPLY`, and require a fresh IFR review.

```text
setup_var.efi SocketCommonRcConfig:0x04(2)=0x0003
setup_var.efi SocketCommonRcConfig:0x04(2)
```

Payload change: `00 00`→`03 00`, only payload offset 4 (the 5th byte) changes. Linux efivarfs adds four attribute bytes, so that byte is at file offset8. EDK2 saved-variable header8 + UTF16 name42 + GUID16 + attributes4 = payload start70 (`0x46`); changed byte74 (`0x4a`), CRC at184 (`0xb8`), complete file188 bytes. Compare generated expected files with a fresh EDK2 save before writing. Never import the Linux118-byte file as an EDK2 dump.

## Linux allocation and persistence

After boot, capture a **new** private baseline, compare the full variable with the original and verify that only the planned bytes changed. The root window must actually fit an aligned target BAR; for this 32GiB target, the 64GiB window accommodates it. The downstream bridges can still show small windows before the resize request.

Create a new runtime profile from this post-change snapshot using the same reviewed firmware/facts and the same `TARGET_GIB`. For this R9700 the firmware-default BAR0 is 256MiB; other hardware must set its observed default with `--initial-bar0-mib`.

```sh
sudo python3 -B scripts/rebar_audit.py --target-gib "$TARGET_GIB" --private-output "$USB/postchange.json"
# Repeat make_profile with postchange.json, the same INITIAL_BAR0_MIB, and new output filenames.
sudo python3 -B scripts/rebar_resize.py --profile "$USB/runtime-profile.json"
sudo python3 -B scripts/rebar_resize.py --profile "$USB/runtime-profile.json" --execute
```

Linux BAR size is `2^(20+n)` bytes: n15=32GiB; n8=256MiB. The kernel's standard interface reallocates the necessary bridge windows; no manual PCI register offset writes are used. The [`resource0_resize` interface](https://github.com/torvalds/linux/blob/v6.1/Documentation/ABI/testing/sysfs-bus-pci#L461) is documented at least as far back as Linux 6.1; this case was verified on Linux 7.0 (`7.0.14-26-pve`). Check the sysfs ABI on your kernel, then verify the GPU's other BARs retain their previous sizes and test a single guest.

Only after manual success, install the audited files (these commands alter the host):

Enable only one resize service. Review and disable an existing implementation before installing a replacement.

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

The service needs no USB. A failed service does not prevent the host boot; do not enable GPU VM autostart until the reboot check succeeds. VMs already using the GPU are never unbound by the script. Run the real reboot checkpoint and inspect `journalctl -b -u rebar-resize.service`.
