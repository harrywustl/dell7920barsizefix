#!/usr/bin/env python3
"""Run inside a Linux AMD GPU guest; optional 4MiB HIP memory test, no configuration changes."""
import argparse
import ctypes as c
import ctypes.util
import json
import shutil
import subprocess
import time
from pathlib import Path
from rebar_audit import require, read, resources, resource_size


def hip_test():
    library = ctypes.util.find_library("amdhip64") or "/opt/rocm/lib/libamdhip64.so"
    h = c.CDLL(library)
    h.hipGetErrorString.restype = c.c_char_p
    h.hipMalloc.argtypes = [c.POINTER(c.c_void_p), c.c_size_t]
    h.hipMemset.argtypes = [c.c_void_p, c.c_int, c.c_size_t]
    h.hipMemcpy.argtypes = [c.c_void_p, c.c_void_p, c.c_size_t, c.c_int]
    h.hipFree.argtypes = [c.c_void_p]
    def check(name, *args):
        code = getattr(h, name)(*args)
        require(code == 0, name + " failed: " + (h.hipGetErrorString(code).decode() if code else ""))
    check("hipInit", 0)
    count = c.c_int()
    check("hipGetDeviceCount", c.byref(count))
    require(count.value == 1, "Select/review a single-GPU guest before this test")
    size = 4 * 2**20
    ptr = c.c_void_p()
    check("hipMalloc", c.byref(ptr), size)
    try:
        check("hipMemset", ptr, 0x5a, size)
        check("hipDeviceSynchronize")
        host = (c.c_ubyte * size)()
        check("hipMemcpy", host, ptr, size, 2)
        require(bytes(host) == b"\x5a" * size, "HIP memory readback mismatch")
    finally:
        check("hipFree", ptr)
    return size


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target-gib", type=int, default=32)
    p.add_argument("--wait-seconds", type=int, default=45)
    p.add_argument("--hip-test", action="store_true")
    a = p.parse_args()
    require(0 <= a.wait_seconds <= 120, "Use a bounded wait, at most 120 seconds")
    end = time.monotonic() + a.wait_seconds
    devices = []
    while True:
        devices = [d for d in Path("/sys/bus/pci/devices").iterdir()
                   if (d / "driver").exists() and (d / "driver").resolve().name == "amdgpu"
                   and (d / "mem_info_vis_vram_total").exists()]
        if devices or time.monotonic() >= end:
            break
        time.sleep(2)
    require(len(devices) == 1, "AMDGPU not ready or multiple AMD GPUs; investigate locally")
    dev = devices[0]
    bar = resource_size(resources(dev)[0])
    total = int(read(dev / "mem_info_vram_total", "0"))
    visible = int(read(dev / "mem_info_vis_vram_total", "0"))
    require(bar == a.target_gib * 2**30 and total > 0 and visible == total, "BAR/visible-VRAM check failed")
    require(Path("/dev/kfd").exists(), "KFD device missing")
    exe = shutil.which("rocminfo") or "/opt/rocm/bin/rocminfo"
    result = subprocess.run([exe], capture_output=True, text=True, timeout=25)
    require(result.returncode == 0 and "KERNEL_DISPATCH" in result.stdout, "ROCm GPU discovery failed")
    report = {"bar0_bytes": bar, "vram_total_bytes": total, "visible_vram_bytes": visible, "rocm_gpu_present": True}
    if a.hip_test:
        report["hip_verified_bytes"] = hip_test()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("GUEST CHECK STOP: " + str(error))
