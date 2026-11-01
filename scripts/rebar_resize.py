#!/usr/bin/env python3
"""Default: check only. Execute only against a locally reviewed private profile."""
import argparse
import fcntl
import json
import os
import sys
from pathlib import Path
from rebar_audit import capture, comparison, require, resources, resource_size, summary


def vfio_holders():
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            comm = (proc / "comm").read_text().strip()
            if comm == "kvm" or comm.startswith("qemu-system"):
                return True
            fds = list((proc / "fd").iterdir())
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(fd).lower()
            except OSError:
                continue
            if "vfio" in target or "iommufd" in target:
                return True
    return False


def verify(now):
    r = now["devices"][now["gpu"]]["resources"]
    a, b, _ = r[0]
    target = now["target_bytes"]
    require(resource_size(r[0]) == target and a % target == 0, "BAR size/alignment is invalid")
    require(any(x <= a <= b <= y for x, y in now["high_root_windows"]), "BAR outside high root window")
    for bridge in now["bridges"]:
        require(any(x <= a and y >= b and flags & 0x200 for x, y, flags in now["devices"][bridge]["resources"][7:]), "Bridge does not cover BAR")


def validate(profile, now):
    require(profile.get("schema") == 1, "Unsupported private profile schema")
    baseline = profile["baseline"]
    require(not comparison(now, baseline), "Firmware/hardware/IOMMU changed; re-audit before enabling writes")
    review = profile.get("firmware_review", {})
    require(review.get("approved") is True, "No manually approved firmware review")
    require(review.get("bios_version") == now["firmware"]["bios_version"], "BIOS review version mismatch")
    require(len(review.get("ifr_sha256", "")) == 64 and len(review.get("firmware_sha256", "")) == 64, "Missing firmware evidence digests")
    require(now.get("variable") is not None and now["variable"]["sha256"] == profile.get("expected_variable_sha256"), "Live variable differs from approved state")
    require(now["target_bytes"] == baseline["target_bytes"], "Target changed")
    r = summary(now)
    require(r["target_supported"] and r["aligned_root_space_available"] and r["iommu_enabled"] and r["vfio_bound"] and r["root_within_physical_address_limit"], "Runtime prerequisite failed")
    allowed = set(now["bridges"] + now["functions"])
    require(set(now["branch"]) == allowed, "Other devices share the resize branch")
    for function in now["functions"]:
        require(now["devices"][function]["iommu_members"] == [function], "Function shares an IOMMU group")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--profile", required=True, type=Path)
    p.add_argument("--execute", action="store_true")
    a = p.parse_args()
    profile = json.loads(a.profile.read_text())
    baseline = profile["baseline"]
    gpu = baseline["gpu"]
    gib = baseline["target_bytes"] // 2**30
    now = capture(gpu, gib)
    validate(profile, now)
    if resource_size(now["devices"][gpu]["resources"][0]) == now["target_bytes"]:
        verify(now)
        print("ALREADY_TARGET_NO_CHANGE")
        return
    require(resource_size(now["devices"][gpu]["resources"][0]) == profile["initial_bar0_bytes"], "Unexpected starting BAR size")
    if not a.execute:
        print("CHECK_PASS_RESIZE_REQUIRED; no driver or resource write")
        return
    require(os.geteuid() == 0, "Root is required")
    with open("/run/lock/rebar-resize.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(not vfio_holders(), "QEMU/VFIO/iommufd in use")
        validate(profile, capture(gpu, gib))
        devs = Path("/sys/bus/pci/devices")
        original = now["devices"][gpu]["resources"]
        unbound = []
        errors = []
        try:
            functions = [f for f in now["functions"] if f != gpu] + [gpu]
            for bdf in functions:
                dev = devs / bdf
                (dev / "driver/unbind").write_text(bdf + "\n")
                unbound.append(bdf)
            (devs / gpu / "resource0_resize").write_text(str(now["target_exponent"]) + "\n")
            after = capture(gpu, gib)
            verify(after)
            for n, row in enumerate(original[:6]):
                if n != 0 and resource_size(row):
                    require(resource_size(after["devices"][gpu]["resources"][n]) == resource_size(row), "Another BAR changed size")
        except Exception as error:
            errors.append(str(error))
            try:
                n = profile["initial_bar0_bytes"].bit_length() - 1 - 20
                (devs / gpu / "resource0_resize").write_text(str(n) + "\n")
                require(resource_size(resources(devs / gpu)[0]) == profile["initial_bar0_bytes"], "Rollback readback failed")
            except Exception as rollback_error:
                errors.append("ROLLBACK FAILED: " + str(rollback_error))
        finally:
            for bdf in reversed(unbound):
                try:
                    if not (devs / bdf / "driver").exists():
                        Path("/sys/bus/pci/drivers/vfio-pci/bind").write_text(bdf + "\n")
                    require((devs / bdf / "driver").resolve().name == "vfio-pci", "VFIO rebind failed")
                except Exception as rebind_error:
                    errors.append("REBIND FAILED: " + str(rebind_error))
        require(not errors, "; ".join(errors))
        print("BAR_RESIZE_AND_VFIO_REBIND_PASS")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.exit("RESIZE STOP: " + str(error))
