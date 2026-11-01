#!/usr/bin/env python3
"""Select only boot/tools/actual backups for a replacement-USB package, not screenshots or test images."""
import argparse
import json
from pathlib import Path
from rebar_audit import require
from usb_archive import volume, safe_name


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--usb", required=True, type=Path)
    p.add_argument("--backup-dir", required=True, help="Actual recovery backup directory relative to USB root")
    p.add_argument("--extra", action="append", default=[], help="Additional required file, relative to USB root")
    a = p.parse_args()
    usb = a.usb.resolve()
    volume(usb)
    require((usb / "EFI/BOOT/BOOTX64.EFI").is_file(), "UEFI fallback loader missing")
    files = set()
    for folder in ["EFI", "loader", "RECOVERY", a.backup_dir]:
        directory = usb.joinpath(*safe_name(folder).parts)
        require(directory.is_dir() or folder in ["loader", "RECOVERY"], "Required boot/backup directory missing")
        files.update(p for p in directory.rglob("*") if p.is_file())
    for name in ["setup_var.efi", "BIOS_IMG.rcv", "PVE-RESCUE.nsh", "CHECK.nsh", "ROUNDTRIP.nsh", "APPLY.nsh", "ROLLBACK.nsh"] + a.extra:
        path = usb.joinpath(*safe_name(name).parts)
        require(path.is_file() or name in ["BIOS_IMG.rcv", "PVE-RESCUE.nsh", "CHECK.nsh", "ROUNDTRIP.nsh", "APPLY.nsh", "ROLLBACK.nsh"], "Required tool/extra file missing")
        if path.is_file():
            files.add(path)
    for path in files:
        rel = path.relative_to(usb)
        require(not path.is_symlink(), "Symlink in recovery selection")
        require(path.suffix.lower() not in [".png", ".jpg", ".jpeg", ".pdf"], "Screenshot/tutorial artifact in recovery selection")
        require(not any(x.lower() in ["restore-drill", "original-screenshots", "original-records", ".git"] for x in rel.parts), "Historical evidence/test-copy directory selected")
    names = sorted(p.relative_to(usb).as_posix() for p in files)
    names.append("RECOVERY-INCLUDE.json")
    dest = usb / "RECOVERY-INCLUDE.json"
    require(not dest.exists(), "Recovery selection exists; review before replacing it")
    dest.write_text(json.dumps(names, indent=2) + "\n")
    print("FUNCTIONAL_RECOVERY_FILES", len(names), "PAYLOAD_BYTES", sum(p.stat().st_size for p in files), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("RECOVERY SELECTION STOP: " + str(error))
