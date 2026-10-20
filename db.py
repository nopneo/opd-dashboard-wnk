"""ชั้นเชื่อมต่อฐานข้อมูล HOSxP

รองรับ 2 โหมด
  - direct : ต่อ MariaDB ตรง ๆ ด้วย pymysql อ่านค่าจาก .env  (ใช้บนเซิร์ฟเวอร์ production)
  - ssh    : ยิงคำสั่งผ่าน `ssh <host> mariadb hos` แล้วอ่าน TSV  (ใช้ตอน dev บนเครื่องที่ไม่มีรหัส DB)

เลือกโหมดด้วย env `OPD_DB_MODE` (default: direct · ssh เมื่อตั้ง OPD_SSH_HOST และไม่มี DB_PASS)
ข้อมูลใน HOSxP เก็บเป็น tis-620 จึงต้องระบุ charset ให้ถูกทั้งสองทาง
"""

import os
import shlex
import subprocess
from decimal import Decimal

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "hos")
DB_USER = os.getenv("DB_USER", "")
DB_PASS = os.getenv("DB_PASS", "")
SSH_HOST = os.getenv("OPD_SSH_HOST", "")

#: ปกติใช้ direct · โหมด ssh ใช้ตอนพัฒนาบนเครื่องที่ไม่มีรหัส DB (ต้องตั้ง OPD_SSH_HOST)
MODE = os.getenv("OPD_DB_MODE") or ("ssh" if SSH_HOST and not DB_PASS else "direct")


def _fetch_direct(sql):
    import pymysql

    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        charset="tis620",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()
    finally:
        conn.close()


def _fetch_ssh(sql):
    """รันผ่าน ssh แล้วแปลง TSV กลับเป็น list[dict]

    mariadb client ส่ง \\t \\n \\\\ แบบ escape มาใน batch mode จึงต้อง unescape กลับ
    """
    # ssh รวม argv เป็นสตริงเดียวแล้วให้ remote shell ตีความ จึงต้อง quote ให้เอง
    remote = (
        "mariadb --default-character-set=tis620 --batch --raw "
        f"{shlex.quote(DB_NAME)} -e {shlex.quote(' '.join(sql.split()))}"
    )
    # stdin=DEVNULL: ssh ของ Windows ที่ไม่มี console (รันใต้ dev server) จะค้างรอ stdin
    # BatchMode: ห้ามถามรหัส/host key — ล้มทันทีดีกว่าค้างทั้ง request
    proc = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                           SSH_HOST, remote],
                          capture_output=True, stdin=subprocess.DEVNULL, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))

    text = proc.stdout.decode("tis-620", "replace")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return []
    header = lines[0].split("\t")
    rows = []
    for ln in lines[1:]:
        cells = ln.split("\t")
        row = {}
        for k, v in zip(header, cells):
            row[k] = None if v == "NULL" else v
        rows.append(row)
    return rows


def fetch(sql):
    rows = _fetch_direct(sql) if MODE == "direct" else _fetch_ssh(sql)
    return [{k: _clean(v) for k, v in r.items()} for r in rows]


def fetch_one(sql):
    rows = fetch(sql)
    return rows[0] if rows else {}


def _clean(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


def num(v, default=0):
    """แปลงค่าที่ได้จาก DB (อาจเป็น str จากโหมด ssh) ให้เป็นตัวเลขเสมอ"""
    if v is None or v == "":
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return int(f) if f == int(f) else f
