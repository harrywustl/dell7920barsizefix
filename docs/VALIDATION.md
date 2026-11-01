# Validation with fewer reboots

[简体中文](VALIDATION.zh-CN.md)

| Stage | Combine these checks | Required result |
|---|---|---|
| Online preparation | Firmware/IFR, PCI topology, IOMMU, address limits, backups and rescue files | Exact-version review and backup integrity pass |
| First USB boot | Read-only CHECK and variable save, then PVE rescue | USB loader/kernel/initrd boots the existing PVE root |
| Change session | CHECK, full-variable round trip, then APPLY | Original fully restored during test; only planned bytes change on apply |
| Modified PVE boot | Variable diff, root window, manual resize, one guest, service installation | Host/guest checks pass before enabling automation |
| Final normal reboot | Service journal, startup order, host and guest recheck | Actual resize from firmware default occurs before PVE guests |

This normally takes **2 USB Shell boots + 3 PVE boots** (PVE rescue, modified PVE, final normal reboot) from a prepared host, plus an optional cold recovery-menu test. If recovery-menu access is unverified, test it separately before the change session. Record relevant F2 settings in one visit; exiting F2 can cause an additional reboot. Keep a local console available.

## Acceptance checks

- **Host:** only the reviewed variable bytes changed; root MMIO fits CPU address limits and an aligned target BAR; all upstream bridges cover the BAR; other BAR sizes are unchanged; VFIO is rebound; storage, boot and memory remain healthy.
- **Guest:** test one VM per physical GPU at a time. Require target BAR size, AMDGPU binding, all usable VRAM visible, `/dev/kfd`, ROCm discovery and a small HIP allocation/write/readback test. BAR size and usable VRAM need not be numerically identical.
- **Persistence:** inspect the current boot's service journal and ordering before `pve-guests.service`. Starting the service when the BAR is already enlarged tests only its no-op path.
- **Recovery:** distinguish file checks, a real USB/rescue boot, recovery-menu access and an actual firmware recovery. Each proves a different capability.

Copy `guest_check.py` and `rebar_audit.py` into the same guest directory:

```sh
sudo python3 -B guest_check.py --hip-test
```

Without `--hip-test`, the script does not allocate test VRAM. Wait with a timeout for AMDGPU and VRAM readiness; a responding guest agent alone is insufficient.

## Practical checks

- Use direct `qm status` / `pct status` and actual QEMU/VFIO holders; PVE cluster summaries may lag.
- FAT32 filenames cannot contain colons. Sanitize filenames only, never the PCI address passed to sysfs.
- Invoke Python explicitly on `noexec` mounts; do not weaken mount protections to run tools.
- Decompress ESP backups into ordinary USB test files, verify raw hashes and run `fsck.fat -n` on those files. Do not overwrite a working ESP to rehearse recovery.
- Verify and extract the recovery package onto a new FAT32 USB, check restored hashes, then test F12 → UEFI USB → Shell → PVE rescue. Extraction alone does not prove bootability.

Keep actual results and command outputs in your private repository. Re-run the relevant gates after firmware, topology or rescue-kernel changes.
