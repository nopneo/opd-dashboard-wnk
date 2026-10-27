"""Data Audit (หน้า /check), แถบเตือนบนแดชบอร์ด และ setup_check.py — ไม่ต่อฐานข้อมูลจริง"""

import pytest

import app as app_mod
import check
import queries
import setup_check


def _fake(monkeypatch, rows_by_key, one=None):
    """fetch ปลอม: คืนแถวตามคำแรกที่พบใน SQL"""
    def fetch(sql, args=None):
        for key, rows in rows_by_key.items():
            if key in sql:
                return rows
        return []
    monkeypatch.setattr(check, "fetch", fetch)
    monkeypatch.setattr(check, "fetch_one", lambda sql, args=None: (one or {}))


def test_dep_audit_flags_ungrouped_department(monkeypatch):
    _fake(monkeypatch, {"group by o.main_dep": [
        {"dep": "010", "n": 90}, {"dep": "999", "n": 3}, {"dep": "036", "n": 5}, {"dep": "077", "n": 2}]})
    r = check._dep_audit("2026-10-01", "2026-10-07", 100)
    by = {x["code"]: x for x in r["rows"]}
    assert by["010"]["group"] == "R2" and not by["010"]["warn"]
    assert by["036"]["warn"] and by["036"]["group"] is None      # ไม่เข้ากลุ่ม ≥ 1% → เตือน
    assert not by["999"]["warn"] and "กลับบ้าน" in by["999"]["label"]
    assert [x["code"] for x in r["rows"]][:1] == ["010"]       # เรียงตามจำนวน visit


def test_appt_code_suggests_other_codes_named_appointment(monkeypatch):
    _fake(monkeypatch, {"ovstist": [
        {"code": "01", "name": "มาเอง", "n": 60}, {"code": "02", "name": "นัดมา", "n": 30},
        {"code": "08", "name": "นัดตรวจ Lab", "n": 10}]})
    appt = check._code_audit("2026-10-01", "2026-10-07", 100)[0]
    assert appt["status"] == "warn" and appt["fix"] == "OPD_APPT_CODES=02,08"


def test_appt_code_missing_is_bad(monkeypatch):
    _fake(monkeypatch, {"ovstist": [{"code": "01", "name": "มาเอง", "n": 100}]})
    appt = check._code_audit("2026-10-01", "2026-10-07", 100)[0]
    assert appt["status"] == "bad" and "OPD_APPT_CODES" in appt["fix"]


def test_appt_codes_env_reaches_sql(monkeypatch, fake_db):
    monkeypatch.setattr(queries, "APPT_CODES", ["02", "08"])
    queries.hourly("2026-10-01", "2026-10-07", 7)
    bound = fake_db[-1][2]
    assert "('02','08')" in bound.replace(" ", "")


def test_audit_survives_missing_tables(monkeypatch):
    def boom(sql, args=None):
        raise RuntimeError("no table")
    monkeypatch.setattr(check, "fetch", boom)
    monkeypatch.setattr(check, "fetch_one", boom)
    a = check.audit("2026-10-01", "2026-10-07", 0)
    assert a["deps"]["error"] == "RuntimeError" and isinstance(a["codes"], list)


@pytest.fixture
def client(fake_db):
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


def test_dashboard_shows_audit_bar_until_audited(client, monkeypatch):
    assert "audit-bar" in client.get("/").get_data(as_text=True)
    assert "audit-bar" not in client.get("/?print=1").get_data(as_text=True)    # ไม่ติดไปในไฟล์ส่งออก
    monkeypatch.setenv("OPD_DATA_AUDITED", "1")
    assert "audit-bar" not in client.get("/").get_data(as_text=True)


def test_check_page_has_audit_section(client):
    html = client.get("/check").get_data(as_text=True)
    assert 'id="audit"' in html and "audit-sum" in html


@pytest.mark.parametrize("lines, risky", [
    (["GRANT USAGE ON *.* TO `opd_ro`@`%`", "GRANT SELECT ON `hos`.* TO `opd_ro`@`%`"], []),
    (["GRANT SELECT (hn, vn), SHOW VIEW ON `hos`.* TO `x`@`%`"], []),
    (["GRANT SELECT, INSERT, UPDATE ON `hos`.* TO `x`@`%`"], ["INSERT", "UPDATE"]),
    (["GRANT ALL PRIVILEGES ON *.* TO `root`@`localhost` WITH GRANT OPTION"], ["ALL PRIVILEGES", "GRANT OPTION"]),
])
def test_setup_check_flags_write_privileges(lines, risky):
    assert setup_check.risky_privs(lines) == risky


def test_setup_check_ignores_write_privileges_on_other_databases():
    lines = ["GRANT SELECT ON `hos`.* TO `nop`@`30.25.1.%`",
             "GRANT SELECT, INSERT, UPDATE, DELETE ON `test`.* TO `nop`@`30.25.1.%`"]
    assert setup_check.risky_privs(lines, "hos") == []
    assert setup_check.risky_privs(lines, "test") == ["DELETE", "INSERT", "UPDATE"]
    assert setup_check.risky_privs(["GRANT INSERT ON *.* TO `x`@`%`"], "hos") == ["INSERT"]
