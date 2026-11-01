#!/usr/bin/env python3
"""Read an IFRExtractor text export; emit facts, never firmware writes."""
import argparse
import hashlib
import json
import re
import struct
import uuid
from pathlib import Path


def parse(text):
    stores = []
    for match in re.finditer(r'VarStoreEfi Guid: ([0-9A-Fa-f-]+), VarStoreId: (0x[0-9A-Fa-f]+), Attributes: (0x[0-9A-Fa-f]+), Size: (0x[0-9A-Fa-f]+), Name: "SocketCommonRcConfig"', text):
        guid, store, attrs, size = match.groups()
        stores.append({"guid": guid.lower(), "store_id": int(store, 16), "attributes": int(attrs, 16), "size": int(size, 16)})
    fields = []
    for match in re.finditer(r'OneOf Prompt: "(MMIO High Base|MMIO High Granularity Size|Isoc Mode)"(.*?)(?=\n\s*End)', text, re.S):
        name, body = match.groups()
        values = {}
        for label, value in re.findall(r'OneOfOption Option: "([^"]+)" Value: (0x[0-9A-Fa-f]+|\d+)', body):
            values[label] = int(value, 0)
        offset = re.search(r'VarOffset: (0x[0-9A-Fa-f]+)', body)
        size = re.search(r'Size: (\d+)', body)
        store = re.search(r'VarStoreId: (0x[0-9A-Fa-f]+)', body)
        if offset and size and store:
            qid = re.search(r'QuestionId: (0x[0-9A-Fa-f]+)', body)
            fields.append({"name": name, "question_id": int(qid[1], 16) if qid else None, "offset": int(offset[1], 16), "width_bytes": int(size[1]) // 8,
                           "store_id": int(store[1], 16), "options": values})
    multipliers = set(int(n) for n in re.findall(r'Total mmioh space can be up to (\d+)xgranularity', text, re.I))
    return {"stores": stores, "fields": fields, "mmio_total_multiplier": next(iter(multipliers)) if len(multipliers) == 1 else None}


def check_raw(data, facts):
    checks = []
    for store in facts["stores"]:
        hits = []
        for i in range(len(data) - 26):
            if data[i] != 0x26:
                continue
            length = data[i + 1] & 0x7f
            if length < 27 or i + length > len(data):
                continue
            if data[i + 26:i + length].split(b"\0")[0] != b"SocketCommonRcConfig":
                continue
            sid = struct.unpack_from("<H", data, i + 2)[0]
            guid = str(uuid.UUID(bytes_le=data[i + 4:i + 20]))
            attrs, size = struct.unpack_from("<IH", data, i + 20)
            if (sid, guid, attrs, size) == (store["store_id"], store["guid"], store["attributes"], store["size"]):
                hits.append(i)
        if len(hits) != 1:
            raise ValueError("Raw EFI VarStore does not uniquely match text")
        checks.append({"kind": "VarStoreEfi", "pe32_offset": hits[0]})
    for field in facts["fields"]:
        hits = []
        for i in range(len(data) - 14):
            if data[i] != 0x05 or not data[i + 1] & 0x80:
                continue
            length = data[i + 1] & 0x7f
            qid, sid, offset = struct.unpack_from("<HHH", data, i + 6)
            width = 1 << (data[i + 13] & 3)
            if (qid, sid, offset, width) != (field["question_id"], field["store_id"], field["offset"], field["width_bytes"]):
                continue
            if length != 14 + 3 * width:
                continue
            j, depth, options = i + length, 1, []
            while j + 2 <= len(data) and depth:
                op, flags = data[j:j + 2]
                n = flags & 0x7f
                if n < 2 or j + n > len(data):
                    break
                if op == 0x09 and depth == 1 and n == 6 + width:
                    options.append(int.from_bytes(data[j + 6:j + n], "little"))
                if op == 0x29:
                    depth -= 1
                elif flags & 0x80:
                    depth += 1
                j += n
            if depth == 0 and sorted(options) == sorted(field["options"].values()):
                hits.append(i)
        if len(hits) != 1:
            raise ValueError("Raw OneOf width/offset/options do not uniquely match text: " + field["name"])
        checks.append({"kind": field["name"], "pe32_offset": hits[0]})
    return checks


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ifr", type=Path)
    p.add_argument("--pe32", type=Path, help="Independent raw-opcode cross-check of the same extracted PE32")
    a = p.parse_args()
    raw = a.ifr.read_bytes()
    result = parse(raw.decode(errors="strict"))
    result["text_sha256"] = hashlib.sha256(raw).hexdigest()
    if a.pe32:
        binary = a.pe32.read_bytes()
        result["raw_checks"] = check_raw(binary, result)
        result["pe32_sha256"] = hashlib.sha256(binary).hexdigest()
    result["approved"] = False
    result["required_manual_checks"] = ["Exact installed BIOS and official firmware match", "PE32/raw IFR opcode widths agree", "Live variable GUID/attributes/size match", "Base plus worst-case MMIO range fits physical-address limit", "Review every changed field; do not import another machine's blob"]
    print(json.dumps(result, indent=2))
    if len(result["stores"]) != 1 or len(result["fields"]) < 2:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
