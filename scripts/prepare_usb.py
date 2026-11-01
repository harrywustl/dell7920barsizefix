#!/usr/bin/env python3
"""Populate an already formatted FAT32 USB. Never formats or alters firmware boot entries."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path, PurePosixPath
from rebar_audit import require, save_private
from usb_archive import volume, digest

TOOLS = [
    ("https://github.com/pbatard/UEFI-Shell/releases/download/26H2/shellx64.efi", "EFI/BOOT/BOOTX64.EFI", "4922d9885ac92d8ab58e5da4eb8ad6cbfbe651ea9cdc03a1ba67355e5ede83b1"),
    ("https://github.com/datasone/setup_var.efi/releases/download/0.3.1/setup_var.efi", "setup_var.efi", "cbe5777b61276d3f3506a28b34845326e92f6c171bff59177e3912fe20f49840"),
]


def copy_verified(src, dest):
    require(src.is_file() and not dest.exists(), "Missing source or destination already exists")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as a, dest.open("xb") as b:
        shutil.copyfileobj(a, b, 2**20)
        b.flush()
        os.fsync(b.fileno())
    require(digest(src) == digest(dest), "Copy readback hash failed")


def prepare(usb, esp=None, entry=None, bios_image=None, bios_sha=None):
    usb = Path(usb).resolve()
    info = volume(usb)
    require(not any(usb.iterdir()), "Use an empty USB; existing content will not be overwritten")
    for url, name, expected in TOOLS:
        dest = usb / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=90) as src, dest.open("xb") as out:
            shutil.copyfileobj(src, out, 2**20)
            out.flush()
            os.fsync(out.fileno())
        require(digest(dest) == expected, "Pinned tool SHA256 mismatch")
        raw = dest.read_bytes()
        require(raw[:2] == b"MZ", "Not a PE executable")
        pe = int.from_bytes(raw[0x3c:0x40], "little")
        require(raw[pe:pe + 4] == b"PE\x00\x00" and int.from_bytes(raw[pe + 4:pe + 6], "little") == 0x8664, "Not x86-64 PE")
        require(int.from_bytes(raw[pe + 24 + 68:pe + 24 + 70], "little") == 10, "Not an EFI application")
    if esp or entry:
        require(esp is not None and entry is not None, "Provide both --esp-readonly-mount and --entry")
        esp = Path(esp).resolve()
        require(os.path.ismount(esp), "ESP must be mounted separately read-only")
        require("ro" in subprocess.check_output(["findmnt", "-n", "-o", "OPTIONS", "--mountpoint", str(esp)], text=True).strip().split(","), "Source ESP is not read-only")
        require(Path(entry).name == entry and entry.endswith(".conf"), "Invalid loader entry name")
        conf = esp / "loader/entries" / entry
        text = conf.read_text()
        require(any(line.strip().startswith("options ") and "root=ZFS=" in line and "boot=zfs" in line for line in text.splitlines()), "Only the documented systemd-boot/ZFS rescue path is supported")
        paths = ["EFI/systemd/systemd-bootx64.efi", "loader/entries/" + entry]
        initrds = []
        for line in text.splitlines():
            pieces = line.split(None, 1)
            if len(pieces) == 2 and pieces[0] in ["linux", "initrd"]:
                rel = PurePosixPath(pieces[1].lstrip("/"))
                require(".." not in rel.parts and "\\" not in str(rel), "Unsafe loader path")
                paths.append(str(rel))
                if pieces[0] == "initrd":
                    initrds.append(str(rel))
        require(len(paths) >= 4 and initrds, "Missing kernel/initrd")
        for rel in paths:
            copy_verified(esp / rel, usb / rel)
        listing = "\n".join(subprocess.check_output(["lsinitramfs", str(usb / rel)], text=True) for rel in initrds)
        require("zfs.ko" in listing and "scripts/local-top/zfs" in listing, "Rescue initrd lacks ZFS support")
        (usb / "loader/loader.conf").write_text("default " + entry + "\ntimeout 10\neditor no\n")
        (usb / "PVE-RESCUE.nsh").write_bytes(b"@echo -off\r\n\\EFI\\systemd\\systemd-bootx64.efi\r\n")
    if bios_image:
        require(bios_sha and len(bios_sha) == 64 and digest(bios_image) == bios_sha.lower(), "Exact official recovery image digest required")
        copy_verified(Path(bios_image), usb / "BIOS_IMG.rcv")
    save_private(usb / "USB-PROVENANCE.json", {"volume": info, "tools": [{"source": u, "file": n, "sha256": h} for u, n, h in TOOLS],
        "shell_digest_source": "Publisher release digest", "setup_var_digest_source": "Locally observed digest, not publisher-signed", "actual_boot_test_completed": False})
    os.sync()
    print("USB_FILES_HASH_VERIFIED; perform F12 Shell and rescue boot tests before firmware writes")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--usb", type=Path, required=True)
    p.add_argument("--esp-readonly-mount", type=Path)
    p.add_argument("--entry")
    p.add_argument("--bios-image", type=Path)
    p.add_argument("--bios-sha256")
    a = p.parse_args()
    prepare(a.usb, a.esp_readonly_mount, a.entry, a.bios_image, a.bios_sha256)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("USB PREPARATION STOP: " + str(error))
