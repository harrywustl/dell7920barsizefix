# Agent prompt: investigate and adapt safely

[简体中文](prompt.zh-CN.md)

Read README and the FIRMWARE, RECOVERY, USB, VALIDATION and PRIVACY guides before acting.

Goal: investigate a Dell/UEFI GPU BAR constraint and adapt this procedure to the actual hardware/BIOS. Begin read-only. Do not infer authorization to write firmware, unbind devices, shut down VMs, change boot parameters or reboot from an investigation request. Explain the specific proposed change and wait for explicit authorization where absent.

1. Ask for connection/mount details only if missing; never request private-key contents. Follow PRIVACY: raw logs/screenshots, local profiles and review records go in the user's own private repository; recovery backups go offline on USB/NAS. Public guides contain reusable steps and compatibility facts, never conversation history, personal counts/timings or internal audit receipts. Public output excludes instance IDs, IP/MAC/account names, BDFs, partition/boot UUIDs and private paths. Do not publish original screenshots with identifiers or metadata.
2. Run `rebar_audit.py`; compare a prior private baseline when available. Discover the current GPU rather than assuming a BDF; stop on ambiguity. Check all functions/bridges/root space, address limits, supported sizes, VFIO/IOMMU and live holders. Use direct VM status rather than cached cluster summaries.
3. Match exact installed BIOS version/date/ESRT to official firmware. Extract validated PE32/IFR offline. Run `ifr_review.py --pe32`, compare VarStore GUID/attributes/length with live data and review offsets/widths/enums/help text. A shared name or same size does not prove an old offset is valid. Never bulk-import another machine's variable or reuse old NVRAM after an update.
4. Prepare verified USB-only backups and a model-appropriate local recovery path before retaining firmware changes. Separate actual boot/recovery tests from file-hash checks. Preserve honest limits: no full SPI backup means no universal no-POST recovery guarantee.
5. Only after review and authorization, generate a private profile and guarded Shell plan. Prefer the smallest field change; require full expected-variable comparisons and a verified round trip. Never auto-reboot on failure or delete evidence guards to retry. Do not use arbitrary force-flash or weaken protections.
6. After modified boot, verify exact variable diff and root window. Keep all GPU VMs stopped before standard sysfs resize; rebind original VFIO functions in finally. Refuse other devices in the branch or active QEMU/VFIO holders. Inspect failures before proposing boot parameters or more invasive PCI operations.
7. Verify one guest at a time. Wait with timeout for AMDGPU/VRAM readiness, then check guest BAR, all usable VRAM visible, ROCm and a small HIP memory test. Do not claim an inference speedup without a benchmark.
8. After manual success, create version/topology-bound persistence and validate an actual reboot from the firmware-default small BAR. Do not silently replace the user's already-working service. Provide exact rollback/upgrade instructions and current final VM state.
9. Use the consolidated checkpoints in VALIDATION to reduce reboots without skipping the proven rescue baseline. Keep a complete private command/output ledger, a concise bilingual public guide, reviewed screenshots and privacy checks. No pushes/uploads, firmware writes or reboots unless within the user's authorization.

If any prerequisite differs, report the exact mismatch and the next read-only check. Never mark unknown firmware semantics “approved” just to make a script pass.
