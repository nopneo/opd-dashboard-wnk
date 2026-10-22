"""ชั้นเชื่อมต่อฐานข้อมูล HOSxP

รองรับ 2 โหมด
  - direct : ต่อ MariaDB ตรง ๆ ด้วย pymysql อ่านค่าจาก .env  (ใช้บนเซิร์ฟเวอร์ production)
  - ssh    : ยิงคำสั่งผ่าน `ssh <host> mariadb hos` แล้วอ่าน TSV  (ใช้ตอน dev บนเครื่องที่ไม่มีรหัส DB)

  - bms    : ผ่าน BMS Session API ของ HOSxP (รันเป็น Add-on บน BMS Marketplace — ดู bms_session.py)

เลือกโหมดด้วย env `OPD_DB_MODE` (default: direct · ssh เมื่อตั้ง OPD_SSH_HOST และไม่มี DB_PASS)
ข้อมูลใน HOSxP เก็บเป็น tis-620 จึงต้องระบุ charset ให้ถูกทั้งสองทาง

ค่าที่มาจากผู้ใช้ (วันที่ รหัสแผนก ฯลฯ) ส่งเป็นพารามิเตอร์เสมอ: fetch("... where d = %(d1)s", {"d1": d1})
เมื่อส่งพารามิเตอร์ เครื่องหมาย % ที่เป็นตัวอักษรใน SQL ต้องเขียนเป็น %% (เช่น time_format(x, '%%H:%%i'))
"""

import os
import shlex
import subprocess
import threading
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
#: เวลาสูงสุดต่อคำสั่ง SQL (วินาที) — กัน query ค้างจนกิน worker และภาระของ DB HOSxP
QUERY_TIMEOUT = int(os.getenv("OPD_DB_TIMEOUT", "60"))

#: ปกติใช้ direct · โหมด ssh ใช้ตอนพัฒนาบนเครื่องที่ไม่มีรหัส DB (ต้องตั้ง OPD_SSH_HOST)
MODE = os.getenv("OPD_DB_MODE") or ("ssh" if SSH_HOST and not DB_PASS else "direct")


#: connection ต่อเธรด — ใช้ซ้ำทุกคำสั่งใน request เดียวกัน แล้ว app ปิดตอนจบ request (close())
_local = threading.local()


def _conn():
    import pymysql

    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        charset="tis620",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=QUERY_TIMEOUT + 5,
    )
    # ให้ MariaDB หยุด query เองเมื่อเกินเวลา (read_timeout ตัดแค่ฝั่ง client, query ยังรันต่อใน DB)
    # MySQL ไม่มีตัวแปรนี้ — ข้ามได้ ยังมี read_timeout กันอยู่
    try:
        with conn.cursor() as cur:
            cur.execute(f"set session max_statement_time = {QUERY_TIMEOUT:d}")
    except pymysql.MySQLError:
        pass
    _local.conn = conn
    return conn


def close():
    """ปิด connection ของเธรดนี้ (app เรียกตอนจบทุก request)"""
    conn = getattr(_local, "conn", None)
    _local.conn = None
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def _fetch_direct(sql, args):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall()
    except Exception:
        close()                 # connection อาจเสีย/หมดเวลา — คำสั่งถัดไปเปิดใหม่
        raise


def _bind(sql, args):
    """แทนพารามิเตอร์ลง SQL สำหรับโหมด ssh — escape แบบเดียวกับ pymysql"""
    if args is None:
        return sql
    from pymysql.converters import escape_item

    if isinstance(args, dict):
        return sql % {k: escape_item(v, "utf8") for k, v in args.items()}
    return sql % tuple(escape_item(v, "utf8") for v in args)


def _fetch_ssh(sql, args):
    """รันผ่าน ssh แล้วแปลง TSV กลับเป็น list[dict]

    mariadb client ส่ง \\t \\n \\\\ แบบ escape มาใน batch mode จึงต้อง unescape กลับ
    """
    sql = _bind(sql, args)
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


def _fetch_bms(sql, args):
    import bms_session

    # แทนค่าพารามิเตอร์ด้วย escape ของ pymysql (โหมดนี้รับเฉพาะ HOSxP ที่เป็น MySQL/MariaDB)
    return bms_session.run_sql(_bind(sql, args))


def tenant():
    """รหัสโรงพยาบาลของ request นี้ — ใช้แยกแคชเมื่อหลาย รพ. ใช้แอปเดียวกัน (โหมด bms) · โหมดอื่นคืนสตริงว่าง"""
    if MODE != "bms":
        return ""
    import bms_session

    sess = bms_session.current.get()
    return sess.hospital_code if sess else ""


def fetch(sql, args=None):
    if MODE == "bms":
        rows = _fetch_bms(sql, args)
    elif MODE == "direct":
        rows = _fetch_direct(sql, args)
    else:
        rows = _fetch_ssh(sql, args)
    return [{k: _clean(v) for k, v in r.items()} for r in rows]


def fetch_one(sql, args=None):
    rows = fetch(sql, args)
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
