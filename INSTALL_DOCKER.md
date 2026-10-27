# ติดตั้ง OPD Dashboard ด้วย Docker

คู่มือนี้สำหรับติดตั้ง**ในโรงพยาบาล** ให้แอปต่อฐานข้อมูล HOSxP ตรง (แบบเดียวกับ [INSTALL.md](INSTALL.md) ข้อ 2–3
แต่ไม่ต้องลง Python / Chromium บนเครื่องเอง) · ข้อมูลไม่ออกนอกโรงพยาบาล

ถ้าจะรันเป็น Add-on บน BMS Developer Portal (อ่านข้อมูลผ่าน BMS Session API) ดู [INSTALL.md](INSTALL.md) ข้อ 8 แทน

**ขั้นตอนโดยย่อ:** ติดตั้ง Docker → ได้โค้ดแอป → สร้าง `.env` → `docker compose up -d --build` → เปิด `/check`

## 1. สิ่งที่ต้องมี

| รายการ | หมายเหตุ |
|---|---|
| เครื่องในเครือข่าย รพ. ที่ลง Docker ได้ | Linux: Docker Engine + Compose plugin · Windows: Docker Desktop (WSL 2) · RAM ว่าง 1 GB ขึ้นไป |
| อินเทอร์เน็ตตอนบิลด์ครั้งแรก | ดาวน์โหลด image `python:3.12-alpine`, chromium และไลบรารี Python (หลังบิลด์แล้วไม่ต้องใช้) |
| บัญชีฐานข้อมูล HOSxP แบบ**อ่านอย่างเดียว** | ดูข้อ 4 เรื่อง IP ที่ต้อง GRANT |

ตรวจว่า Docker พร้อม:

```bash
docker --version
docker compose version
```

## 2. ได้โค้ดแอป

เลือกอย่างใดอย่างหนึ่ง:

```bash
# ก) ชุดติดตั้ง zip จาก GitHub Releases
unzip opd_dashboard-<เวอร์ชัน>.zip && cd opd_dashboard

# ข) git
git clone https://github.com/nopneo/opd-dashboard-wnk.git opd_dashboard && cd opd_dashboard
```

ต้องเห็นไฟล์ `Dockerfile`, `docker-compose.yml` และ `.env.example` ในโฟลเดอร์

## 3. สร้างไฟล์ `.env`

```bash
cp .env.example .env
chmod 600 .env          # Linux — ไฟล์นี้มีรหัสผ่านฐานข้อมูล
```

แก้ค่าฐานข้อมูลใน `.env`:

```ini
OPD_DB_MODE=direct
DB_HOST=192.168.1.10        # IP เครื่องฐานข้อมูล HOSxP — ห้ามใช้ 127.0.0.1 (ดูข้อ 4)
DB_PORT=3306
DB_NAME=hos
DB_USER=opd_ro
DB_PASS=<รหัสผ่าน>
OPD_CONTACT=งานสารสนเทศ โทร 1234
```

`PORT` ใน `.env` ไม่มีผล — `docker-compose.yml` กำหนดพอร์ตเอง (ข้อ 5) · ค่าอื่น ๆ ทั้งหมดใช้ได้เหมือน INSTALL.md ข้อ 4

## 4. ฐานข้อมูลอยู่ที่ไหน → ใส่ `DB_HOST` และ GRANT อย่างไร

ใน container `127.0.0.1` คือตัว container เอง ไม่ใช่เครื่องที่ลง Docker

| ฐานข้อมูล HOSxP อยู่ | `DB_HOST` | GRANT ให้ IP ไหน |
|---|---|---|
| **เครื่องอื่น** (กรณีส่วนใหญ่) | IP เครื่องฐานข้อมูล เช่น `192.168.1.10` | IP ของ**เครื่องที่ลง Docker** |
| **เครื่องเดียวกับ Docker** | `host.docker.internal` | วง IP ของ Docker เช่น `'opd_ro'@'172.%'` · MariaDB ต้องไม่ผูก `bind-address=127.0.0.1` |

ไม่แน่ใจว่าต้อง GRANT ให้ IP ไหน: รันข้อ 5 ไปก่อน แล้วดู IP ใน error `Access denied for user 'opd_ro'@'<IP>'` (ข้อ 7)

```sql
CREATE USER 'opd_ro'@'<IP ตามตาราง>' IDENTIFIED BY '<รหัสผ่าน>';
GRANT SELECT ON hos.* TO 'opd_ro'@'<IP ตามตาราง>';
```

## 5. บิลด์และรัน

```bash
docker compose up -d --build
```

ครั้งแรกใช้เวลา 2–5 นาที (ดาวน์โหลด chromium) แล้วเปิด **`http://<IP เครื่องนี้>:5900/`**

`docker-compose.yml` ที่มากับโค้ด:
- บิลด์ target **`direct`** (ต่อฐานข้อมูลตรง + ปุ่มส่งออก PNG/JPG/PDF)
- เปิดพอร์ต `5900` ของเครื่อง → `8080` ใน container · เปลี่ยนพอร์ตที่บรรทัด `- "5900:8080"`
- `restart: unless-stopped` — เปิดเครื่องใหม่แอปขึ้นเอง (ต้องตั้ง Docker ให้เริ่มตอนบูต: Linux `systemctl enable docker`)
- เวลาใน container เป็นเวลาไทย (`TZ=Asia/Bangkok`) · รันด้วย user ธรรมดา (uid 10001) ไม่ใช่ root
- ปิด sandbox ของ chromium (`OPD_CHROME_NO_SANDBOX=1`) — ใช้ใน container ไม่ได้ ตัว container กั้นแทน

ไม่ใช้ Compose ก็ได้:

```bash
docker build --target direct -t opd-dashboard-direct .
docker run -d --name opd-dashboard --restart unless-stopped \
  -p 5900:8080 --env-file .env -e PORT=8080 -e OPD_CHROME_NO_SANDBOX=1 \
  --add-host host.docker.internal:host-gateway \
  opd-dashboard-direct
```

## 6. ตรวจสอบหลังติดตั้ง

1. ตรวจสภาพแวดล้อมและฐานข้อมูล: `docker compose exec opd python setup_check.py` — แก้ข้อ ✘ ก่อน (ดู INSTALL.md ข้อ 0)
2. เปิด **`http://<IP เครื่องนี้>:5900/check`** จากเครื่องใน LAN — หน้านี้บอกว่าคอลัมน์เวลาใน `service_time` ตรงกับที่ รพ. บันทึกไหม
   และ Data Audit ท้ายหน้า (กลุ่มแผนก รหัสนัด …) — ค่าที่หน้านั้นเสนอ (`OPD_ST_MAP`, `OPD_DEP_MAP`, `OPD_APPT_CODES`)
   ใส่ใน `.env` แล้ว `docker compose up -d` (รายละเอียด INSTALL.md ข้อ 6)
3. หน้าแรกขึ้นตัวเลขของวันนี้ · ลองปุ่ม ⬇ PNG มุมบนขวา (ได้ไฟล์ภายใน ~10 วินาที)
4. สถานะ container: `docker compose ps` ต้องเป็น `Up`
5. เทียบตัวเลขกับรายงานเดิม 1–2 สัปดาห์ ตรงแล้วตั้ง `OPD_DATA_AUDITED=1` ใน `.env` (ซ่อนแถบเตือนบนแดชบอร์ด)

## 7. แก้ปัญหา

ดู log: `docker compose logs -f opd` (กด Ctrl+C เพื่อออก)

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| `Can't connect to MySQL server on '127.0.0.1'` | ใส่ `DB_HOST` เป็น IP จริงหรือ `host.docker.internal` (ข้อ 4) |
| `Access denied for user 'opd_ro'@'172.x.x.x'` | GRANT ยังไม่ครอบ IP ที่ขึ้นใน error — GRANT ให้ IP นั้น (หรือวง `172.%` เมื่อฐานข้อมูลอยู่เครื่องเดียวกัน) |
| `Can't connect ... (timed out)` | firewall ของเครื่องฐานข้อมูลไม่เปิด 3306 ให้เครื่อง Docker |
| ปุ่มส่งออก PNG/PDF ขึ้น error · log มี `SIGABRT` | ต้องมี `OPD_CHROME_NO_SANDBOX=1` (ใน `docker-compose.yml` ตั้งไว้แล้ว · `docker run` ต้องใส่ `-e` เอง) — sandbox ของ chromium ใช้ใน container ทั่วไปไม่ได้ |
| ไฟล์ส่งออกมีกล่อง □ แทนไอคอน | image เก่าก่อนเพิ่มฟอนต์ emoji — บิลด์ใหม่ `docker compose up -d --build` |
| เวลา "วันนี้" ผิดไป 7 ชม. | ใช้ image ที่บิลด์จาก `Dockerfile` ของโปรเจกต์ (ตั้ง `TZ` ไว้แล้ว) — อย่าตั้ง `TZ` ทับใน `.env` |
| แก้ `.env` แล้วไม่เปลี่ยน | ต้อง `docker compose up -d` ใหม่ (restart เฉย ๆ ไม่อ่าน `.env` ซ้ำ) |

## 8. ไฟล์ของโรงพยาบาล (ไม่บังคับ)

ไม่ต้องบิลด์ใหม่ — เปิดบรรทัด `volumes:` ใน `docker-compose.yml` (เอา `#` ออก) แล้ววางไฟล์ไว้ข้าง `docker-compose.yml`:

| ไฟล์ | ใช้ทำอะไร |
|---|---|
| `hospital_logo.png` | โลโก้โรงพยาบาล (PNG สี่เหลี่ยมจัตุรัส) |
| `flow_layout.json` | ผัง Flow 3D ของอาคาร รพ. — เริ่มจาก `flow_layout.example.json` (INSTALL.md ข้อ 7) |

แล้ว `docker compose up -d` · ไฟล์เหล่านี้ไม่ถูกเขียนทับตอนอัปเดต

## 9. เปิดผ่าน reverse proxy / อินเทอร์เน็ต

ตั้ง proxy ไปที่ `http://127.0.0.1:5900/` ตาม INSTALL.md ข้อ 5 (sub-path ใช้ `X-Forwarded-Prefix` ได้เหมือนเดิม)

ถ้า proxy อยู่**เครื่องเดียวกับ Docker** ให้เปิดพอร์ตเฉพาะในเครื่อง เพื่อไม่ให้ใครข้าม proxy มาที่แอปตรง ๆ:

```yaml
    ports:
      - "127.0.0.1:5900:8080"
```

**อย่าเปิดพอร์ต 5900 ออกอินเทอร์เน็ตตรง ๆ** — บน Docker Desktop (Windows) แอปเห็นทุกคำขอมาจาก IP ภายในของ Docker
จึงนับคนนอกเป็น "ใน รพ." และเปิดหน้ารายเคส/HN ให้ · ถ้าผ่าน Cloudflare ตั้ง `OPD_TRUSTED_IPS` ตาม INSTALL.md ข้อ 4

## 10. อัปเดตเป็นเวอร์ชันใหม่

```bash
git pull                      # หรือแตก zip ใหม่ทับโฟลเดอร์เดิม
docker compose up -d --build
docker image prune -f         # ลบ image เก่าที่ไม่ใช้แล้ว
```

`.env`, `hospital_logo.png` และ `flow_layout.json` ไม่ถูกเขียนทับ · บิลด์ใหม่ = ได้แพตช์ความปลอดภัยล่าสุดของ Alpine ด้วย (`apk upgrade`)

หยุดแอป: `docker compose down` (ไม่ลบ `.env` หรือไฟล์ของ รพ.)
