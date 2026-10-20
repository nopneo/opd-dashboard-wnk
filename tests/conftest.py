"""ตั้งค่าร่วมของ test — ไม่ต่อฐานข้อมูลจริง (แทน fetch ด้วยตัวปลอม)"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
import deps  # noqa: E402

#: แผนกตัวอย่าง (รหัส → ชื่อ) ใช้แทน kskdepartment
DEPS = {"001": "ห้องบัตร เวชระเบียน", "010": "ห้องตรวจโรค 2", "011": "ห้องฉุกเฉิน ER",
        "020": "ห้องจ่ายยา", "030": "การเงิน", "040": "คลินิก NCD", "050": "ทันตกรรม"}


@pytest.fixture(autouse=True)
def fake_deps(monkeypatch):
    """เติมแคชแผนกไว้ก่อน deps จึงไม่ยิง DB"""
    monkeypatch.setitem(deps._cache, "t", time.time())
    monkeypatch.setitem(deps._cache, "deps", {
        c: {"name": n, "group": deps.classify(n)} for c, n in DEPS.items()})
    monkeypatch.setitem(deps._cache, "hosp", {"hospitalname": "โรงพยาบาลทดสอบ"})


@pytest.fixture
def fake_db(monkeypatch):
    """แทน fetch ทุกโมดูล: ประกอบ SQL ด้วย db._bind (จับ % ที่ไม่ได้ escape / พารามิเตอร์หาย)
    แล้วคืนผลว่าง · คืน list ของ (sql, args, sql ที่แทนค่าแล้ว) ให้ test ตรวจ"""
    import check
    import flow
    import queries

    calls = []

    def fetch(sql, args=None):
        calls.append((sql, args, db._bind(sql, args)))
        return []

    def fetch_one(sql, args=None):
        fetch(sql, args)
        return {}

    for mod in (queries, check):
        monkeypatch.setattr(mod, "fetch", fetch)
        monkeypatch.setattr(mod, "fetch_one", fetch_one)
    monkeypatch.setattr(flow, "fetch", fetch)
    monkeypatch.setattr(deps, "fetch", fetch)
    monkeypatch.setattr(queries, "CACHE_TTL", 0)
    flow._cache._data.clear()
    return calls
