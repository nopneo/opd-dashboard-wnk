"""ตรวจความพร้อมของข้อมูล HOSxP ก่อนใช้แดชบอร์ด (หน้า /check)

แต่ละโรงพยาบาลกดเวลาลงคอลัมน์ของ `service_time` ไม่เหมือนกัน หน้านี้บอกว่า
  - คอลัมน์ service1 … service20 มีข้อมูลกี่ % ของ visit และถูกกดจากจุดบริการไหน
  - ขั้นบริการที่แดชบอร์ดใช้ (stmap.STEPS) อ่านจากคอลัมน์ไหน ครอบคลุมเท่าไร
  - ช่องไหนบนแดชบอร์ดจะขึ้น "–" เพราะไม่มีคู่เวลาให้คำนวณ
  - ข้อเสนอค่า OPD_ST_MAP เมื่อขั้นไหนแทบไม่มีข้อมูล แต่มีคอลัมน์อื่นที่น่าจะใช้แทนได้
แสดงเฉพาะจำนวนนับและชื่อแผนก ไม่มีข้อมูลรายคน
"""

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
    return {
        "visits": visits, "st_rows": st_rows, "st_pct": queries._pct(st_rows, visits),
        "steps": steps, "cols": cols, "sla": sla,
        "suggest": sug, "suggest_env": sug_env,
        "current_env": ",".join(f"{stmap.STEPS[stmap.STD.index(k)][1]}:{v}"
                                for k, v in stmap.MAP.items()),
        "map_errors": stmap.ERRORS,
        "others": _other_sources(d1, d2, visits),
        "ok_pct": OK_PCT, "part_pct": PART_PCT,
    }
