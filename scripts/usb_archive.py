#!/usr/bin/env python3
"""ZIP64 file-tree archive with FAT32-safe parts; no disk formatting or raw disk writes."""
import argparse
import bisect
import hashlib
import io
import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath
from rebar_audit import require


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while chunk := f.read(4 * 2**20):
            h.update(chunk)
    return h.hexdigest()


def volume(path):
    path = Path(path).resolve()
    require(os.path.ismount(path), "USB argument must be its mounted filesystem root")
    if sys.platform == "darwin":
        raw = plistlib.loads(subprocess.check_output(["diskutil", "info", "-plist", str(path)]))
        require(raw.get("MountPoint") == str(path) and "FAT32" in raw.get("FilesystemName", "").upper(), "Expected a mounted FAT32 volume")
        info = {"target": str(path), "fstype": "vfat", "uuid": raw.get("VolumeUUID"), "source": raw.get("DeviceNode")}
    else:
        info = json.loads(subprocess.check_output(["findmnt", "-J", "-o", "TARGET,FSTYPE,UUID,SOURCE", "--mountpoint", str(path)], text=True))["filesystems"][0]
    require(info["fstype"] in ["vfat", "msdos"], "Expected a FAT32 USB volume")
    require(info.get("uuid"), "Filesystem UUID missing")
    return info


class PartsWriter(io.RawIOBase):
    def __init__(self, directory, limit):
        self.directory = Path(directory)
        self.limit = limit
        self.position = 0
        self.current_bytes = 0
        self.file = None
        self.parts = []
        self.hasher = None

    def writable(self):
        return True

    def seekable(self):
        return False

    def tell(self):
        return self.position

    def finish_part(self):
        if self.file:
            self.file.flush()
            os.fsync(self.file.fileno())
            self.file.close()
            self.parts[-1].update(bytes=self.current_bytes, sha256=self.hasher.hexdigest())
            self.file = None

    def write(self, data):
        view = memoryview(data)
        size = len(view)
        while view:
            if self.file is None:
                name = "usb-full.zip.%03d" % (len(self.parts) + 1)
                self.file = (self.directory / name).open("xb")
                self.parts.append({"file": name})
                self.current_bytes = 0
                self.hasher = hashlib.sha256()
            count = min(len(view), self.limit - self.current_bytes)
            chunk = view[:count]
            self.file.write(chunk)
            self.hasher.update(chunk)
            self.current_bytes += count
            self.position += count
            view = view[count:]
            if self.current_bytes == self.limit:
                self.finish_part()
        return size

    def close(self):
        self.finish_part()
        super().close()


class PartsReader(io.RawIOBase):
    def __init__(self, directory, parts):
        self.paths = [Path(directory) / p["file"] for p in parts]
        self.offsets = [0]
        for p in parts:
            self.offsets.append(self.offsets[-1] + p["bytes"])
        self.position = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset if whence == 0 else self.position + offset if whence == 1 else self.offsets[-1] + offset
        require(position >= 0, "Negative seek")
        self.position = position
        return position

    def read(self, size=-1):
        remaining = self.offsets[-1] - self.position
        size = remaining if size < 0 else min(size, remaining)
        if size <= 0:
            return b""
        data = bytearray()
        while size:
            index = bisect.bisect_right(self.offsets, self.position) - 1
            count = min(size, self.offsets[index + 1] - self.position)
            with self.paths[index].open("rb") as f:
                f.seek(self.position - self.offsets[index])
                chunk = f.read(count)
            require(len(chunk) == count, "Truncated archive part")
            data.extend(chunk)
            self.position += count
            size -= count
        return bytes(data)


def open_archive(directory):
    directory = Path(directory)
    receipt = json.loads((directory / "parts.json").read_text())
    require(receipt.get("format") == "concatenated-zip64-v1", "Unknown archive format")
    for number, part in enumerate(receipt["parts"], 1):
        expected_name = "recovery-usb.zip" if receipt.get("single_zip") else "usb-full.zip.%03d" % number
        require(part["file"] == expected_name and (not receipt.get("single_zip") or len(receipt["parts"]) == 1), "Invalid archive part name/order")
        path = directory / part["file"]
        require(path.stat().st_size == part["bytes"] and digest(path) == part["sha256"], "Archive part hash mismatch")
    return receipt, PartsReader(directory, receipt["parts"])


def safe_name(name):
    path = PurePosixPath(name)
    require(not path.is_absolute() and ".." not in path.parts and "\\" not in name and ":" not in name, "Unsafe archive path")
    require(bool(path.parts), "Empty archive path")
    return path


def inspect_archive(z):
    names = []
    folded = set()
    for item in z.infolist():
        name = str(safe_name(item.filename))
        require(name.casefold() not in folded, "Duplicate or case-colliding archive path")
        folded.add(name.casefold())
        require(not stat.S_ISLNK(item.external_attr >> 16), "Symlink in archive")
        require(not item.is_dir(), "Archive should contain regular files only")
        require(item.file_size <= 2**32 - 1, "A file exceeds FAT32's size limit")
        names.append(name)
    return names


def verify(directory):
    receipt, stream = open_archive(directory)
    with zipfile.ZipFile(stream) as z:
        names = inspect_archive(z)
        manifest = json.loads(z.read("ARCHIVE-MANIFEST.json"))
        expected = {x["path"]: x for x in manifest["files"]}
        require(set(names) == set(expected) | {"ARCHIVE-MANIFEST.json"}, "Archive inventory mismatch")
        for n, item in enumerate(expected.values(), 1):
            h = hashlib.sha256()
            count = 0
            with z.open(item["path"]) as f:
                while chunk := f.read(4 * 2**20):
                    h.update(chunk)
                    count += len(chunk)
            require(count == item["bytes"] and h.hexdigest() == item["sha256"], "Archived file mismatch")
            if n % 25 == 0:
                print("VERIFY_FILES", n, "of", len(expected), flush=True)
    print("ZIP_CRC_AND_ALL_FILE_SHA256_PASS", len(expected), flush=True)
    return receipt, manifest


def create(usb, output, limit, include_list=None, single=False):
    usb = Path(usb).resolve()
    info = volume(usb)
    output = Path(output).resolve()
    require(output.is_relative_to(usb) and output != usb, "Archive output must be below this USB")
    require(output.parent != usb, "Use a dedicated archive container, for example USB/ARCHIVES/session")
    require(not output.exists(), "Archive output already exists")
    require(0 < limit <= 2**31, "Part size must be at most 2GiB")
    files = []
    if include_list:
        selected = json.loads(Path(include_list).read_text())
        require(isinstance(selected, list) and selected and len(selected) == len(set(selected)), "Invalid recovery include list")
        candidates = [usb.joinpath(*safe_name(name).parts) for name in selected]
        require(all(p.is_file() for p in candidates), "A required recovery file is missing")
    else:
        candidates = sorted(usb.rglob("*"))
    for path in candidates:
        if path.is_relative_to(output.parent):
            continue
        require(not path.is_symlink(), "USB contains a symlink; stop")
        if path.is_file():
            require(path.relative_to(usb).as_posix() != "ARCHIVE-MANIFEST.json", "Reserved archive manifest name")
            safe_name(path.relative_to(usb).as_posix())
            require(path.stat().st_size <= 2**32 - 1, "Source file exceeds FAT32 limit")
            files.append(path)
    require(files, "Source USB is empty")
    total = sum(p.stat().st_size for p in files)
    require(not single or total + 16 * 2**20 < 2**32, "Recovery ZIP would exceed FAT32 limit; use multipart mode")
    require(shutil.disk_usage(usb).free > total + 64 * 2**20, "Not enough space for a complete archive")
    output.mkdir(parents=True)
    writer = (output / "recovery-usb.zip").open("xb") if single else PartsWriter(output, limit)
    inventory = []
    try:
        with zipfile.ZipFile(writer, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
            for n, path in enumerate(files, 1):
                before = path.stat()
                h = hashlib.sha256()
                count = 0
                name = path.relative_to(usb).as_posix()
                with path.open("rb") as src, z.open(name, "w", force_zip64=True) as dest:
                    while chunk := src.read(4 * 2**20):
                        dest.write(chunk)
                        h.update(chunk)
                        count += len(chunk)
                after = path.stat()
                require(count == before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns, "Source changed during archive")
                inventory.append({"path": name, "bytes": count, "sha256": h.hexdigest()})
                print("ARCHIVE_FILES", n, "of", len(files), "BYTES", writer.tell(), flush=True)
            z.writestr("ARCHIVE-MANIFEST.json", json.dumps({"files": inventory, "source_volume": info}, indent=2))
    finally:
        writer.close()
    parts = [{"file": "recovery-usb.zip", "bytes": (output / "recovery-usb.zip").stat().st_size, "sha256": digest(output / "recovery-usb.zip")}] if single else writer.parts
    receipt = {"format": "concatenated-zip64-v1", "single_zip": single, "parts": parts, "source_bytes": total,
               "source_files": len(inventory), "created_unix": int(time.time()), "source_volume": info}
    (output / "parts.json").write_text(json.dumps(receipt, indent=2) + "\n")
    os.sync()
    verify(output)
    (output / "VERIFIED.json").write_text(json.dumps({"all_file_sha256_and_zip_crc": True, "source_files": len(inventory)}, indent=2) + "\n")
    os.sync()


def extract(directory, target, confirmation):
    target = Path(target).resolve()
    info = volume(target)
    require(info["uuid"] == confirmation, "Confirm the destination filesystem UUID")
    os_metadata = {".DS_Store", ".Spotlight-V100", ".fseventsd", ".Trashes", "System Volume Information"}
    require(not any(p.name not in os_metadata for p in target.iterdir()), "Destination USB must be empty except OS metadata")
    receipt, manifest = verify(directory)
    require(shutil.disk_usage(target).free > receipt["source_bytes"] + 64 * 2**20, "Destination is too small")
    for item in manifest["files"]:
        require(not target.joinpath(*safe_name(item["path"]).parts).exists(), "Destination file already exists; refuse overwrite")
    _, stream = open_archive(directory)
    with zipfile.ZipFile(stream) as z:
        for item in manifest["files"]:
            rel = safe_name(item["path"])
            dest = target.joinpath(*rel.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256()
            with z.open(item["path"]) as src, dest.open("xb") as out:
                while chunk := src.read(4 * 2**20):
                    out.write(chunk)
                    h.update(chunk)
                out.flush()
                os.fsync(out.fileno())
            require(h.hexdigest() == item["sha256"] and digest(dest) == item["sha256"], "Extracted file readback mismatch")
    (target / "MIGRATION.json").write_text(json.dumps({"source_volume": receipt["source_volume"], "destination_volume": info,
        "warning": "Historical tools may pin the old USB UUID. Use current generic tools with this volume. Never transplant firmware/ESP backups to another machine."}, indent=2) + "\n")
    os.sync()
    print("EXTRACT_AND_READBACK_PASS; boot test is still required", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("create")
    c.add_argument("--usb", required=True, type=Path)
    c.add_argument("--output", required=True, type=Path)
    c.add_argument("--part-bytes", type=int, default=2**31)
    c.add_argument("--include-list", required=True, type=Path, help="Explicit functional recovery files, not a tutorial/evidence dump")
    c.add_argument("--single-zip", action="store_true", help="One conventional ZIP when it fits FAT32")
    v = sub.add_parser("verify")
    v.add_argument("archive", type=Path)
    e = sub.add_parser("extract")
    e.add_argument("archive", type=Path)
    e.add_argument("--usb", required=True, type=Path)
    e.add_argument("--confirm-target-uuid", required=True)
    a = p.parse_args()
    if a.mode == "create":
        create(a.usb, a.output, a.part_bytes, a.include_list, a.single_zip)
    elif a.mode == "verify":
        verify(a.archive)
    else:
        extract(a.archive, a.usb, a.confirm_target_uuid)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("ARCHIVE STOP: " + str(error))
