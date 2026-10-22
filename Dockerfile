# OPD Dashboard — container สำหรับ BMS Developer Portal (kube.bmscloud.in.th) หรือ Docker ทั่วไป
#   docker build -t opd-dashboard .
#
# ใช้ได้ 2 โหมด เลือกด้วย env OPD_DB_MODE ตอนรัน:
#   bms (ค่าเริ่มต้น) — Add-on บน BMS Marketplace อ่านข้อมูลผ่าน BMS Session API (ดู bms_session.py)
#       ไม่ต้องมีรหัสฐานข้อมูล · ปุ่มส่งออก PNG/JPG/PDF ปิดในโหมดนี้
#       docker run -p 8080:8080 opd-dashboard
#   direct — Dedicated Pod ต่อฐานข้อมูล HOSxP ตรง (ต้องผ่าน Audit ของ BMS ก่อนใช้บน Developer Portal)
#       docker run -p 8080:8080 -e OPD_DB_MODE=direct --env-file .env opd-dashboard
#       ค่าฐานข้อมูล (DB_HOST/DB_USER/DB_PASS ...) ส่งเป็น env ตอนรัน — ห้ามใส่ใน image
#       ถ้าปุ่มส่งออกใช้ไม่ได้เพราะ container ไม่รองรับ sandbox ของ chromium ให้เพิ่ม -e OPD_CHROME_NO_SANDBOX=1
FROM python:3.12-slim

# TZ: หน้า "วันนี้" และผังผู้ป่วยใช้เวลาเครื่อง ต้องเป็นเวลาไทย
# chromium: ส่งออก PNG/JPG/PDF (render.py) ใช้ในโหมด direct · fonts-thai-tlwg: ฟอนต์ไทยสำรองของ Chromium
# OPD_CACHE_TTL: โหมด bms ทุกคำสั่งวิ่งผ่าน HOSxP ของผู้ใช้ไปฐานข้อมูลหลัก (ไม่มี Slave) — แคชนานขึ้นลดภาระ
#   โหมด direct อยากให้ข้อมูลสดกว่านี้ ส่ง -e OPD_CACHE_TTL=60 ตอนรัน
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    OPD_DB_MODE=bms \
    TZ=Asia/Bangkok \
    OPD_CACHE_TTL=300 \
    OPD_FLOW_TTL=120 \
    PORT=8080
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium fonts-thai-tlwg tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

RUN useradd --create-home --uid 10001 app && mkdir -p out && chown -R app /app
USER app

EXPOSE 8080
# gthread: request หนึ่งรอ HOSxP API หลายวินาที — ใช้ thread ไม่ให้ผู้ใช้คนอื่นต้องรอ
# access log บันทึกแค่ path (%(U)s) ไม่มี query string — URL แรกมี bms-session-id ซึ่งแลกเป็น token ได้
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 8 --timeout 120 --access-logfile - --access-logformat '%(t)s %(m)s %(U)s %(s)s %(L)ss' app:app"]
