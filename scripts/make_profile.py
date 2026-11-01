#!/usr/bin/env python3
"""Bind a reviewed IFR/official firmware pair to a private live-machine snapshot."""
import argparse
import json
import re
from pathlib import Path
from rebar_audit import require, save_private
from usb_archive import digest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--facts", type=Path, required=True)
    p.add_argument("--firmware", type=Path, required=True)
    p.add_argument("--official-sha256", required=True)
    p.add_argument("--confirm-reviewed-version", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--approved-facts-output", type=Path, required=True)
    p.add_argument("--initial-bar0-mib", type=int, default=256)
    a = p.parse_args()
    baseline, facts = json.loads(a.baseline.read_text()), json.loads(a.facts.read_text())
    require(a.confirm_reviewed_version == baseline["firmware"]["bios_version"], "BIOS version confirmation differs")
    require(re.fullmatch(r"[0-9a-fA-F]{64}", a.official_sha256), "Invalid official SHA256")
    require(digest(a.firmware) == a.official_sha256.lower(), "Official firmware digest does not match")
    require(facts.get("raw_checks") and len(facts.get("stores", [])) == 1, "Independent raw IFR checks missing")
    var = baseline.get("variable")
    store = facts["stores"][0]
    require(var and baseline["variable_count"] == 1 and var["filename"].lower() == "socketcommonrcconfig-" + store["guid"], "Live variable GUID mismatch/ambiguity")
    require(var["data_size"] == store["size"] and var["attributes"] == store["attributes"], "Live VarStore shape differs")
    initial = a.initial_bar0_mib * 2**20
    require(initial > 0 and initial & (initial - 1) == 0 and initial <= baseline["target_bytes"], "Invalid initial BAR size")
    profile = {"schema": 1, "baseline": baseline, "initial_bar0_bytes": initial,
               "expected_variable_sha256": var["sha256"],
               "firmware_review": {"approved": True, "bios_version": a.confirm_reviewed_version,
                                   "firmware_sha256": a.official_sha256.lower(), "ifr_sha256": facts["text_sha256"]}}
    require(not a.output.exists() and not a.approved_facts_output.exists(), "Never overwrite old approvals")
    facts["approved"] = True
    save_private(a.output, profile)
    save_private(a.approved_facts_output, facts)
    print("PRIVATE_PROFILE_CREATED; explicit review confirmation recorded, no firmware or PCI writes")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("PROFILE STOP: " + str(error))
