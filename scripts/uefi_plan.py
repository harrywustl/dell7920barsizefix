#!/usr/bin/env python3
"""Generate guarded UEFI scripts/comparison files on USB; never write EFI variables."""
import argparse
import hashlib
import json
import re
import struct
import uuid
import zlib
from pathlib import Path
from rebar_audit import require
from usb_archive import volume


def saved_variable(name, guid, attributes, payload):
    encoded_name = (name + "\0").encode("utf-16le")
    data = struct.pack("<II", len(encoded_name), len(payload)) + encoded_name
    data += uuid.UUID(guid).bytes_le + struct.pack("<I", attributes) + payload
    return data + struct.pack("<I", zlib.crc32(data))


def scripts(name, guid, offset, width, original, target, base_offset, base_width, folder):
    stem = "\\" + folder.replace("/", "\\") + "\\"
    ref_before, ref_after = stem + "EXPECTED-BEFORE.bin", stem + "EXPECTED-AFTER.bin"
    def save(filename):
        return f"dmpstore {name} -guid {guid} -s {stem}{filename}\nif not %lasterror% == 0 then\n  goto STOP\nendif\n"
    def compare(left, right, fail="STOP"):
        return f"comp {left} {right}\nif not %lasterror% == 0 then\n  goto {fail}\nendif\n"
    def write(value, fail="STOP"):
        return f"setup_var.efi {name}:0x{offset:X}({width})=0x{value:X}\nif not %lasterror% == 0 then\n  goto {fail}\nendif\n"
    def header(title, guard):
        return f'@echo -off\nif not "%1" == "RUN" then\n  echo Usage: {title}.nsh RUN\n  goto END\nendif\nif exist {stem}{guard} then\n  echo STOP: evidence exists; do not overwrite or repeat blindly.\n  goto END\nendif\n'
    end = ":STOP\necho STOP: verification failed. Do not reboot. Report this screen.\n:END\n"
    check = f"@echo -off\ndmpstore {name} -guid {guid}\nsetup_var.efi {name}:0x{base_offset:X}({base_width})\nsetup_var.efi {name}:0x{offset:X}({width})\necho Read only. Match the reviewed plan before any write.\n"
    roundtrip = header("ROUNDTRIP", "ROUNDTRIP-BEFORE.bin")
    roundtrip += save("ROUNDTRIP-BEFORE.bin") + compare(stem + "ROUNDTRIP-BEFORE.bin", ref_before)
    roundtrip += write(target, "RESTORE")
    roundtrip += save("ROUNDTRIP-TARGET.bin").replace("goto STOP", "goto RESTORE")
    roundtrip += compare(stem + "ROUNDTRIP-TARGET.bin", ref_after, "RESTORE")
    roundtrip += f"echo VERIFIED > {stem}TARGET-VERIFIED.txt\n:RESTORE\n" + write(original)
    roundtrip += save("ROUNDTRIP-RESTORED.bin") + compare(stem + "ROUNDTRIP-RESTORED.bin", ref_before)
    roundtrip += f"if exist {stem}TARGET-VERIFIED.txt then\n  echo ROUNDTRIP_PASS: target and complete restoration verified.\nelse\n  echo TARGET_TEST_FAILED: original restored. Do not apply.\nendif\ngoto END\n" + end
    apply = header("APPLY", "APPLY-BEFORE.bin")
    apply += f"if not exist {stem}TARGET-VERIFIED.txt then\n  echo STOP: roundtrip was not verified.\n  goto END\nendif\n"
    apply += save("APPLY-BEFORE.bin") + compare(stem + "APPLY-BEFORE.bin", ref_before) + write(target)
    apply += save("APPLIED.bin") + compare(stem + "APPLIED.bin", ref_after)
    apply += "echo APPLY_PASS: complete variable matches expected target. No automatic reset.\ngoto END\n" + end
    rollback = header("ROLLBACK", "ROLLBACK-CURRENT.bin")
    rollback += save("ROLLBACK-CURRENT.bin") + compare(stem + "ROLLBACK-CURRENT.bin", ref_after) + write(original)
    rollback += save("ROLLED-BACK.bin") + compare(stem + "ROLLED-BACK.bin", ref_before)
    rollback += "echo ROLLBACK_PASS: complete original verified. No automatic reset.\ngoto END\n" + end
    return {"CHECK.nsh": check, "ROUNDTRIP.nsh": roundtrip, "APPLY.nsh": apply, "ROLLBACK.nsh": rollback}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--usb", type=Path, required=True)
    p.add_argument("--profile", type=Path, required=True)
    p.add_argument("--facts", type=Path, required=True)
    p.add_argument("--efivar", type=Path, required=True)
    p.add_argument("--folder", default="REBAR-PLAN")
    p.add_argument("--target-label", default="64G")
    a = p.parse_args()
    volume(a.usb)
    require(re.fullmatch(r"[A-Za-z0-9_-]+", a.folder), "Use a simple new USB folder name")
    profile = json.loads(a.profile.read_text())
    facts = json.loads(a.facts.read_text())
    require(profile["firmware_review"]["approved"] is True and facts.get("approved") is True, "Manual firmware review approval missing")
    require(Path("/sys/class/dmi/id/bios_version").read_text().strip() == profile["firmware_review"]["bios_version"] == profile["baseline"]["firmware"]["bios_version"], "Installed BIOS differs from reviewed version")
    require(profile["firmware_review"]["ifr_sha256"] == facts["text_sha256"] and facts.get("raw_checks"), "Missing matching independent raw IFR check")
    require(profile["baseline"]["variable_count"] == 1, "Firmware variable name is ambiguous")
    store = facts["stores"][0]
    require(len(facts["stores"]) == 1, "Ambiguous IFR VarStore")
    raw = a.efivar.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == profile["baseline"]["variable"]["sha256"], "Live variable differs from inspected baseline")
    require(len(raw) == store["size"] + 4 and int.from_bytes(raw[:4], "little") == store["attributes"], "Live variable size/attributes mismatch")
    require(a.efivar.name.lower() == "socketcommonrcconfig-" + store["guid"].lower(), "Live GUID mismatch")
    fields = {x["name"]: x for x in facts["fields"]}
    base, gran = fields["MMIO High Base"], fields["MMIO High Granularity Size"]
    require(base["store_id"] == gran["store_id"] == store["store_id"], "Fields use another VarStore")
    offset, width = gran["offset"], gran["width_bytes"]
    require(width in [1, 2, 4, 8] and offset + width <= store["size"], "Invalid reviewed offset/width")
    original = int.from_bytes(raw[4 + offset:4 + offset + width], "little")
    require(original in gran["options"].values(), "Original granularity is not a legal enum")
    target = gran["options"][a.target_label]
    require(original != target, "Already target; no firmware write plan is needed")
    payload = raw[4:]
    base_value = int.from_bytes(payload[base["offset"]:base["offset"] + base["width_bytes"]], "little")
    base_labels = [label for label, value in base["options"].items() if value == base_value]
    require(len(base_labels) == 1, "Ambiguous Base enum")
    def byte_label(label):
        match = re.fullmatch(r'(\d+)([TGM])', label)
        require(match is not None, "Unsupported IFR size label; review semantics manually")
        return int(match[1]) * 2**{"T": 40, "G": 30, "M": 20}[match[2]]
    multiplier = facts.get("mmio_total_multiplier")
    bits_match = re.search(r'address sizes\s*:\s*(\d+) bits physical', Path('/proc/cpuinfo').read_text())
    require(bits_match is not None and int(bits_match[1]) == profile["baseline"]["physical_address_bits"], "CPU address width changed or unknown")
    require(isinstance(multiplier, int) and multiplier > 0, "Cannot infer total MMIO limit from the reviewed help text")
    require(byte_label(base_labels[0]) + multiplier * byte_label(a.target_label) <= 2**int(bits_match[1]), "Planned MMIO range exceeds CPU physical address limit")
    candidate = bytearray(payload)
    candidate[offset:offset + width] = target.to_bytes(width, "little")
    folder = a.usb / a.folder
    require(not folder.exists(), "Plan exists; never overwrite previous evidence")
    folder.mkdir()
    for name, data in [("EXPECTED-BEFORE.bin", payload), ("EXPECTED-AFTER.bin", candidate)]:
        (folder / name).write_bytes(saved_variable("SocketCommonRcConfig", store["guid"], store["attributes"], data))
    for name, text in scripts("SocketCommonRcConfig", store["guid"], offset, width, original, target, base["offset"], base["width_bytes"], a.folder).items():
        (folder / name).write_bytes(text.replace("\n", "\r\n").encode("ascii"))
    plan = {"original": original, "target": target, "payload_offset": offset, "field_width": width,
            "efivarfs_offset": offset + 4, "changed_payload_bytes": [i for i, (x, y) in enumerate(zip(payload, candidate)) if x != y],
            "bios_version": profile["firmware_review"]["bios_version"], "no_automatic_reset": True}
    (folder / "plan.json").write_text(json.dumps(plan, indent=2))
    print("PLAN_GENERATED_ONLY; no EFI variable write. In Shell select this USB, then run its CHECK/ROUNDTRIP/APPLY scripts manually.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("PLAN STOP: " + str(error))
