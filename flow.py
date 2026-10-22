"""ข้อมูลหน้า "ผังผู้ป่วย OPD" (2.5D live / replay)

แปลงเวลาแต่ละขั้นใน `service_time` + `lab_head` ของแต่ละ visit เป็นเส้นทาง
"ช่วงเวลาไหน อยู่จุดบริการไหน" ให้หน้าเว็บขยับหุ่นผู้ป่วยตามเวลา

ส่งออกเฉพาะเวลา (นาทีนับจากเที่ยงคืน) รหัสจุดบริการ เพศ และระดับความเร่งด่วน — ไม่มี vn / HN / ชื่อ / อายุ
แต่ละ visit มีแค่รหัสสุ่ม (hash ของ vn ผสมเกลือลับ) ไว้ให้หน้าเว็บจำหุ่นตัวเดิมได้ตอนรีเฟรช
และเรียงตามรหัสนั้น จึงโยงกลับไปหาลำดับ vn ไม่ได้

ตำแหน่งจริงของผู้ป่วยไม่มีในระบบ จึงอนุมานจากขั้นล่าสุดที่บันทึกเวลาแล้ว
เช่น กด "ส่งพบแพทย์" (service11) แล้วยังไม่กด "เริ่มตรวจ" = นั่งรอหน้าห้องตรวจ
"""

import hashlib
import os
import time
from datetime import date

import deps
import stmap
from cache import TTLCache
from db import fetch, num
from db import tenant as db_tenant
from queries import MAX_TOTAL, _thai_date

# ------------------------------------------------------------ จุดบริการ
#
# (รหัส, ชื่อที่แสดง, เป้าหมายนาที) — เป้าหมายใช้ระบายสีหุ่น/ป้าย: เขียว ≤ เป้า,
# ส้ม เกินเล็กน้อย, แดง ≥ 1.5 เท่า (เกณฑ์เดียวกับหน้าแดชบอร์ด)
AREAS = [
    ("REG", "ห้องบัตร / ลงทะเบียน", 10),
    ("REGER", "ห้องบัตรหน้า ER", 10),
    ("SCR", "จุดซักประวัติ OPD", 30),
    ("NCD", "คลินิก NCD", 30),
    ("LAB", "รอเจาะเลือด", 15),
    ("LABW", "รอผลแล็บ", 60),
    ("DRW", "หน้าห้องตรวจ", 20),
    ("R1", "ห้องตรวจ 1", 15),
    ("R2", "ห้องตรวจ 2", 15),
    ("R3", "ห้องตรวจ 3", 15),
    ("R4", "ห้องตรวจ 4", 15),
    ("R5", "ห้องตรวจ 5", 15),
    ("TELE", "ห้อง Telemed", 30),
    ("ARI", "คลินิก ARI", 45),
    ("ER", "ห้องฉุกเฉิน", 60),
    ("DENT", "ทันตกรรม", 60),
    ("SPEC", "ปฐมภูมิ", 60),
    ("MH", "สุขภาพจิต", 60),
    ("PT", "กายภาพบำบัด", 60),
    ("TTM", "แพทย์แผนไทย", 60),
    ("RX", "รอรับยา", 20),
    ("CASH", "การเงิน", 10),
]
AREA_IDX = {a[0]: i for i, a in enumerate(AREAS)}

#: จุดบริการของแต่ละแผนกมาจากชื่อแผนกใน kskdepartment (deps.classify) — ใช้ได้ทุกโรงพยาบาล
#: แก้ทับรายรหัสได้ด้วย env OPD_DEP_MAP เช่น `011=ER,040=TELE`
ROOMS = {"R1", "R2", "R3", "R4", "R5"}


def _remote_deps():
    """แผนกที่ผู้ป่วยไม่ได้อยู่ใน รพ. — ค่าเริ่มต้น = แผนก Telemed (แพทย์ตรวจทางไกล
    ผู้ป่วยอยู่ รพ.สต./บ้าน) จึงไม่วาดในผัง นับแยกไว้ · env OPD_FLOW_REMOTE_DEPS=none = วาดทุกคน"""
    env = os.getenv("OPD_FLOW_REMOTE_DEPS")
    if env is not None:
        return set() if env.strip().lower() in ("", "none") else {c.strip() for c in env.split(",")}
    return set(deps.codes_in("TELE"))


#: ขั้นสุดท้ายที่บันทึกไว้ไม่ใช่ "จบ" (เช่น กดส่งพบแพทย์แล้วไม่มีเวลาอื่นอีก)
#: ให้อยู่ที่จุดนั้นต่อได้นานสุดกี่นาที — ไม่งั้นหุ่นค้างทั้งวันจากการลืมกดเวลา
LINGER = {"REG": 15, "REGER": 15, "SCR": 60, "NCD": 60, "ARI": 60, "LAB": 30, "LABW": 60,
          "DRW": 120, "R1": 20, "R2": 20, "R3": 20, "R4": 20, "R5": 20, "TELE": 60, "ER": 180,
          "DENT": 60, "SPEC": 60, "MH": 60, "PT": 60, "TTM": 60, "RX": 60, "CASH": 15}
#: เวลาเดินออกจากโรงพยาบาลหลังขั้นสุดท้าย (นาที)
WALK_OUT = 2

#: ลำดับเมื่อเวลาเท่ากัน (บันทึกเป็นนาที/วินาทีเดียวกันบ่อย)
ORDER = ["reg", "s3", "er_in", "s4", "lo", "lr", "s11", "s5", "er_out", "s12", "s6", "s7", "s16", "s20"]

#: อยู่ห้องฉุกเฉินกี่นาทีนับจาก er_regist.enter_er_time (เคสสังเกตอาการ observe = 'Y' นานกว่า)
#: HOSxP ไม่มีเวลาออกจาก ER ที่ใช้ได้ (finish_time = เข้า + 10 นาทีเสมอ, leave_datetime ว่าง)
ER_STAY, ER_OBSERVE = 20, 180
#: ส่งกลับบ้าน (ovst.cur_dep = 999) หลังกิจกรรมสุดท้ายไม่เกินกี่นาที จึงถือเป็นเวลาออกจริง
#: เกินนี้ = กดเป็นชุดตอนเย็น ไม่ใช่เวลาที่ผู้ป่วยออกจริง
HOME_MAX = 120
#: มีส่งกลับบ้านแล้วแต่ขั้นสุดท้ายยังค้าง (เช่น รับใบสั่งยาแล้วไม่ได้กดจ่ายเสร็จ) ให้อยู่ต่อได้ไม่เกินนี้
HOME_LINGER = 30

#: คลินิกที่ตรวจ/ทำหัตถการในคลินิกเอง — มักกด "ตรวจเสร็จ" (service12) ตั้งแต่รับผู้ป่วยเข้าคิว
#: (ทันตกรรม รพ.วังน้ำเขียว 77% กดภายใน 10 นาทีหลังลงทะเบียน แล้วผู้ป่วยรอทำฟันอีก ~1.5 ชม.)
#: จึงให้อยู่ในคลินิกต่อจนถึงขั้นถัดไป/ส่งกลับบ้าน แทนที่จะถือว่าออกไปแล้ว
CLINICS = {"DENT", "SPEC", "MH", "PT", "TTM"}
#: ส่งกลับบ้านหลังขั้นสุดท้ายในคลินิกไม่เกินกี่นาที จึงถือเป็นเวลาออกจริง (90% ของทันตกรรม ≤ 186 นาที)
CLINIC_HOME_MAX = 240
#: วันนี้: แผนกปัจจุบัน (ovst.cur_dep) ยังเป็นคลินิกนั้น = ยังไม่ส่งกลับบ้าน ให้อยู่ต่อ
#: นานสุดกี่นาทีนับจากลงทะเบียน (กันลืมกดส่งกลับบ้านแล้วค้างทั้งวัน)
CLINIC_OPEN_MAX = 300
#: ยืดเวลาออกเผื่อไว้กี่นาทีหลังเวลาปัจจุบัน (หน้าเว็บโหลดข้อมูลใหม่ทุก ~1 นาที)
OPEN_AHEAD = 5


#: ระดับความเร่งด่วน (สีเสื้อหุ่น) — ER ใช้ระดับคัดแยก er_regist.er_emergency_level_id
#: ส่วน OPD ใช้ ovst.pt_priority (0 ปกติ, 1 นัด, 2 พระภิกษุ/ผู้พิการ, 3 ผู้สูงอายุ, 4 ฉุกเฉิน)
#:   1 วิกฤต · 2 ฉุกเฉิน · 3 เร่งด่วน · 4 กึ่งเร่งด่วน · 5 ไม่เร่งด่วน/ทั่วไป · 6 ช่องทางพิเศษ OPD
def _urgency(er_level, priority):
    lv = str(er_level or "")
    if lv in ("1", "2", "3", "4"):
        return int(lv)
    pr = str(priority or "")
    if pr == "4":
        return 2
    if pr in ("2", "3"):
        return 6
    return 5


def _unit(dep, default):
    g = deps.group_of(dep)
    return g if g in AREA_IDX else default


def _wait_area(exam_unit):
    """ส่งพบแพทย์แล้วไปนั่งรอที่ไหน"""
    if exam_unit in ROOMS or exam_unit in ("SCR", "NCD"):
        return "DRW"
    return exam_unit


def _segments(r, now=None):
    """แถว 1 visit → [(นาทีที่เข้า, จุดบริการ), ...], นาทีที่ออกจาก รพ.
    now = นาทีปัจจุบัน (เฉพาะข้อมูลวันนี้) ใช้คงผู้ป่วยคลินิกที่ยังไม่ส่งกลับบ้าน"""
    reg = r["reg"]
    if reg is None:
        return None, None
    md = r.get("md")
    scr_unit = _unit(r.get("d4") or md, "SCR")
    exam_dep = r.get("d5") or r.get("d12") or md
    exam_unit = _unit(exam_dep, "DRW")
    if exam_unit in ("RX", "CASH", "LAB"):
        exam_unit = "DRW"
    if scr_unit in ROOMS or scr_unit in ("RX", "CASH", "LAB"):
        scr_unit = "SCR"

    area = {
        # ผู้ป่วยฉุกเฉิน (แผนกหลัก = ER) ลงทะเบียนที่ห้องบัตรหน้า ER
        "reg": "REGER" if deps.group_of(md) == "ER" else "REG", "s3": scr_unit, "s4": scr_unit,
        "lo": "LAB", "lr": "LABW",
        "s11": _wait_area(exam_unit),
        # ไม่รู้ว่าห้องไหน (ไม่มีรหัสแผนกห้องตรวจ) → ใส่ห้องตรวจ 2 ไว้ก่อน
        "s5": "R2" if exam_unit in ("DRW", "SCR", "NCD") else exam_unit,
        "s12": None, "s6": "RX",
        "s7": _unit(r.get("d7"), "CASH"),
        "s16": None, "s20": None,
        "er_in": "ER", "er_out": None,      # ห้องฉุกเฉินเป็นจุดแวะชั่วคราว แล้วไปขั้นถัดไป/กลับบ้าน
    }

    ev = []
    for k in ORDER:
        t = r.get(k)
        if t is None:
            continue
        if k in ("s3", "s20") and deps.group_of(r.get("d" + k[1:])) == "ADMIN":
            continue            # เวชระเบียนส่งต่อ/ปิด visit ย้อนหลัง — ไม่ใช่ที่อยู่ของผู้ป่วย
        if k != "reg" and not (reg <= t <= reg + MAX_TOTAL):
            continue            # กดเวลาผิดวัน/ก่อนลงทะเบียน
        ev.append((t, ORDER.index(k), k))
    ev.sort()

    # Lab ที่รับ/สั่งหลังขั้นบริการสุดท้าย = ผู้ป่วยกลับไปแล้ว (เช่น ส่งตรวจต่อภายหลัง)
    last_srv = max((t for t, _, k in ev if k not in ("reg", "lo", "lr")), default=None)
    if last_srv is not None:
        ev = [e for e in ev if e[2] not in ("lo", "lr") or e[0] <= last_srv]

    # ตรวจเสร็จ (service12) → ไปรอที่ห้องยาถ้ามีขั้นยาตามมา (ส่วนใหญ่ไม่ได้กด service6
    # มีแต่ service16) ไม่งั้นไปการเงิน ไม่งั้นกลับบ้าน — ไม่ให้นั่งค้างในห้องตรวจ
    t12 = r.get("s12")
    if t12 is not None:
        later = {k for t, _, k in ev if t >= t12}
        area["s12"] = ("RX" if later & {"s6", "s16"} else
                       exam_unit if exam_unit in CLINICS else    # รอในคลินิกจนไปจ่ายเงิน/กลับบ้าน
                       area["s7"] if "s7" in later else None)

    segs = []
    for i, (t, _, k) in enumerate(ev):
        a = area[k]
        if a is None:           # ขั้นที่ "ส่งต่อ" — ไปจุดของขั้นถัดไป
            continue
        if segs and segs[-1][1] == a:
            continue
        segs.append((t, a))

    last_t, _, last_k = ev[-1]
    if area[last_k] is None:
        end = last_t + WALK_OUT
    else:
        end = last_t + LINGER[area[last_k]]
    # เวลาส่งกลับบ้าน (cur_dep = 999) — ที่ รพ.วังน้ำเขียว มักกดตอนแพทย์ตรวจเสร็จ ก่อนรับยา
    # จึงใช้เป็นเวลาออกเฉพาะเมื่อกดหลังกิจกรรมสุดท้าย ถ้ากดก่อน แปลว่า visit จบแล้ว ไม่ต้องค้างนาน
    home = r.get("home")
    in_clinic = area[last_k] in CLINICS
    if home is not None and home >= reg:
        if last_t <= home <= last_t + (CLINIC_HOME_MAX if in_clinic else HOME_MAX):
            end = max(home, last_t + WALK_OUT)
        elif home < last_t and area[last_k] is not None:
            end = min(end, last_t + HOME_LINGER)
    elif now is not None and in_clinic and deps.group_of(r.get("cd")) == area[last_k]:
        end = max(end, min(now + OPEN_AHEAD, reg + CLINIC_OPEN_MAX))
    if not segs:
        segs = [(reg, area["reg"])]
    return segs, end


def _min(col):
    return f"time_to_sec({col})/60"


#: เกลือของรหัส visit — ต้องเหมือนกันทุก worker ของ gunicorn (ไม่งั้นหุ่นสลับตัวตอนรีเฟรช)
_SALT = (os.getenv("OPD_FLOW_SALT")
         or hashlib.sha256(("opd-flow" + os.getenv("DB_USER", "") + os.getenv("DB_PASS", ""))
                           .encode()).hexdigest())


def _vid(vn):
    return hashlib.sha256((_SALT + str(vn)).encode()).hexdigest()[:10]


#: แคช — วันนี้สั้นตามรอบรีเฟรชหน้าเว็บ, วันก่อน ๆ ข้อมูลนิ่งแล้ว
TTL_TODAY = int(os.getenv("OPD_FLOW_TTL", "45"))
TTL_PAST = 3600
_cache = TTLCache(maxsize=32)


def build(d):
    today = date.today().isoformat()
    key = (db_tenant(), d)
    hit = _cache.get(key, TTL_TODAY if d >= today else TTL_PAST)
    if hit is not None:
        return hit

    rows = fetch(f"""
        select o.vn, {_min('ifnull(s.vsttime, o.vsttime)')} reg,
          {_min('s.service3')} s3, {_min('s.service4')} s4, {_min('s.service11')} s11,
          {_min('s.service5')} s5, {_min('s.service12')} s12, {_min('s.service6')} s6,
          {_min('s.service7')} s7, {_min('s.service16')} s16, {_min('s.service20')} s20,
          s.service3_dep d3, s.service4_dep d4, s.service5_dep d5, s.service7_dep d7, s.service12_dep d12,
          s.service20_dep d20, o.main_dep md, o.pt_priority pr, p.sex sex,
          o.an, o.pt_subtype st, o.cur_dep cd,
          case when o.cur_dep = '999' then {_min('o.cur_dep_time')} end home,
          (select {_min('time(min(e.enter_er_time))')} from er_regist e
            where e.vn = o.vn and date(e.enter_er_time) = o.vstdate) er_in,
          (select max(e.observe) from er_regist e where e.vn = o.vn) er_obs,
          (select max(e.er_emergency_level_id) from er_regist e where e.vn = o.vn) erl,
          (select {_min('min(l.order_time)')} from lab_head l
            where l.vn = o.vn and l.order_date = o.vstdate) lo,
          (select {_min('min(l.receive_time)')} from lab_head l
            where l.vn = o.vn and l.receive_date = o.vstdate) lr
        from ovst o left join {stmap.TABLE} s on s.vn = o.vn
          left join patient p on p.hn = o.hn
        where o.vstdate = %(d)s""", {"d": d})

    remote_deps = _remote_deps()
    lt = time.localtime()
    now = lt.tm_hour * 60 + lt.tm_min if d == today else None
    visits, remote, admitted = [], [], 0
    for r in rows:
        if r.get("an"):
            admitted += 1           # ผู้ป่วยใน (admit จาก OPD/ER) — ไม่นับในผัง OPD
            continue
        if r.get("md") in remote_deps or str(r.get("st") or "0") != "0":
            # Telemed / PCU (pt_subtype ≠ 0) ผู้ป่วยไม่ได้อยู่ใน รพ.
            if r.get("reg") is not None:
                remote.append(round(num(r["reg"]), 1))
            continue
        r["home"] = None if r.get("home") is None else round(num(r["home"]), 1)
        r["er_out"] = None
        for k in ORDER:
            r[k] = None if r.get(k) is None else round(num(r[k]), 1)
        if r["er_in"] is not None and r["reg"] is not None:
            r["er_in"] = max(r["er_in"], r["reg"])
            r["er_out"] = r["er_in"] + (ER_OBSERVE if r.get("er_obs") == "Y" else ER_STAY)
        if r["lo"] is not None and r["lr"] is not None and r["lr"] < r["lo"]:
            r["lr"] = None
        segs, end = _segments(r, now)
        if not segs:
            continue
        sex = str(r.get("sex") or "")
        visits.append({"i": _vid(r["vn"]), "s": [[t, AREA_IDX[a]] for t, a in segs],
                       "e": round(end, 1), "u": _urgency(r.get("erl"), r.get("pr")),
                       "g": int(sex) if sex in ("1", "2") else 0})
    visits.sort(key=lambda v: v["i"])

    data = {
        "date": d,
        "date_label": _thai_date(d),
        "is_today": d == today,
        # ER ไม่แสดงเวลารอ/ความหนาแน่น (คนไข้ฉุกเฉินไม่ได้ "รอคิว" แบบ OPD)
        "areas": [{"id": a, "name": n, "target": t, "nowait": a == "ER"} for a, n, t in AREAS],
        "admitted": admitted,
        "visits": visits,
        "remote": sorted(remote),
        "generated": time.strftime("%H:%M:%S"),
    }
    _cache.set(key, data)
    return data
