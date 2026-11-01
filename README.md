# Dell Precision 7920 Tower: 32GiB GPU BAR on Proxmox

[简体中文](README.zh-CN.md)

Reference configuration: **BIOS 2.52.2**, Radeon AI PRO R9700, PVE kernel 7.0.14-26-pve and QEMU 11.0.3, with **32GiB BAR0** on host and guest. Other BIOS versions require fresh firmware review. BAR size alone does not establish an inference speedup.

## What actually fixes it

1. UEFI boot, Above 4GB decoding and adequate high MMIO space.
2. On this exact BIOS, change **only MMIO High Granularity** from enum `0` to `3`, providing a 64GiB root window. Keep MMIO High Base unchanged.
3. Before starting the GPU VM, unbind its idle VFIO functions, request **BAR0 exponent `15`** through Linux `resource0_resize`, verify allocation, then rebind VFIO.
4. Run the checked resize before `pve-guests.service` on subsequent boots.

This procedure uses a hidden firmware setting and the standard Linux resize interface. It requires no ReBarDxe injection or BIOS-code flashing. A 64GiB MMIO window is device address space; it does **not consume 64GiB of system RAM**. PCIe bus allocation, VMD and USB settings are not BAR-size controls.

## Start here

Use a local Linux console or your own SSH connection. Commands below run **on the host**. Store raw reports privately and recovery backups on USB; follow the [data policy](docs/PRIVACY.md). Python 3.10+; standard library only. Read-only checks may need root.

```sh
sudo python3 -B scripts/rebar_audit.py --private-output "$USB/before.json"
# Exit 2 means review needed; a small root window is an expected initial finding.
```

The report on stdout omits instance identifiers. The opt-in JSON contains device identities, topology and resource addresses: keep it private. More than one candidate GPU requires explicit local selection with `--gpu`.

| Order | Action | Checkpoint |
|---|---|---|
| 1 | [Audit firmware and hardware](docs/FIRMWARE.md) | Exact BIOS image/IFR, live variable and CPU address limit agree |
| 2 | [Prepare recovery USB and backups](docs/USB.md) | Hashes, decompression and offline recovery-file checks pass |
| 3 | Boot USB; run read-only CHECK, then PVE rescue | Original PVE/ZFS boots using USB loader/kernel/initrd |
| 4 | Boot USB again; guarded round trip, then APPLY | Complete original restored during test; only reviewed field changes on apply |
| 5 | Boot PVE; check variable and root window; resize idle GPU | Host BAR0=32GiB and every upstream bridge covers it |
| 6 | Test one GPU VM, then install boot service | Guest BAR, AMDGPU, ROCm/HIP pass; shut down VM normally |
| 7 | Normal host reboot and final check | Boot service actually starts with 256MiB and produces 32GiB before PVE guests |

**Usually three normal boot cycles**, plus a separate initial cold-start recovery-menu test if not already proven. Record necessary F2 settings in one visit. Some machines reboot when exiting F2; count that extra transition. Do not combine APPLY with an untested rescue path merely to reduce the count. [Validation checkpoints](docs/VALIDATION.md).

## BIOS settings that matter

![Above 4GB enabled](docs/images/above-4g.png)

![Legacy Option ROMs disabled](docs/images/legacy-option-roms.png)

Use UEFI, enable Above 4GB and disable Legacy Option ROMs. Enable VT-d for passthrough. These unsigned tools require Secure Boot disabled; that is a tool requirement. Preserve working storage/boot settings. [BIOS reference screens](docs/SCREENSHOTS.md).

## Repeat after a BIOS update or GPU move

```sh
sudo python3 -B scripts/rebar_audit.py \
  --baseline "$USB/before.json" --private-output "$USB/after.json"
```

The script discovers the current GPU path and reports changed BIOS/build, GPU identity, bridges, branch membership, IOMMU isolation, supported BAR sizes and available aligned root space. **It never approves a new BIOS offset.** Re-extract and cross-check IFR before generating another firmware write plan. A moved GPU also requires reviewing the Proxmox PCI mapping and replacing the old private runtime profile.

## Reusable tools

| Script | Default behavior |
|---|---|
| `rebar_audit.py` | Read-only discovery; redacted stdout, optional private JSON |
| `ifr_review.py` | Parse IFR text; `--pe32` independently checks raw opcode widths/offsets/options |
| `make_profile.py` | Create a private profile only after explicit exact-version review confirmation |
| `uefi_plan.py` | Generate guarded CHECK / ROUNDTRIP / APPLY / ROLLBACK; never writes firmware itself |
| `rebar_resize.py` | Check only; `--execute` required for idle VFIO unbind/resize/rebind |
| `guest_check.py` | Run inside the guest; waits for AMDGPU, checks BAR/VRAM/ROCm; optional `--hip-test` |
| `prepare_usb.py` | Populate an **empty, already formatted** USB; never formats disks |
| `esp_backup.py` | USB-only backup/verify; restore additionally requires exact target PARTUUID |
| `usb_archive.py` | Explicit recovery-file selection; single ZIP when it fits FAT32, otherwise ≤2GiB parts; verified USB reconstruction |
| `recovery_manifest.py` | Select boot/tools/actual backups, exclude screenshots and test-image copies |
| `privacy_check.py` | Text/PNG metadata checks; optional private screenshot hash allowlist |

Generate profiles from the current machine and validate manual resizing before enabling automation. Use only one resize service; review any existing implementation before replacing it.

## Rollback and BIOS upgrades

**Before a BIOS upgrade:** disable the automatic BAR service; while still on the old, audited BIOS, restore only this custom hidden field to its recorded original value and verify it. Keep normal SATA/UEFI/VT-d settings recorded. There is no blanket need to reset every BIOS setting just for this workaround; follow the target firmware's own release instructions. After updating, keep automation disabled until fresh investigation and IFR review pass. [Rollback, upgrade and no-POST limits](docs/RECOVERY.md).

Keep raw logs/screenshots and local profiles in your own private repository; keep recovery images and the complete USB package offline on USB/NAS. Credentials belong in neither Git repository. [Privacy boundaries](docs/PRIVACY.md).

## Agent prompt, tests and references

[Reusable agent prompt](prompt.md) · [Safety tests](tests/test_safety.py)

```sh
python3 -B -m unittest discover -s tests -v
python3 -B scripts/privacy_check.py .
```

[Original V100 discussion](https://github.com/xCuri0/ReBarUEFI/discussions/331) · [Linux 7.0 resize implementation](https://github.com/torvalds/linux/blob/v7.0/drivers/pci/pci-sysfs.c) · [QEMU 11.0.3 VFIO](https://github.com/qemu/qemu/blob/v11.0.3/hw/vfio/pci.c) · [Dell recovery](https://www.dell.com/support/kbdoc/en-us/000132453/how-to-recover-the-bios-on-a-dell-computer-or-tablet)
