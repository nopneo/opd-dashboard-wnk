# ติดตั้ง OPD Dashboard สำหรับโรงพยาบาลที่ใช้ HOSxP

แอปนี้**ติดตั้งบนเซิร์ฟเวอร์ของโรงพยาบาลเอง** แล้วอ่านฐานข้อมูล HOSxP ของโรงพยาบาลนั้นโดยตรง
ไม่มี endpoint กลาง ไม่ส่งข้อมูลออกนอกโรงพยาบาล — endpoint ของแต่ละที่คือ `http://<เซิร์ฟเวอร์ของ รพ.>:5900/`

ชื่อโรงพยาบาลอ่านจาก `opdconfig` และจัดกลุ่มแผนกจากชื่อใน `kskdepartment` อัตโนมัติ ไม่ต้องแก้โค้ด

**ในชุดติดตั้ง:** โค้ดแอป · `INSTALL.md` (ไฟล์นี้) · `OPD_Dashboard_manual.pdf` (คู่มือผู้ใช้ฉบับพิมพ์ ฉบับล่าสุดดาวน์โหลดได้จากปุ่ม ⬇ PDF ในหน้าคู่มือ)
· `flow_layout.example.json` (ผังอาคารตัวอย่างของ Flow 3D) · `CHANGELOG.md`
· `Dockerfile`, `docker-compose.yml`, `INSTALL_DOCKER.md` (ติดตั้งด้วย Docker)

**ขั้นตอนโดยย่อ:** ติดตั้ง (ข้อ 2 หรือ 3) → ใส่ค่าฐานข้อมูลใน `.env` → เปิดหน้า **`/check`** ตรวจข้อมูล (ข้อ 6)
→ ตั้ง `OPD_ST_MAP` ถ้าหน้านั้นแจ้ง → (ถ้าต้องการ) ปรับผัง Flow 3D (ข้อ 7)

## 1. สิ่งที่ต้องมี

| รายการ | หมายเหตุ |
|---|---|
| เครื่องเซิร์ฟเวอร์ในเครือข่าย รพ. | Linux (แนะนำ) หรือ Windows · RAM 2 GB ขึ้นไป |
| Python 3.9 ขึ้นไป | `python3 --version` |
| บัญชีฐานข้อมูล HOSxP แบบ**อ่านอย่างเดียว** | MariaDB/MySQL ของ HOSxP (ฐาน `hos`) |
| Google Chrome / Chromium | เฉพาะถ้าต้องการปุ่มส่งออก JPG/PNG/PDF (Linux: `chromium-headless` + ฟอนต์ `google-noto-emoji-color-fonts`) |

สร้างบัญชีอ่านอย่างเดียว (ทำโดยผู้ดูแลฐานข้อมูล — เปลี่ยน IP และรหัสผ่านเอง):

```sql
CREATE USER 'opd_ro'@'<IP เซิร์ฟเวอร์แอป>' IDENTIFIED BY '<รหัสผ่าน>';
GRANT SELECT ON hos.* TO 'opd_ro'@'<IP เซิร์ฟเวอร์แอป>';
```

## 2. ติดตั้งบน Linux

> **มี Docker อยู่แล้ว?** ข้ามข้อ 2–3 ไปใช้ [INSTALL_DOCKER.md](INSTALL_DOCKER.md) — ไม่ต้องลง Python / Chromium เอง

```bash
sudo unzip opd_dashboard-1.3.2.zip -d /opt && cd /opt/opd_dashboard
sudo useradd --system --home-dir /opt/opd_dashboard --shell /sbin/nologin opd   # ไม่รันแอปด้วย root
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
sudo cp .env.example .env
sudo nano .env       # ใส่ DB_HOST / DB_USER / DB_PASS ของ รพ.
sudo chown -R opd:opd /opt/opd_dashboard && sudo chmod 600 .env
sudo -u opd .venv/bin/gunicorn -w 3 -t 120 -b 0.0.0.0:5900 app:app     # ทดสอบ แล้วเปิด http://<IP>:5900/
```

รันเป็น service (systemd) — `/etc/systemd/system/opd-dashboard.service`:

```ini
[Unit]
Description=OPD Dashboard
After=network.target

[Service]
User=opd
Group=opd
WorkingDirectory=/opt/opd_dashboard
ExecStart=/opt/opd_dashboard/.venv/bin/gunicorn -w 3 -t 120 -b 0.0.0.0:5900 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now opd-dashboard
```

**ไม่รันด้วย root** — ถ้าแอปหรือ chromium (ปุ่มส่งออก) มีช่องโหว่ ผู้โจมตีจะได้แค่สิทธิ์ของ user `opd`
และเมื่อไม่ใช่ root chromium จะเปิด sandbox ได้ (ถ้าส่งออกไม่ได้เพราะเครื่องปิด user namespace ไว้ ให้ใส่
`OPD_CHROME_NO_SANDBOX=1` ใน `.env`) · ที่ติดตั้งไว้แล้วแบบ root ย้ายได้ด้วย:

```bash
sudo useradd --system --home-dir /opt/opd_dashboard --shell /sbin/nologin opd
sudo chown -R opd:opd /opt/opd_dashboard && sudo chmod 600 /opt/opd_dashboard/.env
sudo systemctl edit --full opd-dashboard     # เพิ่ม User=opd และ Group=opd ใต้ [Service]
sudo systemctl restart opd-dashboard
```

## 3. ติดตั้งบน Windows

```bat
cd C:\opd_dashboard
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      &REM แก้ค่า DB_ ใน .env ด้วย Notepad
.venv\Scripts\waitress-serve --listen=0.0.0.0:5900 app:app
```

ให้เปิดเองทุกครั้งที่บูตเครื่องด้วย Task Scheduler (At startup) หรือ NSSM

## 4. ตั้งค่า (.env)

| ค่า | ความหมาย |
|---|---|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS` | ฐานข้อมูล HOSxP (บัญชีอ่านอย่างเดียว) |
| `PORT` | พอร์ตของแอป (ค่าเริ่มต้น 5900) |
| `OPD_HOSPITAL_NAME` | ชื่อโรงพยาบาล ถ้าไม่ใส่อ่านจาก `opdconfig` |
| `OPD_CONTACT`, `OPD_DEV_CONTACT` | ช่องทางติดต่อที่แสดงท้ายทุกหน้า เช่น `งานสารสนเทศ โทร 1234` |
| `OPD_ST_MAP` | คอลัมน์ของ `service_time` ที่แต่ละขั้นอ่าน เมื่อ รพ. กดเวลาลงคอลัมน์อื่น เช่น `screen:service1,screen_end:service2` (ดูข้อ 6) |
| `OPD_FLOW_LAYOUT` | ที่อยู่ไฟล์ผัง Flow 3D (ค่าเริ่มต้น `flow_layout.json` ในโฟลเดอร์แอป · ดูข้อ 7) |
| `OPD_DEP_MAP` | กำหนดกลุ่มแผนกเอง เช่น `011=ER,040=TELE` (กลุ่ม: REG SCR NCD LAB DRW R1–R5 TELE ARI ER DENT SPEC MH PT TTM RX CASH ADMIN) |
| `OPD_TARGET_TOTAL`, `OPD_TARGET_PEAK`, `OPD_TARGET_LAB_TAT` | เป้าหมาย |
| `OPD_SHOW_HN` | `lan` (ค่าเริ่มต้น) แสดง HN ในหน้ารายเคสเฉพาะเครื่องในเครือข่ายที่ต่อตรง · `off` ไม่แสดงเลย |
| `OPD_FLOW_REMOTE_DEPS` | แผนกที่ผู้ป่วยไม่ได้อยู่ใน รพ. (ไม่วาดในผัง Flow 3D) ค่าเริ่มต้น = แผนก Telemed · `none` = วาดทุกคน |
| `OPD_MAX_DAYS` | ช่วงวันที่ยาวสุดที่ดึงได้ต่อครั้ง (ค่าเริ่มต้น 366) — กันฐานข้อมูล HOSxP ช้าจากการดึงหลายปี |
| `OPD_DB_TIMEOUT` | เวลาสูงสุดต่อคำสั่ง SQL เป็นวินาที (ค่าเริ่มต้น 60) |
| `OPD_LOG_PARAMS` | `1` = บันทึกชื่อพารามิเตอร์ที่แอปไม่รู้จักลง log (ใช้ตรวจ add-on ของ HOSxP · ค่าเริ่มต้นปิด) |
| `OPD_PUBLIC_DRILLDOWN` | `1` = เปิดหน้าดูรายเคส (`/cases`) และตรวจข้อมูล (`/check`) ให้เข้าจากนอก LAN ได้ · ค่าเริ่มต้นเฉพาะ LAN |
| `OPD_LAN_NETS` | ช่วง IP ภายในของ รพ. ที่ไม่ใช่ 10.x / 172.16–31.x / 192.168.x (เช่น `30.25.0.0/16`) — ใช้กับเครื่องที่ต่อแอปตรง ไม่ผ่าน Cloudflare |
| `OPD_TRUSTED_IPS` | IP สาธารณะของ รพ. (คั่นด้วย `,` ใส่ CIDR ได้) — เมื่อเปิดผ่าน Cloudflare คำขอจาก IP เหล่านี้นับเป็น "ใน รพ." (เห็นรายเคส/HN) · ดูจาก header `CF-Connecting-IP` ซึ่ง Cloudflare ใส่เอง ต้องตั้ง firewall ให้เว็บรับเฉพาะ IP ของ Cloudflare ด้วย |
| `OPD_EXPORT_WAIT` | ส่งออก PNG/JPG/PDF: รอคิวได้นานสุดกี่วินาที (ค่าเริ่มต้น 0 = ไม่ว่างตอบ 503 ทันที ไม่กิน worker) |
| `OPD_EXPORT_CACHE_TTL` | เก็บไฟล์ที่ส่งออกแล้วให้คนถัดไปที่ขอช่วงเดียวกัน (วินาที, ค่าเริ่มต้น 300) |
| `OPD_CHROME_NO_SANDBOX` | `1` = ปิด sandbox ของ chromium (ค่าเริ่มต้นปิดเฉพาะเมื่อรันด้วย root / บน Windows) |

โลโก้โรงพยาบาล: วางไฟล์ PNG สี่เหลี่ยมจัตุรัสที่ `static/img/hospital_logo.png` แล้วรีสตาร์ตแอป


## 5. เปิดผ่าน reverse proxy (ทางเลือก)

ถ้าต้องการวางใต้ sub-path เช่น `https://<โดเมน รพ.>/opd/` (Apache):

```apache
ProxyPass /opd/ http://127.0.0.1:5900/
ProxyPassReverse /opd/ http://127.0.0.1:5900/
<Location /opd/> RequestHeader set X-Forwarded-Prefix /opd </Location>
```

แอปอ่าน `X-Forwarded-Prefix` สร้างลิงก์ให้ถูกเอง · เมื่อเข้าผ่าน proxy หน้ารายเคส (`/cases`) และตรวจข้อมูล (`/check`)
เปิดไม่ได้ ลิงก์จะถูกซ่อน (เปิดเฉพาะใน LAN — แม้ไม่มี HN รายการ visit ยังโยงกลับไปหาตัวผู้ป่วยได้)

**ถ้าเปิดออกอินเทอร์เน็ต ควรตั้งที่ proxy / Cloudflare เพิ่ม** (แอปทำเองไม่ได้):
- จำกัดจำนวนคำขอ (rate limit) เช่น 60 ครั้ง/นาทีต่อ IP และ 5 ครั้ง/นาทีสำหรับ `/opd/export.*`, `/opd/help.pdf`
  — แต่ละช่วงวันที่ใหม่ยิงคำสั่งไปฐานข้อมูล HOSxP ราว 20 คำสั่ง
- firewall ให้พอร์ต 5900 รับเฉพาะเครื่อง proxy และ LAN — ไม่ให้ข้าม proxy มาที่แอปตรง ๆ
- header `Strict-Transport-Security`, และ `X-Frame-Options: SAMEORIGIN` ถ้าไม่ได้เปิดผ่านกรอบของโปรแกรมอื่น

## 6. ตรวจสอบหลังติดตั้ง

- `http://<IP>:5900/healthz` ต้องได้ `{"status": "ok"}`
- หน้าแรกแสดงชื่อโรงพยาบาลของตัวเอง และตัวเลขของวันนี้
- `/help` คู่มือการใช้งาน · ท้ายหน้าแสดงเวอร์ชันและช่องทางติดต่อ
- **`/check` ตรวจความพร้อมของข้อมูล (สำคัญ)** — แต่ละโรงพยาบาลตั้งค่า HOSxP เองว่าจุดบริการไหนกดเวลาลงคอลัมน์ไหนของ
  `service_time` ถ้าไม่ตรงกับค่าเริ่มต้น ช่องเวลารอ (เช่น รอพบแพทย์) จะขึ้น “–”

  | ขั้น (ชื่อใน `OPD_ST_MAP`) | ความหมาย | คอลัมน์เริ่มต้น |
  |---|---|---|
  | `send` | ส่งตรวจ | `service3` |
  | `screen` | เริ่มซักประวัติ / คัดกรอง | `service4` |
  | `screen_end` | คัดกรองเสร็จ → ส่งพบแพทย์ | `service11` |
  | `doctor` | แพทย์เริ่มตรวจ | `service5` |
  | `doctor_end` | แพทย์ตรวจเสร็จ | `service12` |
  | `rx_in` | ใบสั่งยาถึงห้องจ่ายยา | `service6` |
  | `pay` | ชำระเงิน | `service7` |
  | `rx_out` | จ่ายยาเสร็จ | `service16` |
  | `unit_end` | จบบริการที่หน่วยเฉพาะ | `service20` |

  1. ดูตาราง 1 ในหน้า `/check` — ขั้นที่ขึ้น **แทบไม่มี** คือขั้นที่คอลัมน์ไม่ตรง
  2. ดูตาราง 3 ว่าจุดบริการนั้น (เช่น ซักประวัติ) กดเวลาลงคอลัมน์ไหน — หน้าเว็บจะเสนอบรรทัด `OPD_ST_MAP=…` ให้ถ้าพบ
  3. ตรวจกับการทำงานจริง แล้วใส่ใน `.env` เช่น `OPD_ST_MAP=screen:service1,screen_end:service2` (`none` = ไม่มีขั้นนี้)
  4. รีสตาร์ตแอป แล้วเปิด `/check` อีกครั้ง

## 7. ปรับผัง Flow 3D ให้ตรงอาคารของโรงพยาบาล (ทางเลือก)

ผังเริ่มต้นเป็นอาคารของโรงพยาบาลวังน้ำเขียว ปรับได้โดยไม่แก้โค้ด:

1. คัดลอก `flow_layout.example.json` เป็น `flow_layout.json` ในโฟลเดอร์แอป
2. เปิดภาพแผนผังอาคารด้วย Paint (มุมล่างซ้ายแสดงพิกัดพิกเซลของเมาส์) วัดว่า 1 เมตรยาวกี่พิกเซล ใส่ใน `scale`
3. ใส่พิกัด `[ซ้าย, บน, ขวา, ล่าง]` (หน่วยพิกเซลบนภาพ) ของแต่ละจุดบริการใน `areas` · พื้นอาคารใน `buildings`
   · ถนนใน `road` (ผู้ป่วยเดินมาจากปลายล่างของถนน) · ประตูใน `doors` (`main` = ประตูหลัก)
4. บันทึกแล้วรีเฟรชหน้า `/flow` — เห็นผลทันทีไม่ต้องรีสตาร์ต ถ้าไฟล์ผิดรูปแบบจะมีข้อความแจ้งท้ายหน้าและใช้ผังตัวอย่างแทน

รหัสจุดบริการใน `areas`: REG ห้องบัตร · REGER ห้องบัตรหน้า ER · SCR ซักประวัติ · NCD · LAB · LABW รอผลแล็บ ·
DRW หน้าห้องตรวจ · R1–R5 ห้องตรวจ · TELE · ARI · ER · DENT ทันตกรรม · SPEC ปฐมภูมิ · MH สุขภาพจิต · PT กายภาพ ·
TTM แผนไทย · RX รอรับยา · CASH การเงิน (จุดที่ไม่ได้ใส่จะเรียงเป็นแถวใต้ผัง)
ตัวเลือกของแต่ละจุด: `kind` สีพื้น · `counter` เคาน์เตอร์ · `room` ห้องตรวจ · `open` ไม่มีผนัง · `cap` ที่นั่งจริง · `door` · `short`

## 8. รันเป็น Add-on บน BMS Marketplace (ไม่ต้องติดตั้งที่โรงพยาบาล)

แอปรันบน BMS Developer Portal (`*.kube.bmscloud.in.th`) และอ่านข้อมูลของแต่ละ รพ. ผ่าน BMS Session API
— ไม่มีรหัสฐานข้อมูล ไม่ต่อฐานข้อมูลตรง (แอปที่ต่อฐานข้อมูลตรงต้องผ่าน Audit จาก BMS ก่อนใช้งาน)

1. BMS Developer Portal → นำเข้า Repo → สร้างแอปใหม่ (ชื่อพิมพ์เล็ก เช่น `opd-dashboard`) — ใช้ `Dockerfile`
   ของโปรเจกต์ (ตั้ง `OPD_DB_MODE=bms`, `TZ=ICT-7`, ฟังพอร์ต `$PORT` ค่าเริ่มต้น 8080)
2. Marketplace → นักพัฒนา → Add-on ของฉัน → สร้าง Add-on ประเภท **Standalone** ใส่ URL ของแอป → ส่งตรวจสอบ
3. ผู้ใช้เปิดจาก HOSxP (ต้องเข้าระบบด้วย ProviderID) — HOSxP ส่ง `?bms-session-id=` มาให้เอง

| ค่า (ไม่บังคับ) | ความหมาย |
|---|---|
| `OPD_BMS_APP` | ชื่อแอปที่ส่งไปกับทุกคำสั่ง SQL (ค่าเริ่มต้น `OPD.Dashboard`) |
| `OPD_BMS_ALLOWED_HOSTS` | ปลายทาง API ที่ยอมรับ (ค่าเริ่มต้น `.hosxp.net`) |
| `OPD_BMS_PASTE_URL` | ที่แลก session (ค่าเริ่มต้น `https://hosxp.net/phapi/PasteJSON`) |

ข้อจำกัดของโหมดนี้: ไม่มีปุ่มส่งออก PNG/JPG/PDF · HOSxP ที่ใช้ PostgreSQL ยังไม่รองรับ ·
ข้อมูลส่วนบุคคล (เช่น HN) อาจแสดงเป็น `[MASKED]` ตามนโยบายของ BMS

## 9. อัปเดตเป็นเวอร์ชันใหม่

แตก zip ใหม่ทับโฟลเดอร์เดิม (`.env`, `flow_layout.json` และโลโก้ของ รพ. ไม่ถูกเขียนทับ เพราะไม่มีในชุดติดตั้ง) แล้วรีสตาร์ต service
