# OPD Dashboard — container สำหรับ BMS Developer Portal (Dedicated Pod) หรือ Docker ทั่วไป
#   docker build -t opd-dashboard .
#   docker run -p 8080:8080 --env-file .env opd-dashboard
# ค่าฐานข้อมูล (DB_HOST/DB_USER/DB_PASS ...) ส่งเป็น env ตอนรัน — ห้ามใส่ใน image
FROM python:3.12-slim

# TZ: หน้า "วันนี้" และผังผู้ป่วยใช้เวลาเครื่อง ต้องเป็นเวลาไทย
# chromium: ส่งออก PNG/JPG/PDF (render.py) · fonts-thai-tlwg: ฟอนต์ไทยสำรองของ Chromium
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 TZ=Asia/Bangkok PORT=8080
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium fonts-thai-tlwg tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --system --uid 10001 app && mkdir -p out && chown -R app /app
USER app

EXPOSE 8080
CMD exec gunicorn -w 3 -t 120 -b 0.0.0.0:${PORT} app:app
