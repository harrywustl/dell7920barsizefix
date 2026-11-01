import hashlib
import io
import json
import struct
import sys
import tempfile
import unittest
import uuid
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ifr_review import parse, check_raw
from privacy_check import scan_text
from rebar_audit import comparison, require, resource_size
from rebar_resize import validate
from uefi_plan import saved_variable, scripts
from usb_archive import PartsReader, PartsWriter, safe_name, inspect_archive, verify, extract, create


class SafetyTests(unittest.TestCase):
    def test_require_survives_optimized_python(self):
        with self.assertRaises(RuntimeError):
            require(False, "Stop")

    def test_firmware_change_is_detected(self):
        baseline = {"firmware": {"bios_version": "old"}, "devices": {}}
        current = {"firmware": {"bios_version": "new"}, "devices": {}}
        self.assertIn("firmware", comparison(current, baseline))

    def test_unapproved_profile_cannot_reach_sysfs(self):
        baseline = {"devices": {}}
        with self.assertRaisesRegex(RuntimeError, "approved"):
            validate({"schema": 1, "baseline": baseline, "firmware_review": {"approved": False}}, baseline)

    def test_saved_variable_format_and_one_byte_change(self):
        guid = str(uuid.UUID(int=1))
        before = saved_variable("SocketCommonRcConfig", guid, 7, bytes(114))
        data = bytearray(114)
        data[4] = 3
        after = saved_variable("SocketCommonRcConfig", guid, 7, data)
        self.assertEqual(len(before), 188)
        self.assertEqual(struct.unpack_from("<II", before), (42, 114))
        self.assertEqual(struct.unpack("<I", before[-4:])[0], zlib.crc32(before[:-4]))
        self.assertEqual([i for i in range(184) if before[i] != after[i]], [74])

    def test_guarded_shell_has_no_automatic_reset(self):
        plans = scripts("Variable", str(uuid.UUID(int=1)), 4, 2, 0, 3, 0, 4, "PLAN")
        for name in ["ROUNDTRIP.nsh", "APPLY.nsh", "ROLLBACK.nsh"]:
            self.assertIn('"%1" == "RUN"', plans[name])
            self.assertIn("if exist", plans[name])
            self.assertIn("comp ", plans[name])
            self.assertNotIn("\nreset", plans[name].lower())
        self.assertIn(":RESTORE", plans["ROUNDTRIP.nsh"])

    def test_split_zip_boundaries_and_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = bytes(range(256)) * 21
            h = hashlib.sha256(payload).hexdigest()
            manifest = {"files": [{"path": "EFI/BOOT/BOOTX64.EFI", "bytes": len(payload), "sha256": h}]}
            writer = PartsWriter(root, 333)
            with zipfile.ZipFile(writer, "w", allowZip64=True) as z:
                with z.open("EFI/BOOT/BOOTX64.EFI", "w", force_zip64=True) as f:
                    f.write(payload)
                z.writestr("ARCHIVE-MANIFEST.json", json.dumps(manifest))
            writer.close()
            receipt = {"format": "concatenated-zip64-v1", "parts": writer.parts, "source_bytes": len(payload), "source_volume": {"uuid": "OLD_TEST_VOLUME"}}
            (root / "parts.json").write_text(json.dumps(receipt))
            self.assertTrue(all(p["bytes"] <= 333 for p in writer.parts))
            verify(root)
            stream = PartsReader(root, writer.parts)
            with zipfile.ZipFile(stream) as z:
                self.assertEqual(z.read("EFI/BOOT/BOOTX64.EFI"), payload)
            dest = root / "destination"
            dest.mkdir()
            with patch("usb_archive.volume", return_value={"uuid": "NEW_TEST_VOLUME"}):
                extract(root, dest, "NEW_TEST_VOLUME")
                self.assertEqual((dest / "EFI/BOOT/BOOTX64.EFI").read_bytes(), payload)
                self.assertEqual(json.loads((dest / "MIGRATION.json").read_text())["destination_volume"]["uuid"], "NEW_TEST_VOLUME")
                with self.assertRaisesRegex(RuntimeError, "empty"):
                    extract(root, dest, "NEW_TEST_VOLUME")
            p = root / writer.parts[0]["file"]
            p.write_bytes(b"x" + p.read_bytes()[1:])
            with self.assertRaisesRegex(RuntimeError, "hash"):
                verify(root)

    def test_archive_path_traversal_and_fat_collisions(self):
        for name in ["../escape", "/absolute", "a\\b", "a:b"]:
            with self.assertRaises(RuntimeError):
                safe_name(name)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("File", "one")
            z.writestr("file", "two")
        out.seek(0)
        with zipfile.ZipFile(out) as z, self.assertRaisesRegex(RuntimeError, "colliding"):
            inspect_archive(z)

    def test_functional_single_zip_excludes_unselected_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "EFI/BOOT").mkdir(parents=True)
            (root / "EFI/BOOT/BOOTX64.EFI").write_bytes(b"test-loader")
            (root / "restore-backup.gz").write_bytes(b"test-backup")
            (root / "screenshot.png").write_bytes(b"must-not-be-archived")
            selection = root / "selection.json"
            selection.write_text(json.dumps(["EFI/BOOT/BOOTX64.EFI", "restore-backup.gz"]))
            out = root / "ARCHIVES/copy"
            with patch("usb_archive.volume", return_value={"uuid": "TEST_VOLUME"}):
                create(root, out, 2**31, selection, True)
            with zipfile.ZipFile(out / "recovery-usb.zip") as z:
                self.assertEqual(set(z.namelist()), {"EFI/BOOT/BOOTX64.EFI", "restore-backup.gz", "ARCHIVE-MANIFEST.json"})
                self.assertEqual(z.read("restore-backup.gz"), b"test-backup")

    def test_privacy_patterns(self):
        address = ".".join(["10", "20", "30", "40"])
        self.assertIn("IPv4", scan_text(address))
        self.assertIn("instance_UUID", scan_text(str(uuid.UUID(int=2))))
        self.assertFalse(scan_text("BIOS 2.52.2; 32GiB BAR; no host identifiers"))

    def test_resource_zero_is_not_a_byte(self):
        self.assertEqual(resource_size([0, 0, 0]), 0)
        self.assertEqual(resource_size([2**35, 2**36 - 1, 0]), 2**35)

    def test_ifr_field_width_is_bits_to_bytes(self):
        text = 'OneOf Prompt: "MMIO High Granularity Size", QuestionId: 0xA, VarStoreId: 0x2, VarOffset: 0x4, Size: 16\nOneOfOption Option: "64G" Value: 3\nEnd'
        facts = parse(text)
        self.assertEqual(facts["fields"][0]["width_bytes"], 2)
        self.assertEqual(facts["fields"][0]["options"]["64G"], 3)


if __name__ == "__main__":
    unittest.main()
