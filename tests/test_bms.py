"""โหมด BMS Marketplace (OPD_DB_MODE=bms) — จำลอง hosxp.net/PasteJSON และ /api/sql ไม่ยิงออกจริง"""

import time

import pytest

import app as app_mod
import bms_session
import db
import deps
import flow
import queries

TUNNEL = {"A": "https://11111-ondemand-win-aaa.tunnel.hosxp.net",
          "B": "https://22222-ondemand-win-bbb.tunnel.hosxp.net"}


def paste(code, hosp="11111", url=None, db_type="MariaDB", msg=200, name="โรงพยาบาลเอ"):
    return {"MessageCode": msg, "Message": "OK", "result": {
        "user_info": {"hospital_code": hosp, "location": name, "bms_url": url or TUNNEL["A"],
                      "bms_session_code": "tok-" + code, "bms_database_type": db_type},
        "key_value": "tok-" + code, "expired_second": 36000}}


class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p


class FakeHTTP:
    """แทน requests.Session — เก็บทุก request ไว้ให้ test ตรวจ"""

    def __init__(self):
        self.sessions = {}             # session id → PasteJSON payload
        self.sql_calls = []            # (url, headers, json)
        self.sql_reply = self._reply
        self.sql_status = 200

    @staticmethod
    def _reply(url, body):
        if "from hospcode" in body["sql"]:             # ชื่อ รพ. ตามรหัสใน session
            names = {"11111": "โรงพยาบาลเอ", "22222": "โรงพยาบาลบี"}
            code = next((c for c in names if c in body["sql"]), None)
            data = [{"hospitalcode": code, "hospitalname": names[code]}] if code else []
            return {"MessageCode": 200, "data": data}
        return {"MessageCode": 200, "data": []}

    def get(self, url, params=None, timeout=None):
        assert url == bms_session.PASTE_URL and params["Action"] == "GET"
        return FakeResp(self.sessions.get(params["code"], {"MessageCode": 500, "Message": "not found"}))

    def post(self, url, params=None, headers=None, json=None, timeout=None):
        if params:
            url = url + "?" + "&".join(f"{k}={v}" for k, v in params.items())
        self.sql_calls.append((url, headers, json))
        return FakeResp(self.sql_reply(url, json), self.sql_status)


@pytest.fixture
def bms(monkeypatch):
    http = FakeHTTP()
    http.sessions["sess-aaaa-1111"] = paste("aaaa")
    http.sessions["sess-bbbb-2222"] = paste("bbbb", hosp="22222", url=TUNNEL["B"], name="โรงพยาบาลบี")
    monkeypatch.setattr(bms_session, "_http", lambda: http)
    monkeypatch.setattr(db, "MODE", "bms")
    monkeypatch.setattr(app_mod, "EXPORT_ENABLED", False)
    monkeypatch.setattr(deps, "_caches", {})
    monkeypatch.setattr(queries, "CACHE_TTL", 120)
    bms_session._sessions._data.clear()
    queries._cache._data.clear()
    flow._cache._data.clear()
    app_mod.app.config["TESTING"] = True
    return http


def test_no_session_asks_to_open_from_hosxp(bms):
    r = app_mod.app.test_client().get("/")
    assert r.status_code == 401 and "HOSxP" in r.get_data(as_text=True)
    assert not bms.sql_calls


def test_session_from_url_moves_to_cookie_and_queries_with_bearer(bms):
    c = app_mod.app.test_client()
    r = c.get("/?d1=2026-10-01&bms-session-id=sess-aaaa-1111&vn=690101080001&marketplace_token=mkt_1")
    assert r.status_code == 302
    loc = r.headers["Location"]
    assert "bms-session-id" not in loc and "marketplace_token" not in loc and "d1=2026-10-01" in loc
    cookie = r.headers["Set-Cookie"]
    assert "opd_bms_sid=sess-aaaa-1111" in cookie and "HttpOnly" in cookie
    r = c.get("/?d1=2026-10-01")
    assert r.status_code == 200 and "โรงพยาบาลเอ" in r.get_data(as_text=True)
    url, headers, body = bms.sql_calls[0]
    assert url == TUNNEL["A"] + "/api/sql"
    assert headers["Authorization"] == "Bearer tok-aaaa"            # token ทาง header เท่านั้น
    assert "tok-aaaa" not in url and body["app"] == bms_session.APP_ID
    assert all("opdconfig" not in b["sql"] for _, _, b in bms.sql_calls)  # ตารางต้องห้ามของ API


def test_values_are_escaped_into_sql(bms):
    c = app_mod.app.test_client()
    c.get("/?bms-session-id=sess-aaaa-1111")
    c.get("/cases?d1=2026-10-01&d2=2026-10-02&dep=010")
    sqls = [b["sql"] for _, _, b in bms.sql_calls]
    assert any("'2026-10-01'" in s and "'010'" in s for s in sqls)
    assert not any("%(" in s for s in sqls)


def test_two_hospitals_do_not_share_cache(bms):
    a, b = app_mod.app.test_client(), app_mod.app.test_client()
    a.get("/?bms-session-id=sess-aaaa-1111")
    b.get("/?bms-session-id=sess-bbbb-2222")
    a.get("/api/data.json?d1=2026-10-01&d2=2026-10-01")
    n = len(bms.sql_calls)
    b.get("/api/data.json?d1=2026-10-01&d2=2026-10-01")             # รพ. อื่น ช่วงเดียวกัน → ต้องยิงใหม่
    assert len(bms.sql_calls) > n
    assert {u for u, _, _ in bms.sql_calls[n:]} == {TUNNEL["B"] + "/api/sql"}
    m = len(bms.sql_calls)
    a.get("/api/data.json?d1=2026-10-01&d2=2026-10-01")             # รพ. เดิม → ใช้แคช
    assert len(bms.sql_calls) == m


def test_expired_session(bms):
    c = app_mod.app.test_client()
    assert c.get("/?bms-session-id=nope-0000-0000").status_code == 401
    c.get("/?bms-session-id=sess-aaaa-1111")
    bms.sql_status = 501                                             # token หมดอายุ
    r = c.get("/api/flow.json")
    assert r.status_code == 401 and "หมดอายุ" in r.get_data(as_text=True)
    assert bms_session._sessions.get("sess-aaaa-1111", 999) is None    # ล้าง session ทิ้งให้แลกใหม่


def test_truncated_result_is_an_error_not_a_wrong_total(bms):
    c = app_mod.app.test_client()
    c.get("/?bms-session-id=sess-aaaa-1111")
    bms.sql_reply = lambda url, body: {"MessageCode": 200, "data": [{"c": 1}], "truncated": True}
    r = c.get("/cases")
    assert r.status_code == 413 and "ช่วงวันที่สั้นลง" in r.get_data(as_text=True)


@pytest.mark.parametrize("bad_url", ["https://evil.example", "http://x.tunnel.hosxp.net",
                                     "https://hosxp.net.evil.example", "https://10.0.0.5"])
def test_session_pointing_elsewhere_is_rejected(bms, bad_url):
    """ข้อมูล session ปลอมห้ามทำให้เซิร์ฟเวอร์ยิงคำสั่ง (และ token) ไปที่อื่น"""
    bms.sessions["evil-0000-0000"] = paste("evil", url=bad_url)
    r = app_mod.app.test_client().get("/?bms-session-id=evil-0000-0000")
    assert r.status_code == 401 and not bms.sql_calls


def test_postgresql_not_supported_yet(bms):
    bms.sessions["pg-0000-0000"] = paste("pg", db_type="PostgreSQL")
    r = app_mod.app.test_client().get("/?bms-session-id=pg-0000-0000")
    assert r.status_code == 401 and "PostgreSQL" in r.get_data(as_text=True)


def test_bad_session_id_format_never_reaches_hosxp(bms):
    r = app_mod.app.test_client().get("/?bms-session-id=../../etc")
    assert r.status_code == 401


def test_export_disabled_and_hidden(bms):
    c = app_mod.app.test_client()
    c.get("/?bms-session-id=sess-aaaa-1111")
    assert c.get("/export.pdf").status_code == 404
    assert c.get("/help.pdf").status_code == 404
    assert "/export." not in c.get("/").get_data(as_text=True)


def test_drilldown_open_in_bms_mode(bms):
    c = app_mod.app.test_client()
    c.get("/?bms-session-id=sess-aaaa-1111")
    assert c.get("/cases", headers={"CF-Connecting-IP": "8.8.8.8"}).status_code == 200


def test_session_does_not_leak_to_next_request(bms):
    c = app_mod.app.test_client()
    c.get("/?bms-session-id=sess-aaaa-1111")
    c.get("/")
    r = app_mod.app.test_client().get("/manifest.webmanifest")     # ไม่มี session
    assert "โรงพยาบาลเอ" not in r.get_data(as_text=True)


def test_hospital_name_from_hospcode_not_location(bms):
    bms.sessions["sess-cccc-3333"] = paste("cccc", hosp="33333", name="server")   # location = ที่ทำงานผู้ใช้
    c = app_mod.app.test_client()
    c.get("/?bms-session-id=sess-cccc-3333")
    html = c.get("/").get_data(as_text=True)
    assert "โรงพยาบาล 33333" in html and ">server<" not in html


def test_pastejson_rejection_reason_is_shown(bms):
    bms.sessions["deny-0000-0000"] = {"MessageCode": 401, "Message": "token_missing"}
    r = app_mod.app.test_client().get("/?bms-session-id=deny-0000-0000")
    assert r.status_code == 401 and "token_missing" in r.get_data(as_text=True)


def test_healthz_needs_no_session(bms):
    assert app_mod.app.test_client().get("/healthz").status_code == 200


def test_session_repr_hides_token():
    s = bms_session.Session("id", TUNNEL["A"], "secret-token", "1", "mariadb", time.time())
    assert "secret-token" not in repr(s)


def test_shows_last_data_when_hosxp_is_closed(bms, monkeypatch):
    """ผู้ใช้ปิด HOSxP/tunnel ล่ม → แสดงข้อมูลล่าสุดพร้อมคำเตือน แทนหน้า error"""
    monkeypatch.setattr(queries, "CACHE_TTL", 1)
    c = app_mod.app.test_client()
    c.get("/?bms-session-id=sess-aaaa-1111")
    assert c.get("/?d1=2026-10-01&d2=2026-10-01").status_code == 200
    time.sleep(1.1)                                                  # แคชหมดอายุ

    def down(url, body):
        raise AssertionError("ไม่ควรถูกเรียก")

    bms.sql_reply = lambda url, body: {"MessageCode": 500, "Message": "connection refused"}
    r = c.get("/?d1=2026-10-01&d2=2026-10-01")
    assert r.status_code == 200 and "แสดงข้อมูลล่าสุดเมื่อ" in r.get_data(as_text=True)


def test_expired_session_is_not_hidden_by_stale_data(bms, monkeypatch):
    monkeypatch.setattr(queries, "CACHE_TTL", 1)
    c = app_mod.app.test_client()
    c.get("/?bms-session-id=sess-aaaa-1111")
    c.get("/?d1=2026-10-01&d2=2026-10-01")
    time.sleep(1.1)
    bms.sql_status = 501
    assert c.get("/?d1=2026-10-01&d2=2026-10-01").status_code == 401


def test_check_page_keeps_each_query_within_20_tables(bms):
    c = app_mod.app.test_client()
    c.get("/?bms-session-id=sess-aaaa-1111")
    assert c.get("/check").status_code == 200
    for _, _, body in bms.sql_calls:
        assert body["sql"].lower().count("service_time") + body["sql"].lower().count(" ovst ") <= 20


def test_marketplace_token_forwarded_in_body_not_url(bms):
    c = app_mod.app.test_client()
    c.get("/?bms-session-id=sess-aaaa-1111&marketplace_token=hxp_abc123")
    c.get("/api/flow.json")
    url, headers, body = bms.sql_calls[-1]
    assert body["marketplace-token"] == "hxp_abc123"
    assert "hxp_abc123" not in url


def test_no_marketplace_token_no_field(bms):
    c = app_mod.app.test_client()
    c.get("/?bms-session-id=sess-aaaa-1111")
    c.get("/api/flow.json")
    assert "marketplace-token" not in bms.sql_calls[-1][2]


def test_truncated_message_shows_limit(bms):
    c = app_mod.app.test_client()
    c.get("/?bms-session-id=sess-aaaa-1111")
    bms.sql_reply = lambda url, body: {"MessageCode": 200, "data": [], "truncated": True,
                                       "result_limit_bytes": 1048576}
    assert "1,024 KB" in c.get("/cases").get_data(as_text=True)
