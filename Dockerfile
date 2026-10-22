# OPD Dashboard — container สำหรับ BMS Developer Portal (kube.bmscloud.in.th) หรือ Docker ทั่วไป
#
# มี 2 แบบ เลือกด้วย --target (ไม่ระบุ = bms ซึ่งเป็น stage สุดท้าย):
#   bms (ค่าเริ่มต้น) — Add-on บน BMS Marketplace อ่านข้อมูลผ่าน BMS Session API (ดู bms_session.py)
#       ไม่ต้องมีรหัสฐานข้อมูล · ปุ่มส่งออก PNG/JPG/PDF ปิด จึงไม่ลง chromium
#       (chromium ดึงไลบรารีระบบมาอีกหลายร้อยตัว — ช่องโหว่ที่ Trivy เจอส่วนใหญ่มาจากตรงนี้)
#       docker build -t opd-dashboard .
#       docker run -p 8080:8080 opd-dashboard
#   direct — Dedicated Pod ต่อฐานข้อมูล HOSxP ตรง + ปุ่มส่งออก (ต้องผ่าน Audit ของ BMS ก่อนใช้บน Developer Portal)
#       docker build --target direct -t opd-dashboard-direct .
#       docker run -p 8080:8080 --env-file .env opd-dashboard-direct
#       ค่าฐานข้อมูล (DB_HOST/DB_USER/DB_PASS ...) ส่งเป็น env ตอนรัน — ห้ามใส่ใน image
#       ถ้าปุ่มส่งออกใช้ไม่ได้เพราะ container ไม่รองรับ sandbox ของ chromium ให้เพิ่ม -e OPD_CHROME_NO_SANDBOX=1
FROM python:3.12-slim AS base

# TZ: หน้า "วันนี้" และผังผู้ป่วยใช้เวลาเครื่อง ต้องเป็นเวลาไทย
# OPD_CACHE_TTL: โหมด bms ทุกคำสั่งวิ่งผ่าน HOSxP ของผู้ใช้ไปฐานข้อมูลหลัก (ไม่มี Slave) — แคชนานขึ้นลดภาระ
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    OPD_DB_MODE=bms \
    TZ=Asia/Bangkok \
    OPD_CACHE_TTL=300 \
    OPD_FLOW_TTL=120 \
    PORT=8080
# upgrade: เก็บแพตช์ความปลอดภัยของ Debian ที่ออกหลัง image python ถูกสร้าง
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends tzdata \
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


# ---- direct: ต่อฐานข้อมูลตรง + chromium สำหรับส่งออก PNG/JPG/PDF (render.py)
FROM base AS direct
USER root
# fonts-thai-tlwg: ฟอนต์ไทยสำรองของ Chromium
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium fonts-thai-tlwg \
    && rm -rf /var/lib/apt/lists/*
# แคชเท่าค่าปกติของแอป (ฐานข้อมูลตรงรับภาระได้มากกว่า ข้อมูลสดกว่า)
ENV OPD_DB_MODE=direct \
    OPD_CACHE_TTL=120 \
    OPD_FLOW_TTL=45
USER app


# ---- bms: ค่าเริ่มต้น (stage สุดท้าย = สิ่งที่ Developer Portal บิลด์เมื่อไม่ระบุ target)
FROM base AS bms
