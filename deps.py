"""ข้อมูลโรงพยาบาลและการจัดกลุ่มแผนก — อ่านจาก HOSxP ของแต่ละโรงพยาบาลเอง

รหัสแผนก (kskdepartment.depcode) แต่ละโรงพยาบาลตั้งไม่เหมือนกัน จึงจัดกลุ่มจาก "ชื่อแผนก"
แทนการผูกรหัสตายตัว แล้วให้แก้ทับได้ด้วย env `OPD_DEP_MAP` เช่น `011=ER,040=TELE`
"""

import os
import re
import time

from db import fetch

#: (กลุ่ม, รูปแบบชื่อแผนก) — ตรวจตามลำดับ ตัวแรกที่ตรงชนะ (ตัวพิมพ์เล็ก/ใหญ่ไม่มีผล)
RULES = [
    ("ADMIN", r"เวชระเบียน"),
    ("RX", r"จ่ายยา|เภสัช|^ห้องยา"),
    ("CASH", r"เก็บเงิน|การเงิน|ชำระเงิน"),
    ("TELE", r"telemed|โทรเวช"),
    ("ARI", r"\bari\b"),
    ("ER", r"\ber\b|ฉุกเฉิน|อุบัติเหตุ"),
    ("DENT", r"ทันต"),
    ("TTM", r"แผนไทย"),
    ("PT", r"กายภาพ"),
    ("MH", r"จิตเวช|สุขภาพจิต"),
    ("SPEC", r"ปฐมภูมิ|เวชศาสตร์ครอบครัว|เวชปฏิบัติครอบครัว"),
    ("LAB", r"\blab\b|ชันสูตร|เทคนิคการแพทย์"),
    ("NCD", r"\bncd\b|เบาหวาน|ความดัน|โรคเรื้อรัง"),
    ("ROOM", r"ห้องตรวจ(?:โรค)?\s*(\d+)"),
    ("SCR", r"ซักประวัติ|คัดกรอง|หน้าห้องตรวจ"),
]
_RX = [(g, re.compile(p, re.I)) for g, p in RULES]

_TTL = 3600
_cache = {"t": 0, "deps": {}, "hosp": None}


def classify(name):
    """ชื่อแผนก → กลุ่ม (None = ไม่เข้ากลุ่มใด)"""
    name = (name or "").strip()
    for group, rx in _RX:
        m = rx.search(name)
        if not m:
            continue
        if group == "ROOM":
            n = int(m.group(1))
            return f"R{min(max(n, 1), 5)}"     # ผังมีห้องตรวจ 1-5 ห้องเลขสูงกว่ารวมไว้ห้อง 5
        return group
    return None


def _overrides():
    out = {}
    for pair in os.getenv("OPD_DEP_MAP", "").split(","):
        if "=" in pair:
            code, group = pair.split("=", 1)
            out[code.strip()] = group.strip().upper()
    return out


def _load():
    if _cache["t"] and time.time() - _cache["t"] < _TTL:     # โหลดแล้ว (แม้ไม่มีแผนกเลย)
        return
    rows = fetch("select depcode, department from kskdepartment")
    deps = {r["depcode"]: {"name": r["department"] or "", "group": classify(r["department"])}
            for r in rows}
    for code, group in _overrides().items():
        deps.setdefault(code, {"name": code})["group"] = group
    try:
        h = fetch("select hospitalcode, hospitalname from opdconfig limit 1")
        hosp = h[0] if h else None
    except Exception:           # บางรุ่นไม่มีตาราง opdconfig
        hosp = None
    _cache.update(t=time.time(), deps=deps, hosp=hosp)


def group_of(depcode):
    _load()
    return (_cache["deps"].get(depcode or "") or {}).get("group")


def name_of(depcode):
    _load()
    return (_cache["deps"].get(depcode or "") or {}).get("name") or (depcode or "")


def codes_in(group):
    _load()
    return sorted(c for c, d in _cache["deps"].items() if d.get("group") == group)


def hospital_name():
    """ชื่อโรงพยาบาล: env OPD_HOSPITAL_NAME > opdconfig.hospitalname ของ HOSxP"""
    env = os.getenv("OPD_HOSPITAL_NAME")
    if env:
        return env
    try:
        _load()
    except Exception:
        return "โรงพยาบาล"
    h = _cache["hosp"] or {}
    return h.get("hospitalname") or "โรงพยาบาล"
