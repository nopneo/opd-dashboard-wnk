import time
from datetime import date

import pytest

import cache
import db
import deps
import flow
import stmap
from app import _parse_date


@pytest.mark.parametrize("raw, want", [
    ("2026-10-16", date(2026, 10, 16)),
    ("16/10/2569", date(2026, 10, 16)),       # พ.ศ.
    ("16/10/2026", date(2026, 10, 16)),
    ("16-10-2569", date(2026, 10, 16)),
    ("16/10/69", date(2026, 10, 16)),         # ปี 2 หลัก ≥ 60 = พ.ศ.
    ("16/10/26", date(2026, 10, 16)),         # ปี 2 หลัก < 60 = ค.ศ.
    ("  16/10/2569 ", date(2026, 10, 16)),
    ("", None), (None, None), ("abc", None), ("31/02/2569", None), ("2026-13-01", None),
    ("2026-10-16' or 1=1 --", None),
])
def test_parse_date(raw, want):
    assert _parse_date(raw) == want


def test_stmap_parse():
    out, err = stmap._parse("screen:service1, service11:SERVICE2,send:none,bad,doctor:x;drop")
    assert out == {"service4": "service1", "service11": "service2", "service3": "none"}
    assert err == ["bad", "doctor:x;drop"]


@pytest.mark.parametrize("name, group", [
    ("ห้องจ่ายยา", "RX"), ("ห้องตรวจโรค 3", "R3"), ("ห้องตรวจ 9", "R5"), ("ห้องฉุกเฉิน", "ER"),
    ("ER", "ER"), ("คลินิก NCD", "NCD"), ("การเงิน", "CASH"), ("ทันตกรรม", "DENT"),
    ("จุดซักประวัติ OPD", "SCR"), ("Telemedicine", "TELE"), ("อะไรก็ไม่รู้", None), (None, None),
])
def test_classify(name, group):
    assert deps.classify(name) == group


def test_bind_escapes_values():
    sql = db._bind("select 1 where a = %(a)s and b in %(b)s and t = '%%H'", {"a": "x' or '1'='1", "b": ["1", "2"]})
    assert sql == r"select 1 where a = 'x\' or \'1\'=\'1' and b in ('1','2') and t = '%H'"
    assert db._bind("select '%H'", None) == "select '%H'"


def test_ttl_cache_expiry_and_size(monkeypatch):
    c = cache.TTLCache(maxsize=2)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a", 60) == 1          # a ถูกใช้ล่าสุด → b เก่าสุด
    c.set("c", 3)
    assert c.get("b", 60) is None and c.get("a", 60) == 1 and c.get("c", 60) == 3
    now = time.time()
    monkeypatch.setattr(cache.time, "time", lambda: now + 100)
    assert c.get("a", 60) is None and len(c) == 1


def _visit(**kw):
    r = {k: None for k in flow.ORDER}
    r.update(md="010", home=None)
    r.update(kw)
    return r


def test_segments_normal_visit():
    segs, end = flow._segments(_visit(reg=480, s4=490, s11=500, s5=520, s12=530, s16=545))
    assert segs == [(480, "REG"), (490, "SCR"), (500, "DRW"), (520, "R2"), (530, "RX")]
    assert end == 545 + flow.WALK_OUT


def test_segments_er_registration_and_linger():
    segs, end = flow._segments(_visit(md="011", reg=600, s11=610))
    assert segs[0] == (600, "REGER")
    assert end == 610 + flow.LINGER[segs[-1][1]]


def test_segments_ignore_bad_times():
    # เวลาก่อนลงทะเบียน / เกินวัน ต้องถูกข้าม
    segs, _ = flow._segments(_visit(reg=480, s4=100, s5=480 + 10_000))
    assert segs == [(480, "REG")]


def test_segments_no_registration():
    assert flow._segments(_visit(reg=None)) == (None, None)


def test_segments_clinic_early_finish_stays_in_clinic():
    # ทันตกรรมกด "ตรวจเสร็จ" ตอนรับเข้าคิว → ยังอยู่ในคลินิกจนไปจ่ายเงิน แล้วออกตอนส่งกลับบ้าน
    segs, end = flow._segments(_visit(md="050", reg=458, s3=458, s12=460, s7=546, home=546))
    assert segs == [(458, "REG"), (458, "DENT"), (546, "CASH")]
    assert end == 546 + flow.WALK_OUT
    # ส่งกลับบ้านช้ากว่า HOME_MAX ของ OPD แต่ยังอยู่ในเกณฑ์ของคลินิก
    _, end = flow._segments(_visit(md="050", reg=458, s3=458, s12=460, home=640))
    assert end == 640


def test_segments_clinic_open_visit_today():
    # วันนี้ยังไม่ส่งกลับบ้าน (แผนกปัจจุบัน = ทันตกรรม) → ยังนั่งรอในคลินิก
    v = _visit(md="050", cd="050", reg=444, s3=444, s12=445)
    segs, end = flow._segments(v, now=510)
    assert segs[-1][1] == "DENT" and end == 510 + flow.OPEN_AHEAD
    assert flow._segments(v, now=900)[1] == 444 + flow.CLINIC_OPEN_MAX   # ลืมส่งกลับบ้าน
    assert flow._segments(v)[1] == 445 + flow.LINGER["DENT"]            # วันก่อน ๆ
    # OPD ทั่วไปไม่ยืดเวลา
    v = _visit(md="010", cd="010", reg=444, s11=450)
    assert flow._segments(v, now=600)[1] == 450 + flow.LINGER["DRW"]
