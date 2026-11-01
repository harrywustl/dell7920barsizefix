#!/usr/bin/env python3
"""Read-only PCI/firmware audit. Private JSON is opt-in; stdout omits identifiers."""
import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def read(path, default=""):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def save_private(path, data):
    path = Path(path)
    require(not path.exists(), "Output exists; choose a new file")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def resources(device):
    return [[int(x, 16) for x in line.split()]
            for line in device.joinpath("resource").read_text().splitlines()]


def resource_size(row):
    return row[1] - row[0] + 1 if row[0] else 0


def capture(gpu_arg=None, target_gib=32):
    base = Path("/sys/bus/pci/devices")
    candidates = [p for p in base.iterdir()
                  if read(p / "class").startswith("0x03") and (p / "resource0_resize").exists()]
    if gpu_arg:
        require(re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", gpu_arg), "Invalid BDF")
        gpu = base / gpu_arg
        require(gpu in candidates, "Selected display device has no BAR0 resize interface")
    else:
        require(len(candidates) == 1, "GPU selection is ambiguous; use --gpu with a locally discovered BDF")
        gpu = candidates[0]
    target = target_gib * 2**30
    require(target_gib > 0 and target & (target - 1) == 0, "Target must be a power of two")
    exponent = target.bit_length() - 1 - 20
    nodes = [gpu.resolve()]
    parent = nodes[0].parent
    while re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", parent.name):
        nodes.append(parent)
        parent = parent.parent
    root_bus = parent.name.removeprefix("pci")
    root_port = nodes[-1]
    branch = sorted(p.name for p in base.iterdir() if p.resolve().is_relative_to(root_port))
    functions = sorted(p.name for p in base.iterdir()
                       if p.name.rsplit(".", 1)[0] == gpu.name.rsplit(".", 1)[0])
    states = {}
    for bdf in branch:
        dev = base / bdf
        group = dev / "iommu_group"
        states[bdf] = {
            "identity": {k: read(dev / k) for k in ["vendor", "device", "subsystem_vendor", "subsystem_device", "class"]},
            "driver": (dev / "driver").resolve().name if (dev / "driver").exists() else None,
            "resources": resources(dev),
            "iommu_members": sorted(p.name for p in (group / "devices").iterdir()) if group.exists() else [],
        }
    windows = []
    for line in Path("/proc/iomem").read_text().splitlines():
        match = re.fullmatch(r"\s*([0-9a-f]+)-([0-9a-f]+) : PCI Bus " + re.escape(root_bus), line)
        if match:
            a, b = (int(v, 16) for v in match.groups())
            if a >= 2**32:
                windows.append([a, b])
    variables = list(Path("/sys/firmware/efi/efivars").glob("SocketCommonRcConfig-*"))
    variable = None
    if len(variables) == 1:
        raw = variables[0].read_bytes()
        variable = {"filename": variables[0].name, "attributes": int.from_bytes(raw[:4], "little"),
                    "data_size": len(raw) - 4, "sha256": hashlib.sha256(raw).hexdigest(),
                    "base_raw_2_52_only": int.from_bytes(raw[4:8], "little"),
                    "granularity_raw_2_52_only": int.from_bytes(raw[8:10], "little")}
    bits = re.search(r"address sizes\s*:\s*(\d+) bits physical", read("/proc/cpuinfo"))
    mask = int(read(gpu / "resource0_resize", "0"), 16)
    firmware = {k: read(Path("/sys/class/dmi/id") / k) for k in ["sys_vendor", "product_name", "bios_version", "bios_date"]}
    firmware["esrt_versions"] = {read(p / "fw_class"): read(p / "fw_version")
                                for p in Path("/sys/firmware/efi/esrt/entries").glob("entry*")}
    data = {"schema": 1, "firmware": firmware, "kernel": os.uname().release,
            "gpu": gpu.name, "functions": functions, "root_bus": root_bus,
            "bridges": [p.name for p in reversed(nodes[1:])], "branch": branch,
            "devices": states, "high_root_windows": windows, "resize_mask": mask,
            "target_bytes": target, "target_exponent": exponent,
            "physical_address_bits": int(bits[1]) if bits else None,
            "variable_count": len(variables), "variable": variable,
            "iommu_enabled": bool(list(Path("/sys/kernel/iommu_groups").glob("*"))),
            "secure_boot": None,
            "memtotal_kib": int(read("/proc/meminfo").splitlines()[0].split()[1]),
            "boot_id": read("/proc/sys/kernel/random/boot_id")}
    secure = list(Path("/sys/firmware/efi/efivars").glob("SecureBoot-*"))
    if len(secure) == 1:
        data["secure_boot"] = bool(secure[0].read_bytes()[4])
    return data


def comparison(now, baseline):
    changes = []
    for key in ["firmware", "gpu", "functions", "bridges", "branch", "physical_address_bits", "resize_mask"]:
        if now.get(key) != baseline.get(key):
            changes.append(key)
    for bdf in baseline.get("devices", {}):
        old = baseline["devices"][bdf]
        new = now["devices"].get(bdf, {})
        for key in ["identity", "iommu_members"]:
            if old.get(key) != new.get(key):
                changes.append("device_" + key)
    return sorted(set(changes))


def summary(data, baseline=None):
    target = data["target_bytes"]
    aligned_fit = any(((a + target - 1) // target) * target + target - 1 <= b
                      for a, b in data["high_root_windows"])
    gpu = data["devices"][data["gpu"]]
    return {"bios_version": data["firmware"]["bios_version"], "kernel": data["kernel"],
            "bar0_bytes": resource_size(gpu["resources"][0]),
            "target_bytes": target, "target_supported": bool(data["resize_mask"] & (1 << data["target_exponent"])),
            "aligned_root_space_available": aligned_fit, "iommu_enabled": data["iommu_enabled"],
            "vfio_bound": all(data["devices"][f]["driver"] == "vfio-pci" for f in data["functions"]),
            "high_root_window_sizes": [b - a + 1 for a, b in data["high_root_windows"]],
            "root_within_physical_address_limit": bool(data["physical_address_bits"]) and all(b < 2**data["physical_address_bits"] for _, b in data["high_root_windows"]),
            "single_matching_firmware_variable": data["variable_count"] == 1,
            "private_baseline_changes": comparison(data, baseline) if baseline else [],
            "firmware_offsets_automatically_approved": False,
            "note": "Read-only. New BIOS requires independent IFR review; addresses/identifiers omitted."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gpu")
    p.add_argument("--target-gib", type=int, default=32)
    p.add_argument("--baseline", type=Path)
    p.add_argument("--private-output", type=Path)
    a = p.parse_args()
    now = capture(a.gpu, a.target_gib)
    baseline = json.loads(a.baseline.read_text()) if a.baseline else None
    report = summary(now, baseline)
    if a.private_output:
        save_private(a.private_output, now)
    print(json.dumps(report, indent=2))
    return 2 if report["private_baseline_changes"] or not all(report[k] for k in ["aligned_root_space_available", "target_supported", "iommu_enabled", "vfio_bound", "root_within_physical_address_limit"]) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit("AUDIT STOP: " + str(error))
