"""ป้องกันการย้อนหาตัวบุคคลจากหน้าสาธารณะ (คนนอก รพ.) — แบบเดียวกับ anc / lr / ipd / er dashboard

ปัญหา: แดชบอร์ดและ /api/data.json เลือกช่วงได้แคบถึง 1 วัน พร้อมจำนวนรายแผนก/คลินิก และหน้า Flow 3D (/api/flow.json)
แสดงทุก visit ของวันที่เลือกเป็นรายคน (เวลาลงทะเบียน แผนกที่ไป เพศ ระดับความเร่งด่วน) — คนที่รู้ว่าใครมา รพ. วันไหน
จึงรู้ว่าคนนั้นไปคลินิกไหน (รวมคลินิกจิตเวช) ทั้งที่แอปถือว่ารายเคสระบุตัวได้และปิดหน้า /cases จากคนนอกอยู่แล้ว

มาตรการ (เฉพาะคนนอก รพ. — เครื่องใน รพ. เห็นเหมือนเดิม):
1. ช่วงวันที่ของแดชบอร์ด / data.json / ไฟล์ส่งออก ปัดเป็นเดือนเต็ม (วันที่ 1 ถึงสิ้นเดือน · เดือนปัจจุบันถึงวันนี้)
2. หน้า Flow 3D และ /api/flow.json เปิดได้เฉพาะเครื่องใน รพ. เหมือน /cases (app.py)

OPD_PUBLIC_MONTHLY=0 = ปิดข้อ 1 (ไม่แนะนำ) · ข้อ 2 เปิดให้ทุกที่ได้ด้วย OPD_PUBLIC_DRILLDOWN=1 เท่านั้น (แบบเดียวกับ /cases)
"""

import calendar
import os
from datetime import date


def enabled():
    return os.getenv("OPD_PUBLIC_MONTHLY", "1") != "0"


def month_window(d1, d2, today=None):
    """(d1, d2) แบบ ISO string → ปัดเป็นเดือนเต็ม · วันสิ้นสุดไม่เกินวันนี้"""
    today = today or date.today()
    a, b = date.fromisoformat(d1), date.fromisoformat(d2)
    end = b.replace(day=calendar.monthrange(b.year, b.month)[1])
    return a.replace(day=1).isoformat(), min(end, today).isoformat()
