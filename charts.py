"""ตัวช่วยคำนวณรูปทรงกราฟ SVG ที่วาดฝั่งเซิร์ฟเวอร์ (ไม่โหลดไลบรารีกราฟจากภายนอก)"""

import math


def nice_max(v, ticks=5):
    """ปัดค่าสูงสุดของแกนขึ้นเป็นเลขกลม ๆ ที่หารด้วยจำนวนช่องลงตัว"""
    if not v or v <= 0:
        return ticks
    raw = v / ticks
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if raw <= m * mag:
            return m * mag * ticks
    return 10 * mag * ticks


def smooth_path(points, floor=None, tension=0.18):
    """เส้นโค้งผ่านทุกจุด (Catmull-Rom → Bezier) คืนค่า attribute d ของ <path>

    points: [(x, y), ...] เรียงตาม x
    floor : พิกัด y ของแกนศูนย์ — กันเส้นโค้งพุ่งต่ำกว่าศูนย์ตรงช่วงที่ค่าเป็น 0
    """
    clamp = (lambda y: min(y, floor)) if floor is not None else (lambda y: y)
    if not points:
        return ""
    if len(points) == 1:
        x, y = points[0]
        return f"M{x:.1f},{y:.1f}"
    d = [f"M{points[0][0]:.1f},{points[0][1]:.1f}"]
    for i in range(len(points) - 1):
        p0 = points[i - 1] if i > 0 else points[i]
        p1, p2 = points[i], points[i + 1]
        p3 = points[i + 2] if i + 2 < len(points) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) * tension, clamp(p1[1] + (p2[1] - p0[1]) * tension))
        c2 = (p2[0] - (p3[0] - p1[0]) * tension, clamp(p2[1] - (p3[1] - p1[1]) * tension))
        d.append(f"C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}")
    return " ".join(d)
