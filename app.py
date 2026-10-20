"""OPD Dashboard — แดชบอร์ดบริหารจัดการผู้ป่วยนอก สำหรับโรงพยาบาลที่ใช้ HOSxP

รันเอง:      python app.py            → http://127.0.0.1:5900/
production:  gunicorn -b 0.0.0.0:5900 app:app   (ออกผ่าน sub-path /opd/)
"""

import ipaddress
import json
import os
import re
import tempfile
import threading
import urllib.parse
from datetime import date, timedelta
from io import BytesIO

from flask import (Flask, jsonify, render_template, request, send_file,
                   url_for)

import charts
import check
import deps
import flow
import queries
import render
import stmap


class PrefixMiddleware:
    """รองรับการวางแอปไว้หลัง reverse proxy แบบ sub-path

    อ่าน X-Forwarded-Prefix มาตั้ง SCRIPT_NAME และ X-Forwarded-Proto มาตั้ง url_scheme
    ทำให้ url_for() สร้างลิงก์ /opd/... ถูก และยังเข้าตรง :5900 บน LAN ได้เหมือนเดิม
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        prefix = environ.get("HTTP_X_FORWARDED_PREFIX", "")
        if prefix:
            environ["SCRIPT_NAME"] = prefix.rstrip("/")
            path = environ.get("PATH_INFO", "")
            if path.startswith(prefix):
                environ["PATH_INFO"] = path[len(prefix):] or "/"
        proto = environ.get("HTTP_X_FORWARDED_PROTO")
        if proto:
            environ["wsgi.url_scheme"] = proto
        return self.wsgi_app(environ, start_response)


app = Flask(__name__)
app.wsgi_app = PrefixMiddleware(app.wsgi_app)
app.jinja_env.globals.update(smooth_path=charts.smooth_path, nice_max=charts.nice_max)
#: เวอร์ชันของแอป — แสดงที่ท้ายหน้าและคู่มือ (ประวัติการแก้ไขอยู่ใน CHANGELOG.md)
VERSION = "1.2.1"
#: ผู้พัฒนา — แสดงท้ายทุกหน้าและในคู่มือ (ทุกโรงพยาบาลที่ติดตั้ง) แก้ทับได้ด้วย env OPD_DEV_CONTACT
DEV_CONTACT = "นายเผด็จชัย สิงหล โรงพยาบาลวังน้ำเขียว โทร 086-257-4817"
#: เปลี่ยนเลขนี้ทุกครั้งที่เปลี่ยนไอคอน — บังคับ Safari/Chrome โหลดไอคอนหน้าจอโฮมใหม่
ICON_VERSION = "3"

_HERE = os.path.dirname(os.path.abspath(__file__))


@app.context_processor
def _branding():
    """ชื่อ/โลโก้โรงพยาบาลของแต่ละที่ติดตั้ง — ไม่ผูกกับโรงพยาบาลใดโรงพยาบาลหนึ่ง

    ชื่อ: env OPD_HOSPITAL_NAME หรืออ่านจาก opdconfig ของ HOSxP
    โลโก้: วางไฟล์ static/img/hospital_logo.png (ถ้าไม่มีใช้โลโก้กลาง static/img/logo.png)
    """
    custom = os.path.exists(os.path.join(_HERE, "static", "img", "hospital_logo.png"))
    return {
        "hospital": deps.hospital_name(),
        "logo_url": url_for("static", filename="img/hospital_logo.png" if custom else "img/logo.png")
                    + "?v=" + ICON_VERSION,
        "version": VERSION,
        "icon_v": ICON_VERSION,
        "contact": os.getenv("OPD_CONTACT", "ผู้ดูแลระบบสารสนเทศของโรงพยาบาล"),
        "dev_contact": os.getenv("OPD_DEV_CONTACT", DEV_CONTACT),
    }


app.jinja_env.filters["n"] = lambda v: f"{v:,}" if isinstance(v, (int, float)) else v


#: พารามิเตอร์ของแอปเอง — ตัวอื่นที่เข้ามา (เช่นที่ HOSxP Marketplace ส่งตอนเปิด add-on) จะถูกบันทึก
_KNOWN_ARGS = {"d1", "d2", "print", "d", "t", "tv", "dep", "step", "over"}
#: header มาตรฐานของเบราว์เซอร์/proxy — ไม่ต้องบันทึก
_STD_HEADERS = {"host", "user-agent", "accept", "accept-language", "accept-encoding", "connection",
                "cookie", "referer", "upgrade-insecure-requests", "cache-control", "pragma",
                "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest", "sec-fetch-user", "priority",
                "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform", "if-none-match",
                "if-modified-since", "x-forwarded-for", "x-forwarded-host", "x-forwarded-server",
                "x-forwarded-proto", "x-forwarded-prefix", "cf-ray", "cf-connecting-ip",
                "cf-ipcountry", "cf-visitor", "cdn-loop", "x-real-ip", "content-length", "content-type",
                "origin", "dnt", "purpose", "sec-purpose", "range", "if-range"}


@app.before_request
def _log_unknown_params():
    """บันทึก "ชื่อ" พารามิเตอร์/header/cookie ที่แอปไม่รู้จัก เพื่อดูว่า HOSxP ส่งอะไรมาตอนเปิด add-on

    บันทึกเฉพาะชื่อและความยาวของค่า — ไม่บันทึกค่าเด็ดขาด (อาจเป็น session id / token)
    ปิดได้ด้วย env OPD_LOG_PARAMS=0
    """
    if os.getenv("OPD_LOG_PARAMS", "1") == "0" or request.path.startswith("/static/"):
        return
    args = {k: len(v) for k, v in request.args.items() if k not in _KNOWN_ARGS}
    form = {k: len(v) for k, v in request.form.items()} if request.method == "POST" else {}
    heads = {k: len(v) for k, v in request.headers.items() if k.lower() not in _STD_HEADERS}
    cookies = {k: len(v) for k, v in request.cookies.items()}
    if args or form or heads or cookies:
        app.logger.warning("addon-params %s %s args=%s form=%s headers=%s cookies=%s",
                           request.method, request.path, args, form, heads, cookies)


def _parse_date(v):
    """แปลงวันที่ที่ผู้ใช้กรอกเป็น date — คืน None ถ้าอ่านไม่ได้

    รับ YYYY-MM-DD (ช่องเลือกวันที่ของเบราว์เซอร์) และ วว/ดด/ปปปป หรือ วว-ดด-ปปปป
    (เบราว์เซอร์ในโปรแกรม HOSxP ไม่มีปฏิทินให้เลือก ผู้ใช้จึงพิมพ์เอง มักเป็นปี พ.ศ.)
    """
    v = (v or "").strip()
    if not v:
        return None
    try:
        if "/" in v or (v.count("-") == 2 and len(v.split("-")[0]) <= 2):
            dd, mm, yy = (int(x) for x in v.replace("-", "/").split("/"))
            if yy < 100:
                yy += 2500 if yy >= 60 else 2000     # 69 → 2569 (พ.ศ.), 26 → 2026
        else:
            yy, mm, dd = (int(x) for x in v.split("-"))
        if yy > 2400:
            yy -= 543                                  # พ.ศ. → ค.ศ.
        return date(yy, mm, dd)
    except (TypeError, ValueError):
        return None


def _iso(v, default):
    """วันที่สำหรับต่อเข้า SQL — ผ่าน date() แล้วเท่านั้น จึงปลอดภัยจากการแทรกคำสั่ง"""
    d = _parse_date(v)
    return d.isoformat() if d else default


def _params():
    """(d1, d2, ข้อความเตือน) — กรอกผิดรูปแบบจะแจ้งเตือน ไม่เงียบแล้วกลับไปวันนี้"""
    today = date.today().isoformat()
    warn = []
    out = []
    for key in ("d1", "d2"):
        raw = request.args.get(key)
        d = _parse_date(raw)
        if raw and not d:
            warn.append(f"อ่านวันที่ “{raw}” ไม่ได้ (ใช้รูปแบบ วว/ดด/ปปปป เช่น 16/10/2569)")
        out.append(d.isoformat() if d else today)
    d1, d2 = out
    if d1 > today or d2 > today:
        warn.append("เลือกวันในอนาคต — แสดงถึงวันนี้แทน")
        d1, d2 = min(d1, today), min(d2, today)
    if d1 > d2:
        d1, d2 = d2, d1
    return d1, d2, " · ".join(warn)


@app.route("/")
def dashboard():
    d1, d2, warn = _params()
    t = date.today()
    first = t.replace(day=1)
    prev_end = first - timedelta(days=1)
    ranges = [("วันนี้", t, t), ("7 วันล่าสุด", t - timedelta(days=6), t),
              ("เดือนนี้", first, t), ("เดือนก่อน", prev_end.replace(day=1), prev_end)]
    ranges = [(lbl, a.isoformat(), b.isoformat()) for lbl, a, b in ranges]
    return render_template("dashboard.html", d=queries.build(d1, d2), warn=warn, ranges=ranges,
                           print_mode=request.args.get("print") == "1")


def _hn_allowed():
    """แสดง HN ในหน้ารายเคสได้เฉพาะเครื่องในเครือข่ายภายในที่ต่อเข้าแอปตรง ๆ

    ผ่าน reverse proxy (มี X-Forwarded-For) = อาจมาจากอินเทอร์เน็ต → ไม่แสดง
    ตั้ง env OPD_SHOW_HN=off เพื่อปิดทุกกรณี (ค่าเริ่มต้น lan)
    """
    if os.getenv("OPD_SHOW_HN", "lan").lower() != "lan":
        return False
    if request.headers.get("X-Forwarded-For") or request.headers.get("X-Forwarded-Prefix"):
        return False
    try:
        return ipaddress.ip_address(request.remote_addr or "").is_private
    except ValueError:
        return False


@app.route("/cases")
def cases_page():
    """ดูรายเคส (drill down) จากบล็อกบนแดชบอร์ด"""
    d1, d2, warn = _params()
    dep = request.args.get("dep", "")
    dep = dep if re.fullmatch(r"[0-9A-Za-z]{1,10}", dep) else ""
    try:
        step = int(request.args.get("step", ""))
        step = step if 0 <= step < len(queries.SLA) else None
    except ValueError:
        step = None
    over = request.args.get("over") == "1"
    hn = _hn_allowed()
    data = queries.cases(d1, d2, dep or None, step, over, with_hn=hn)
    depts = queries.build(d1, d2)["dept_table"]
    return render_template("cases.html", d1=d1, d2=d2, dep=dep, step=step, over=over, warn=warn,
                           c=data, depts=depts, show_hn=hn, t_total=queries.TARGET_TOTAL,
                           period=queries._thai_range(d1, d2))


@app.route("/help")
def help_page():
    """คู่มือการใช้งาน + นิยามตัวชี้วัด + ช่องทางติดต่อ"""
    return render_template("help.html", sla=queries.SLA, t=queries, st_steps=stmap.STEPS,
                           print_mode=request.args.get("print") == "1")


@app.route("/help.pdf")
def help_pdf():
    """คู่มือฉบับพิมพ์ (A4) — เรนเดอร์หน้า /help ด้วย chromium headless"""
    url = f"http://127.0.0.1:{os.getenv('PORT', '5900')}/help?print=1"
    if not _render_lock.acquire(timeout=90):
        return {"error": "มีงานส่งออกอื่นค้างอยู่ ลองใหม่อีกครั้ง"}, 503
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "manual.pdf")
            render.to_pdf(render.find_browser(), url, out)
            blob = open(out, "rb").read()
        return send_file(BytesIO(blob), mimetype="application/pdf", as_attachment=True,
                         download_name=f"OPD_Dashboard_manual_{VERSION}.pdf")
    except (Exception, SystemExit) as e:        # find_browser() ไม่พบ chromium = SystemExit
        app.logger.exception("help pdf failed")
        return {"error": f"สร้าง PDF ไม่สำเร็จ: {type(e).__name__}"}, 500
    finally:
        _render_lock.release()


@app.route("/check")
def check_page():
    """ตรวจความพร้อมของข้อมูล — คอลัมน์เวลาใน service_time มีข้อมูลแค่ไหน (ค่าเริ่มต้น 7 วันล่าสุด)"""
    d1, d2, warn = _params()
    if not request.args.get("d1"):
        d1 = (date.fromisoformat(d2) - timedelta(days=6)).isoformat()
    return render_template("check.html", c=check.run(d1, d2), d1=d1, d2=d2, warn=warn,
                           period=queries._thai_range(d1, d2))


@app.route("/api/data.json")
def api_data():
    d1, d2, _ = _params()
    return jsonify(queries.build(d1, d2))


def _flow_layout():
    """ผังอาคารของโรงพยาบาลเอง (flow_layout.json หรือไฟล์ตาม env OPD_FLOW_LAYOUT)

    ไม่มีไฟล์ = ใช้ผังตัวอย่างใน static/flow.js · ไฟล์เสีย = บันทึก log แล้วใช้ผังตัวอย่าง
    อ่านใหม่ทุกครั้งที่เปิดหน้า จึงแก้ไฟล์แล้วกดรีเฟรชเห็นผลทันที ไม่ต้องรีสตาร์ต
    """
    path = os.getenv("OPD_FLOW_LAYOUT") or os.path.join(_HERE, "flow_layout.json")
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
        if not isinstance(j.get("areas"), dict) or not j["areas"]:
            raise ValueError("ไม่มีหัวข้อ areas")
        for k, a in j["areas"].items():
            if not (isinstance(a.get("r"), list) and len(a["r"]) == 4):
                raise ValueError(f"areas.{k}.r ต้องเป็น [ซ้าย, บน, ขวา, ล่าง]")
        return j, None
    except (OSError, ValueError) as e:
        app.logger.warning("flow layout ignored: %s", e)
        return None, f"อ่าน {os.path.basename(path)} ไม่ได้ ({e}) — ใช้ผังตัวอย่างแทน"


@app.route("/flow")
def flow_page():
    """ผังผู้ป่วย OPD แบบ 2.5D — เล่นย้อนหลังรายวัน หรือโหมดสด (วันนี้)"""
    today = date.today().isoformat()
    layout, layout_err = _flow_layout()
    return render_template("flow.html", d=_iso(request.args.get("d"), today), today=today,
                           layout=layout, layout_err=layout_err)


@app.route("/api/flow.json")
def api_flow():
    today = date.today().isoformat()
    d = _iso(request.args.get("d"), today)
    if d > today:
        return {"error": "ยังไม่มีข้อมูลของวันในอนาคต"}, 400
    return jsonify(flow.build(d))


# เรนเดอร์ทีละงานเท่านั้น — chromium กินแรมสูง และมี gunicorn แค่ 3 worker
_render_lock = threading.Lock()

MIME = {"png": "image/png", "jpg": "image/jpeg", "pdf": "application/pdf"}


@app.route("/export.<fmt>")
def export(fmt):
    """ส่งออกหน้าแดชบอร์ดเป็นไฟล์ PNG / JPG / PDF ด้วย chromium headless

    เรียกหน้าเดิมของตัวเองด้วย ?print=1 (ซ่อนแถบเครื่องมือ) แล้วถ่ายภาพ
    """
    if fmt not in MIME:
        return {"error": "รองรับเฉพาะ png, jpg, pdf"}, 404

    d1, d2, _ = _params()
    qs = urllib.parse.urlencode({"d1": d1, "d2": d2, "print": "1"})
    url = f"http://127.0.0.1:{os.getenv('PORT', '5900')}/?{qs}"

    name = f"opd_{d1}_{d2}.{fmt}"
    if not _render_lock.acquire(timeout=90):
        return {"error": "มีงานส่งออกอื่นค้างอยู่ ลองใหม่อีกครั้ง"}, 503
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, name)
            render.render_to(fmt, url, out)
            # อ่านใส่หน่วยความจำก่อนออกจาก with — send_file ยังถือ handle ค้างไว้
            # ทำให้ลบโฟลเดอร์ชั่วคราวไม่ได้ (PermissionError บน Windows)
            blob = open(out, "rb").read()
        return send_file(BytesIO(blob), mimetype=MIME[fmt],
                         as_attachment=True, download_name=name)
    except Exception as e:                      # chromium ไม่มี/ตาย/หมดเวลา
        app.logger.exception("export failed")
        return {"error": f"ส่งออกไม่สำเร็จ: {type(e).__name__}"}, 500
    finally:
        _render_lock.release()


@app.route("/manifest.webmanifest")
def manifest():
    """ให้เพิ่มลงหน้าจอโฮมมือถือแล้วเปิดเต็มจอพร้อมไอคอนแอป

    ใช้ url_for ทุกเส้นทาง เพื่อให้ได้ /opd/... ถูกต้องเมื่ออยู่หลัง reverse proxy
    """
    ic = lambda f: url_for("static", filename="icon/" + f) + "?v=" + ICON_VERSION
    resp = jsonify({
        "name": "OPD Dashboard — " + deps.hospital_name(),
        "short_name": "OPD Dashboard",
        "description": "แดชบอร์ดบริหารจัดการผู้ป่วยนอก",
        "start_url": url_for("dashboard"),
        "scope": url_for("dashboard"),
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#eef2f8",
        "theme_color": "#0f2a5c",
        "icons": [
            {"src": ic("icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": ic("icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": ic("icon-192-maskable.png"), "sizes": "192x192",
             "type": "image/png", "purpose": "maskable"},
            {"src": ic("icon-512-maskable.png"), "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    })
    resp.mimetype = "application/manifest+json"
    return resp


@app.route("/healthz")
def healthz():
    return {"status": "ok"}


if __name__ == "__main__":
    # render.py สตาร์ตแอปด้วย FLASK_DEBUG=0 — ถ้าเปิด reloader ไว้ โปรเซสลูกจะค้างหลัง render.py ปิดตัวแม่
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5900")),
            debug=os.getenv("FLASK_DEBUG", "1") != "0")
