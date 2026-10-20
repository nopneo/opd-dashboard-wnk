"""แคชผลลัพธ์ในหน่วยความจำ — มีอายุ (TTL) และจำกัดจำนวนรายการ

เดิมใช้ dict เปล่า ซึ่งเก็บทุกช่วงวันที่ที่เคยมีคนเปิดไว้ตลอดอายุโปรเซส หน่วยความจำจึงโตไม่หยุด
ตัวนี้ลบรายการที่เก่าที่สุด (ใช้งานล่าสุดนานที่สุด) เมื่อเกิน maxsize
"""

import threading
import time
from collections import OrderedDict


class TTLCache:
    def __init__(self, maxsize=64):
        self.maxsize = maxsize
        self._data = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key, ttl):
        """ค่าที่เก็บไว้ถ้ายังไม่เกิน ttl วินาที ไม่งั้น None"""
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            if time.time() - hit[0] >= ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return hit[1]

    def set(self, key, value):
        with self._lock:
            self._data[key] = (time.time(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def __len__(self):
        return len(self._data)
