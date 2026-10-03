# ============================================================
# test_validate.py — 快照 schema 校验测试（合法/非法/走廊键完整性）
# ============================================================
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import unittest

from corridors import CORRIDOR_IDS
from validate import validate_snapshot


def valid_snapshot() -> dict:
    base = {"fr03": "段基准", "fr15": "平", "ct04": 1, "ct05": "常规", "ct06": "正常"}
    return {
        "date": "2026-10-03",
        "generated_at": "2026-10-03T09:00:00+08:00",
        "pipeline_version": "1.0",
        "corridors": {cid: dict(base) for cid in CORRIDOR_IDS},
        "evidence": {},
    }


class TestValidate(unittest.TestCase):
    def test_valid(self):
        validate_snapshot(valid_snapshot())  # 不抛即过

    def test_missing_corridor(self):
        snap = valid_snapshot()
        del snap["corridors"]["H"]
        with self.assertRaises(ValueError):
            validate_snapshot(snap)

    def test_bad_enum(self):
        snap = valid_snapshot()
        snap["corridors"]["A"]["fr15"] = "大暴雨"
        with self.assertRaises(ValueError):
            validate_snapshot(snap)
        snap = valid_snapshot()
        snap["corridors"]["B"]["ct04"] = 4
        with self.assertRaises(ValueError):
            validate_snapshot(snap)
        snap = valid_snapshot()
        snap["corridors"]["C"]["ct05"] = "正常 "  # 带空格=非法（防手滑）
        with self.assertRaises(ValueError):
            validate_snapshot(snap)

    def test_bad_date(self):
        snap = valid_snapshot()
        snap["date"] = "20261003"
        with self.assertRaises(ValueError):
            validate_snapshot(snap)

    def test_missing_top_key(self):
        snap = valid_snapshot()
        del snap["generated_at"]
        with self.assertRaises(ValueError):
            validate_snapshot(snap)


if __name__ == "__main__":
    unittest.main()
