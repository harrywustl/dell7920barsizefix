#!/usr/bin/env python3
"""Private USB-only ESP backup/verification. Restoring requires exact PARTUUID confirmation."""
import argparse
import gzip
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from rebar_audit import require, save_private
from usb_archive import volume, digest


def stream_digest(stream):
    h, count = hashlib.sha256(), 0
    while chunk := stream.read(4 * 2**20):
        h.update(chunk)
        count += len(chunk)
    return count, h.hexdigest()


def device_info(partuuid):
    require(len(partuuid) == 36 and all(c in "0123456789abcdef-" for c in partuuid.lower()), "Invalid PARTUUID")
    dev = (Path("/dev/disk/by-partuuid") / partuuid).resolve(strict=True)
    st = dev.stat()
    require(stat.S_ISBLK(st.st_mode) and (Path("/sys/class/block") / dev.name / "partition").exists(), "Refuse non-partition target")
    kind = subprocess.check_output(["blkid", "-p", "-s", "PART_ENTRY_TYPE", "-o", "value", str(dev)], text=True).strip().lower()
    require(kind == "c12a7328-f81f-11d2-ba4b-00a0c93ec93b", "Target is not a GPT ESP")
    mm = f"{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}"
    require(all(line.split()[2] != mm for line in Path("/proc/self/mountinfo").read_text().splitlines()), "ESP is mounted; stop")
    size = int(subprocess.check_output(["blockdev", "--getsize64", str(dev)]))
    return dev, size


def backup(usb, ids):
    usb = Path(usb).resolve()
    info = volume(usb)
    require(ids and len(set(ids)) == len(ids), "Choose unique ESP PARTUUIDs")
    devices = [(uid, *device_info(uid)) for uid in ids]
    require(os.statvfs(usb).f_bavail * os.statvfs(usb).f_frsize > sum(size for _, _, size in devices) + 64 * 2**20, "Insufficient USB space")
    out = usb / "REBAR-BACKUP"
    require(not out.exists(), "Backup exists; never overwrite the original")
    out.mkdir()
    manifest = {"usb_uuid": info["uuid"], "ESP": [], "efi_variables": []}
    for n, (uid, dev, size) in enumerate(devices, 1):
        label = f"esp{n}"
        image = out / f"esp-{label}-before.img.gz"
        h, count = hashlib.sha256(), 0
        with dev.open("rb", buffering=0) as src, image.open("xb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=1, mtime=0) as dest:
                while chunk := src.read(4 * 2**20):
                    dest.write(chunk)
                    h.update(chunk)
                    count += len(chunk)
            raw.flush()
            os.fsync(raw.fileno())
        require(count == size, "Incomplete ESP read")
        with gzip.open(image, "rb") as f:
            require(stream_digest(f) == (size, h.hexdigest()), "Backup decompression/hash verification failed")
        manifest["ESP"].append({"label": label, "partuuid": uid, "raw_bytes": size, "raw_sha256": h.hexdigest(),
                                "gzip_bytes": image.stat().st_size, "gzip_sha256": digest(image), "image": image.name})
        print("ESP_BACKUP_AND_DECOMPRESSED_HASH_PASS", n, flush=True)
    variables = list(Path("/sys/firmware/efi/efivars").glob("SocketCommonRcConfig-*"))
    require(len(variables) == 1, "Ambiguous/missing firmware variable")
    raw = variables[0].read_bytes()
    (out / "firmware.before.efivarfs.bin").write_bytes(raw)
    manifest["efi_variables"].append({"filename": variables[0].name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    save_private(out / "backup-manifest.json", manifest)
    os.sync()


def verify_or_restore(manifest_path, label, usb, restore=False, confirmation=None):
    usb = Path(usb).resolve()
    volume(usb)
    manifest_path = Path(manifest_path).resolve()
    require(manifest_path.is_relative_to(usb), "Manifest must be on the selected USB")
    data = json.loads(manifest_path.read_text())
    matches = [x for x in data["ESP"] if x["label"] == label]
    require(len(matches) == 1, "Backup label missing or ambiguous")
    item = matches[0]
    image_name = item.get("image", f"esp-{label}-before.img.gz")
    require(Path(image_name).name == image_name, "Unsafe image name")
    image = manifest_path.parent / image_name
    require(image.stat().st_size == item["gzip_bytes"] and digest(image) == item["gzip_sha256"], "Compressed backup mismatch")
    with gzip.open(image, "rb") as f:
        require(stream_digest(f) == (item["raw_bytes"], item["raw_sha256"]), "Raw backup mismatch")
    dev, size = device_info(item["partuuid"])
    require(size == item["raw_bytes"], "Target size differs")
    if not restore:
        print("CHECK_ONLY_PASS; no block-device write")
        return
    require(confirmation == item["partuuid"], "Exact PARTUUID confirmation required")
    with gzip.open(image, "rb") as src, dev.open("r+b", buffering=0) as dest:
        count = 0
        while chunk := src.read(4 * 2**20):
            view = memoryview(chunk)
            while view:
                written = dest.write(view)
                require(written is not None and written > 0, "Short device write")
                view = view[written:]
            count += len(chunk)
        require(count == size, "Incomplete restore")
        os.fsync(dest.fileno())
    with dev.open("rb", buffering=0) as f:
        require(stream_digest(f) == (size, item["raw_sha256"]), "Restored ESP readback mismatch")
    print("ONE_ESP_RESTORED_AND_READBACK_VERIFIED")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="mode", required=True)
    b = sub.add_parser("create")
    b.add_argument("--usb", required=True, type=Path)
    b.add_argument("--esp-partuuid", action="append", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--usb", required=True, type=Path)
    v.add_argument("--manifest", required=True, type=Path)
    v.add_argument("--label", required=True)
    v.add_argument("--restore", action="store_true")
    v.add_argument("--confirm-partuuid")
    a = p.parse_args()
    if a.mode == "create":
        backup(a.usb, a.esp_partuuid)
    else:
        verify_or_restore(a.manifest, a.label, a.usb, a.restore, a.confirm_partuuid)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("BACKUP/RESTORE STOP: " + str(error))
