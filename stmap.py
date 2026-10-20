"""ความหมายของคอลัมน์เวลาในตาราง `service_time` ของ HOSxP

แต่ละโรงพยาบาลตั้งค่าเองว่าจุดบริการไหนกดเวลาลงคอลัมน์ไหน (service1 … service20)
โค้ดทั้งหมดอ้างชื่อตามแบบ รพ.วังน้ำเขียว (ดู STEPS) — ถ้าที่อื่นบันทึกต่างไป
ให้กำหนด env `OPD_ST_MAP` เช่น

    OPD_ST_MAP=screen:service1,screen_end:service2
    OPD_ST_MAP=service4:service1,service11:service2      (ใช้ชื่อคอลัมน์มาตรฐานเป็นตัวตั้งก็ได้)
    OPD_ST_MAP=send:none                                 (none = ไม่มีขั้นนี้)

เมื่อมีการกำหนด ทุกคำสั่ง SQL จะอ่าน `service_time` ผ่าน derived table ที่เปลี่ยนชื่อคอลัมน์ให้
(MariaDB รวม derived table แบบนี้เข้ากับคำสั่งหลักเอง ยังใช้ index ของ vstdate ได้)
ดูความครอบคลุมของแต่ละคอลัมน์ได้ที่หน้า /check
"""

import os
import re

#: (คอลัมน์มาตรฐาน, ชื่อสั้นใน OPD_ST_MAP, ความหมาย) — เรียงตามลำดับขั้นบริการ
STEPS = [
    ("service3", "send", "ส่งตรวจ (ห้องบัตรส่งต่อ)"),
    ("service4", "screen", "เริ่มซักประวัติ / คัดกรอง"),
    ("service11", "screen_end", "คัดกรองเสร็จ → ส่งพบแพทย์"),
    ("service5", "doctor", "แพทย์เริ่มตรวจ"),
    ("service12", "doctor_end", "แพทย์ตรวจเสร็จ"),
    ("service6", "rx_in", "ใบสั่งยาถึงห้องจ่ายยา"),
    ("service7", "pay", "ชำระเงิน"),
    ("service16", "rx_out", "จ่ายยาเสร็จ"),
    ("service20", "unit_end", "จบบริการที่หน่วยเฉพาะ (ทันตกรรม กายภาพ ฯลฯ)"),
]
STD = [s[0] for s in STEPS]
ALIAS = {s[1]: s[0] for s in STEPS}
#: คอลัมน์เวลาทั้งหมดที่ตาราง service_time มี
ALL = [f"service{i}" for i in range(1, 21)]


def _parse(raw):
    """'screen:service1,service11:service2' → {'service4': 'service1', 'service11': 'service2'}

    ค่าที่อ่านไม่ได้จะถูกข้ามและเก็บไว้ใน ERRORS ให้หน้า /check แสดง
    """
    out, errors = {}, []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            errors.append(part)
            continue
        k, v = (x.strip().lower() for x in part.split(":", 1))
        k = ALIAS.get(k, k)
        if k not in STD or not (v == "none" or v in ALL):
            errors.append(part)
            continue
        out[k] = v
    return out, errors


MAP, ERRORS = _parse(os.getenv("OPD_ST_MAP", ""))


def phys(col):
    """คอลัมน์จริงใน service_time ของขั้นมาตรฐาน col (None = ไม่มีขั้นนี้)"""
    v = MAP.get(col, col)
    return None if v == "none" else v


def _derived():
    cols = ["vn", "hn", "vstdate", "vsttime"]
    for c in STD:
        p = phys(c)
        cols.append(f"{p} {c}" if p else f"cast(null as time) {c}")
        cols.append(f"{p}_dep {c}_dep" if p else f"cast(null as char(3)) {c}_dep")
    return "(select " + ", ".join(cols) + " from service_time)"


#: ใช้แทนชื่อตาราง service_time ในทุกคำสั่ง SQL: f"from {stmap.TABLE} s"
TABLE = _derived() if MAP else "service_time"

# ชื่อคอลัมน์ถูกต่อเข้า SQL ตรง ๆ — ตรวจซ้ำอีกชั้น (ไม่ใช้ assert เพราะ python -O จะตัดทิ้ง)
if not all(re.fullmatch(r"service\d{1,2}|none", v) for v in MAP.values()):
    raise ValueError(f"OPD_ST_MAP มีชื่อคอลัมน์ไม่ถูกต้อง: {MAP}")
