"""ตรวจความพร้อมของข้อมูล HOSxP ก่อนใช้แดชบอร์ด (หน้า /check)

แต่ละโรงพยาบาลกดเวลาลงคอลัมน์ของ `service_time` ไม่เหมือนกัน หน้านี้บอกว่า
  - คอลัมน์ service1 … service20 มีข้อมูลกี่ % ของ visit และถูกกดจากจุดบริการไหน
  - ขั้นบริการที่แดชบอร์ดใช้ (stmap.STEPS) อ่านจากคอลัมน์ไหน ครอบคลุมเท่าไร
  - ช่องไหนบนแดชบอร์ดจะขึ้น "–" เพราะไม่มีคู่เวลาให้คำนวณ
  - ข้อเสนอค่า OPD_ST_MAP เมื่อขั้นไหนแทบไม่มีข้อมูล แต่มีคอลัมน์อื่นที่น่าจะใช้แทนได้
  - Data Audit: แผนกแต่ละรหัสถูกจัดเป็นกลุ่มอะไร และรหัสที่แอปสมมติไว้ (นัด, กลับบ้าน, ผลวินิจฉัยหลัก …)
    ตรงกับข้อมูลของโรงพยาบาลนี้หรือไม่ — รหัสของแต่ละ รพ. ไม่เหมือนกัน ถ้าไม่ตรง ตัวเลขบนแดชบอร์ดจะเพี้ยน
แสดงเฉพาะจำนวนนับและชื่อแผนก ไม่มีข้อมูลรายคน
"""

import os

import deps
import queries
import stmap
from db import fetch, fetch_one, num

#: % ของ visit ที่ถือว่า "ใช้ได้" / "มีบางส่วน" (ไม่ใช่ทุก visit ผ่านทุกขั้น เช่น ไม่มียา ไม่ต้องจ่ายเงิน)
OK_PCT, PART_PCT = 50, 10
#: คอลัมน์ที่จะเสนอเป็นตัวแทน ต้องมีข้อมูลอย่างน้อยเท่านี้
SUGGEST_PCT = 30

#: ขั้นมาตรฐาน → กลุ่มแผนก (deps.classify) ที่ควรเป็นผู้กดเวลา ใช้หาคอลัมน์ทดแทน
#: ขั้นที่อยู่ในกลุ่มเดียวกันเรียงตามลำดับเวลา: คอลัมน์ที่กดก่อน = ขั้นแรก
PAIRS = [
    (("service4", "service11"), {"SCR", "NCD", "ARI"}),
    (("service5", "service12"), {"R1", "R2", "R3", "R4", "R5", "DENT", "SPEC", "TELE"}),
    (("service6", "service16"), {"RX"}),
    (("service7",), {"CASH"}),
]


def _dep_name(code):
    name = deps.name_of(code)
    return name if name and name != code else f"(ไม่ระบุแผนก{' ' + code if code else ''})"


def _status(pct):
    return "ok" if pct >= OK_PCT else "part" if pct >= PART_PCT else "none"


def _columns(d1, d2):
    """สถิติของคอลัมน์จริงทุกตัว: ความครอบคลุม เวลาเฉลี่ยหลังลงทะเบียน และแผนกที่กด"""
    cols = []
    for c in stmap.ALL:
        m = f"time_to_sec(timediff(s.{c}, s.vsttime))/60"
        cols.append(f"sum(s.{c} is not null) n_{c}")
        cols.append(f"avg(case when {m} between 0 and {queries.MAX_GAP} then {m} end) m_{c}")
    r = fetch_one(f"""
        select count(*) visits, sum(s.vn is not null) st_rows, {', '.join(cols)}
        from ovst o left join service_time s on s.vn = o.vn
        where o.vstdate between %(d1)s and %(d2)s""", {"d1": d1, "d2": d2}) or {}
    visits = num(r.get("visits"))

    # แบ่งเป็นชุดละ 10 คอลัมน์ — BMS Session API นับตารางทุกครั้งที่อ้างถึง และรับไม่เกิน 20 ต่อคำสั่ง
    by = {}
    for i in range(0, len(stmap.ALL), 10):
        union = " union all ".join(
            f"select '{c}' c, s.{c}_dep dep, count(*) n from service_time s "
            f"where s.vstdate between %(d1)s and %(d2)s and s.{c} is not null group by s.{c}_dep"
            for c in stmap.ALL[i:i + 10])
        for row in fetch(union, {"d1": d1, "d2": d2}):
            by.setdefault(row["c"], []).append((num(row["n"]), row["dep"] or ""))

    used = {stmap.phys(c): c for c in stmap.STD if stmap.phys(c)}
    out = []
    for c in stmap.ALL:
        n = num(r.get(f"n_{c}"))
        pct = queries._pct(n, visits)
        top = sorted(by.get(c, []), reverse=True)[:3]
        m = r.get(f"m_{c}")
        out.append({
            "col": c, "n": n, "pct": pct, "status": _status(pct),
            "after": round(num(m)) if m is not None else None,
            "deps": [{"code": d, "name": _dep_name(d), "group": deps.group_of(d),
                      "pct": queries._pct(k, n, 0)} for k, d in top],
            "used_as": used.get(c),
        })
    return visits, num(r.get("st_rows")), out


def _suggest(steps, cols):
    """ขั้นที่ข้อมูลแทบไม่มี → คอลัมน์ที่ยังไม่ถูกใช้ ซึ่งกดจากจุดบริการกลุ่มที่ควรเป็น"""
    used = {s["phys"] for s in steps if s["phys"]}
    by_std = {s["col"]: s for s in steps}
    out = {}
    for std_cols, groups in PAIRS:
        if all(by_std[c]["pct"] >= PART_PCT for c in std_cols):
            continue
        cand = [c for c in cols
                if c["col"] not in used and c["pct"] >= SUGGEST_PCT and c["deps"]
                and c["deps"][0]["group"] in groups]
        cand.sort(key=lambda c: c["after"] if c["after"] is not None else 999)
        for std, c in zip(std_cols, cand):
            if by_std[std]["pct"] < PART_PCT:
                out[std] = c["col"]
                used.add(c["col"])
    return out


def _other_sources(d1, d2, visits):
    """ตารางเวลาอื่นของ HOSxP — แสดงเพื่อให้รู้ว่ามีข้อมูลหรือไม่ (แดชบอร์ดยังใช้ service_time)"""
    checks = [
        ("opd_dep_queue", "คิวรายหน่วยบริการ (เวลาเข้าคิว / รับคิว / เสร็จ)",
         f"""select count(distinct vn) v, sum(accept_datetime is not null) acc, count(*) n
             from opd_dep_queue where queue_datetime >= %(d1)s and queue_datetime < %(d2)s + interval 1 day"""),
        ("ovst_service_time", "ระยะเวลาให้บริการรายขั้น (OPD-SCREEN, OPD-DOCTOR …)",
         f"""select count(distinct vn) v, count(*) n from ovst_service_time
             where service_date between %(d1)s and %(d2)s"""),
        ("lab_head", "เวลาสั่ง / รับ / รายงานผล Lab",
         f"select count(distinct vn) v, count(*) n from lab_head where order_date between %(d1)s and %(d2)s"),
        ("er_regist", "เวลาเข้าห้องฉุกเฉิน",
         f"""select count(distinct vn) v, count(*) n from er_regist
             where enter_er_time >= %(d1)s and enter_er_time < %(d2)s + interval 1 day"""),
        ("oapp", "นัดหมาย",
         f"select count(*) v, count(*) n from oapp where nextdate between %(d1)s and %(d2)s"),
    ]
    out = []
    for table, label, sql in checks:
        try:
            r = fetch_one(sql, {"d1": d1, "d2": d2}) or {}
            v = num(r.get("v"))
            row = {"table": table, "label": label, "v": v, "n": num(r.get("n")),
                   "pct": queries._pct(v, visits) if table != "oapp" else None}
            if "acc" in r:
                row["acc"] = queries._pct(num(r.get("acc")), num(r.get("n")))
            out.append(row)
        except Exception as e:                       # บางรุ่นของ HOSxP ไม่มีตารางนี้
            out.append({"table": table, "label": label, "error": type(e).__name__})
    return out


# ------------------------------------------------------------ Data Audit

#: แผนกที่ไม่เข้ากลุ่มใดแต่มี visit อย่างน้อยเท่านี้ (% ของ visit) → ให้ตรวจว่าควรอยู่กลุ่มไหน
DEP_WARN_PCT = 1.0
#: เกณฑ์ของรหัสอื่น ๆ (% ของ visit)
MISSING_WARN_PCT = 5.0       # firstday / สิทธิ ว่างเกินนี้ = ตัวเลขที่เกี่ยวข้องคลาดเคลื่อน
PDX_WARN_PCT = 80.0          # visit ที่มีวินิจฉัย แต่มีวินิจฉัยหลัก (diagtype 1) น้อยกว่านี้
HOME_WARN_PCT = 30.0         # visit ที่จบด้วยแผนก 999 (กลับบ้าน) น้อยกว่านี้

#: กลุ่มแผนก → ผลต่อแดชบอร์ด (แสดงในตาราง Data Audit)
GROUP_LABEL = {
    "ADMIN": "เวชระเบียน — ไม่ถือเป็นจุดที่ผู้ป่วยอยู่",
    "SCR": "ซักประวัติ / คัดกรอง", "NCD": "คลินิก NCD", "ARI": "คลินิก ARI", "LAB": "ห้องแล็บ",
    **{f"R{i}": f"ห้องตรวจ {i}" for i in range(1, 6)},
    "TELE": "Telemed — ผู้ป่วยไม่อยู่ใน รพ. (ไม่วาดในผังผู้ป่วย)",
    "ER": "ห้องฉุกเฉิน — แยกออกจากเวลารอ OPD",
    "DENT": "ทันตกรรม", "SPEC": "ปฐมภูมิ / คลินิกเฉพาะ", "MH": "สุขภาพจิต", "PT": "กายภาพบำบัด",
    "TTM": "แพทย์แผนไทย",
    "RX": "ห้องยา — ส่งคิวแรกมาที่นี่นับเป็น “ส่งคิวไม่ตรง”",
    "CASH": "การเงิน — ส่งคิวแรกมาที่นี่นับเป็น “ส่งคิวไม่ตรง”",
}


def _safe(fn, *args):
    """ตารางบางตัวไม่มีในบางรุ่น / BMS Session API ไม่อนุญาต → ข้ามข้อนั้น ไม่ให้ทั้งหน้าล้ม"""
    try:
        return fn(*args)
    except Exception as e:
        return {"error": type(e).__name__}


def _dep_audit(d1, d2, visits):
    """แผนกหลักของ visit (ovst.main_dep) แต่ละรหัสถูกจัดเป็นกลุ่มอะไร"""
    rows = fetch("""
        select o.main_dep dep, count(*) n from ovst o
        where o.vstdate between %(d1)s and %(d2)s group by o.main_dep""", {"d1": d1, "d2": d2})
    over = deps.overrides()
    out = []
    for r in sorted(rows, key=lambda r: -num(r["n"])):
        code, n = r["dep"] or "", num(r["n"])
        g = deps.group_of(code)
        pct = queries._pct(n, visits)
        home = code in queries.MISROUTE_CODES
        out.append({
            "code": code, "name": _dep_name(code), "n": n, "pct": pct, "group": g,
            "label": ("กลับบ้าน — ส่งคิวแรกมาที่นี่นับเป็น “ส่งคิวไม่ตรง”" if home and not g else
                      GROUP_LABEL.get(g, "ไม่เข้ากลุ่ม — นับเป็นคลินิก OPD ทั่วไป")),
            "override": code in over,
            "warn": g is None and not home and pct >= DEP_WARN_PCT,
        })
    return {"rows": out, "warn": [r for r in out if r["warn"]]}


def _code_audit(d1, d2, visits):
    """รหัสที่แอปสมมติไว้ เทียบกับข้อมูลจริงของโรงพยาบาล → [{label, assume, found, status, fix}]"""
    p = {"d1": d1, "d2": d2, "appt": queries.APPT_CODES}
    out = []

    # 1. มาตามนัด (ovst.ovstist)
    def appt():
        rows = fetch("""
            select o.ovstist code, i.name, count(*) n from ovst o
              left join ovstist i on i.ovstist = o.ovstist
            where o.vstdate between %(d1)s and %(d2)s group by o.ovstist, i.name""", p)
        used = [r for r in rows if (r["code"] or "") in queries.APPT_CODES]
        cand = [r for r in rows if (r["code"] or "") not in queries.APPT_CODES and "นัด" in (r["name"] or "")]
        n = sum(num(r["n"]) for r in used)
        names = ", ".join(f"{r['code']} {r['name'] or ''}".strip() for r in used) or "ไม่มี visit ด้วยรหัสนี้"
        st = "bad" if not n else "warn" if cand else "ok"
        fix = None
        if cand:
            fix = "OPD_APPT_CODES=" + ",".join(queries.APPT_CODES + [r["code"] for r in cand])
        elif not n:
            fix = "ตรวจตาราง ovstist ว่ารหัสไหนคือ “นัดมา” แล้วตั้ง OPD_APPT_CODES"
        return {"label": "มาตามนัด (ovst.ovstist)", "assume": ", ".join(queries.APPT_CODES),
                "found": f"{names} · {queries._pct(n, visits)}% ของ visit"
                         + (" · มีรหัสอื่นที่ชื่อมีคำว่า “นัด”: " +
                            ", ".join(f"{r['code']} {r['name']}" for r in cand) if cand else ""),
                "status": st, "fix": fix,
                "impact": "บล็อก 2/9 (นัด vs Walk-in), บล็อก 7, หน้ารายเคส"}
    out.append(_safe(appt))

    # 2. ข้อมูลผู้ป่วย / สิทธิ / กลับบ้าน ในคำสั่งเดียว
    def basics():
        r = fetch_one("""
            select count(*) n, sum(o.cur_dep = '999') home,
              sum(p.hn is not null and p.firstday is null) nofirst,
              sum(o.pttype is null or o.pttype = '') nopt
            from ovst o left join patient p on p.hn = o.hn
            where o.vstdate between %(d1)s and %(d2)s""", p) or {}
        n = num(r.get("n"))
        home_pct, nofirst, nopt = (queries._pct(num(r.get(k)), n) for k in ("home", "nofirst", "nopt"))
        home_name = deps.name_of("999")
        return [
            {"label": "กลับบ้าน (แผนกปัจจุบัน 999)", "assume": "999",
             "found": f"999 = {home_name if home_name != '999' else 'ไม่มีใน kskdepartment'} · "
                      f"{home_pct}% ของ visit จบด้วย 999",
             "status": "bad" if home_name == "999" else "warn" if home_pct < HOME_WARN_PCT else "ok",
             "fix": None if home_pct >= HOME_WARN_PCT else "ผังผู้ป่วยใช้เวลาส่งกลับบ้านจากรหัสนี้ — ตรวจว่า รพ. ส่งกลับบ้านด้วยรหัสอะไร",
             "impact": "ผังผู้ป่วย (เวลาออก), บล็อก 3 ส่งคิวไม่ตรง"},
            {"label": "ผู้ป่วยใหม่ (patient.firstday)", "assume": "firstday = วันที่มา",
             "found": f"ไม่มี firstday {nofirst}% ของ visit",
             "status": "warn" if nofirst > MISSING_WARN_PCT else "ok", "fix": None,
             "impact": "จำนวนผู้ป่วยใหม่ (บล็อก 1, ตารางรายแผนก)"},
            {"label": "สิทธิการรักษา (ovst.pttype)", "assume": "ทุก visit มีสิทธิ",
             "found": f"ไม่มีสิทธิ {nopt}% ของ visit",
             "status": "warn" if nopt > MISSING_WARN_PCT else "ok", "fix": None,
             "impact": "บล็อก 8 สิทธิ"},
        ]
    b = _safe(basics)
    out.extend(b if isinstance(b, list) else [b])

    # 3. วินิจฉัยหลัก
    def pdx():
        r = fetch_one("""
            select count(distinct d.vn) dx, count(distinct case when d.diagtype = '1' then d.vn end) pdx
            from ovstdiag d join ovst o on o.vn = d.vn
            where o.vstdate between %(d1)s and %(d2)s""", p) or {}
        pct = queries._pct(num(r.get("pdx")), num(r.get("dx")))
        return {"label": "วินิจฉัยหลัก (ovstdiag.diagtype)", "assume": "1",
                "found": f"{pct}% ของ visit ที่มีวินิจฉัย มี diagtype 1",
                "status": "warn" if pct < PDX_WARN_PCT else "ok", "fix": None,
                "impact": "บล็อก 8 กลุ่มโรค Top 5"}
    out.append(_safe(pdx))

    # 4. แผนกฉุกเฉิน
    er = [c.strip() for c in queries.ER_DEP.split(",")] if queries.ER_DEP else deps.codes_in("ER")
    out.append({"label": "ห้องฉุกเฉิน (แยกออกจากเวลารอ OPD)",
                "assume": "OPD_ER_DEP" if queries.ER_DEP else "แผนกที่ชื่อมี ER / ฉุกเฉิน / อุบัติเหตุ",
                "found": ", ".join(f"{c} {deps.name_of(c)}" for c in er) or "ไม่พบแผนก",
                "status": "ok" if er else "bad",
                "fix": None if er else "ตั้ง OPD_DEP_MAP=<รหัส>=ER หรือ OPD_ER_DEP=<รหัส>",
                "impact": "ผู้ป่วย ER ถูกนับรวมเวลารอ OPD"})
    return out


def audit(d1, d2, visits):
    """Data Audit ทั้งหมด + สรุปจำนวนเรื่องที่ควรแก้ (ใช้ทั้งหน้า /check และ setup_check.py)"""
    dep = _safe(_dep_audit, d1, d2, visits)
    codes = _code_audit(d1, d2, visits)
    issues = []
    for w in (dep.get("warn") or []):
        issues.append(f"แผนก {w['code']} {w['name']} ({w['pct']}% ของ visit) ไม่เข้ากลุ่มใด")
    for c in codes:
        if c.get("status") in ("warn", "bad"):
            issues.append(f"{c['label']}: {c['found']}")
    return {"deps": dep, "codes": codes, "issues": issues,
            "audited": os.getenv("OPD_DATA_AUDITED", "0") == "1"}


def run(d1, d2):
    visits, st_rows, cols = _columns(d1, d2)
    by_col = {c["col"]: c for c in cols}
    steps = []
    for std, alias, meaning in stmap.STEPS:
        p = stmap.phys(std)
        c = by_col.get(p) if p else None
        pct = c["pct"] if c else 0.0
        steps.append({"col": std, "alias": alias, "meaning": meaning, "phys": p,
                      "mapped": std in stmap.MAP, "pct": pct, "status": _status(pct),
                      "deps": c["deps"] if c else []})

    st = queries.service_times(d1, d2)
    sla = [{"label": r["label"], "n": r["n"], "pct": queries._pct(r["n"], visits),
            "status": _status(queries._pct(r["n"], visits)), "avg": r["avg"]}
           for r in st["sla"]]

    sug = _suggest(steps, cols)
    sug_env = ",".join(f"{stmap.STEPS[stmap.STD.index(k)][1]}:{v}" for k, v in sug.items())
    if sug_env and stmap.MAP:
        keep = {k: v for k, v in stmap.MAP.items() if k not in sug}
        sug_env = ",".join([f"{stmap.STEPS[stmap.STD.index(k)][1]}:{v}" for k, v in keep.items()] +
                           [sug_env])
    a = audit(d1, d2, visits)
    a["issues"] = [f"ขั้น “{s['meaning']}” แทบไม่มีข้อมูล ({s['pct']}%) — ช่องที่ใช้ขั้นนี้จะเป็น “–”"
                   for s in steps if s["status"] == "none"] + a["issues"]
    return {
        "visits": visits, "st_rows": st_rows, "st_pct": queries._pct(st_rows, visits),
        "steps": steps, "cols": cols, "sla": sla,
        "suggest": sug, "suggest_env": sug_env,
        "current_env": ",".join(f"{stmap.STEPS[stmap.STD.index(k)][1]}:{v}"
                                for k, v in stmap.MAP.items()),
        "map_errors": stmap.ERRORS,
        "others": _other_sources(d1, d2, visits),
        "ok_pct": OK_PCT, "part_pct": PART_PCT,
        "audit": a,
    }
