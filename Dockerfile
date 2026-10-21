# OPD Dashboard แบบ Add-on บน BMS Marketplace (BMS Developer Portal / kube.bmscloud.in.th)
# อ่านข้อมูลผ่าน BMS Session API เท่านั้น — ไม่มีรหัสฐานข้อมูลใน image (ดู bms_session.py)
# ปุ่มส่งออก PNG/JPG/PDF ปิดในโหมดนี้ จึงไม่ต้องลง chromium (image เล็ก)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OPD_DB_MODE=bms \
    # วันที่ "วันนี้" ต้องเป็นเวลาไทย (container เป็น UTC) — ใช้รูปแบบ POSIX ไม่ต้องลง tzdata
    TZ=ICT-7 \
    # ทุกคำสั่งวิ่งผ่าน HOSxP ของผู้ใช้ไปฐานข้อมูลหลัก (ไม่มี Slave) — แคชนานขึ้นลดภาระ
    OPD_CACHE_TTL=300 \
    OPD_FLOW_TTL=120 \
    PORT=8080

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

EXPOSE 8080
# gthread: request หนึ่งรอ HOSxP API หลายวินาที — ใช้ thread ไม่ให้ผู้ใช้คนอื่นต้องรอ
# access log บันทึกแค่ path (%(U)s) ไม่มี query string — URL แรกมี bms-session-id ซึ่งแลกเป็น token ได้
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 8 --timeout 120 --access-logfile - --access-logformat '%(t)s %(m)s %(U)s %(s)s %(L)ss' app:app"]
