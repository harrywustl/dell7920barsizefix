#!/usr/bin/env python3
"""Check public text and PNG metadata, with optional private denylist and image hashes."""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

SHARED_GUIDS = {"4402ca38-808f-4279-bcec-5baf8d59092f", "6b6fd380-2c55-42c6-98bf-cbbc5a9aa666", "a93d4a5b-9ea6-4b38-b118-bd11484e3f6a", "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"}
PATTERNS = {
    "IPv4": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "MAC": r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b",
    "BDF": r"\b[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]\b",
    "local_home": r"/(?:Users|home)/[A-Za-z0-9_.-]+",
    "private_key": r"-----BEGIN (?:OPENSSH|RSA|EC|DSA|PRIVATE).*KEY-----",
    "credential": r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,})\b",
    "SSH_key_material": r"\bssh-(?:ed25519|rsa)\s+[A-Za-z0-9+/=]{30,}",
}


def scan_text(text):
    findings = [name for name, pattern in PATTERNS.items()
                if re.search(pattern, re.sub(r'https?://[^\s<>\)]+', '', text) if name == "local_home" else text)]
    guids = re.findall(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b", text)
    if any(g.lower() not in SHARED_GUIDS for g in guids):
        findings.append("instance_UUID")
    return findings


def png_metadata(path):
    raw = path.read_bytes()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return ["invalid_PNG"]
    kinds, offset = [], 8
    while offset + 12 <= len(raw):
        size = struct.unpack_from(">I", raw, offset)[0]
        kind = raw[offset + 4:offset + 8]
        if kind in [b"tEXt", b"iTXt", b"zTXt", b"eXIf"]:
            kinds.append(kind.decode())
        offset += size + 12
    return kinds


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--denylist", type=Path, help="Private JSON list of additional literal strings")
    p.add_argument("--image-allowlist", type=Path, help="Private JSON map of reviewed image paths to SHA256")
    a = p.parse_args()
    allowed = json.loads(a.image_allowlist.read_text()) if a.image_allowlist else None
    deny = json.loads(a.denylist.read_text()) if a.denylist else []
    problems = []
    for path in a.root.rglob("*"):
        if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(a.root).as_posix()
        if path.suffix == ".png":
            expected = allowed.get(rel) if allowed is not None else None
            if (allowed is not None and expected != hashlib.sha256(path.read_bytes()).hexdigest()) or png_metadata(path):
                problems.append((rel, "unreviewed_image_or_metadata"))
            continue
        if path.suffix not in [".md", ".py", ".json", ".service", ".nsh", ".yml", ".yaml"] and path.name not in ["LICENSE", ".gitignore"]:
            problems.append((rel, "unexpected_file_type"))
            continue
        text = path.read_text()
        for finding in scan_text(text):
            problems.append((rel, finding))
        for secret in deny:
            if secret and secret.lower() in text.lower() and path.name != "LICENSE":
                problems.append((rel, "private_denylist_match"))
    for name, finding in problems:
        print(name, finding)
    if allowed is None:
        print("Visual image review required; no private image hash allowlist supplied.")
    print("PRIVACY_CHECK_PASS" if not problems else "PRIVACY_CHECK_FAILED", flush=True)
    return bool(problems)


if __name__ == "__main__":
    raise SystemExit(main())
