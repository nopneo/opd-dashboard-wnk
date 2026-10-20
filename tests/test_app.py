from datetime import date, timedelta

import pytest

import app as app_mod
import queries


@pytest.fixture
def client(fake_db):
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


@pytest.mark.parametrize("url", [
    "/", "/?d1=01/10/2569&d2=15/10/2569", "/cases", "/cases?dep=010&step=3&over=1",
    "/check", "/help", "/flow", "/api/data.json", "/api/flow.json", "/manifest.webmanifest", "/healthz",
])
def test_pages_render_with_empty_db(client, url):
    assert client.get(url).status_code == 200


def test_every_query_is_parameterised(client, fake_db):
    """ค่าที่ผู้ใช้กรอกต้องไปทางพารามิเตอร์เท่านั้น ไม่ถูกต่อเข้า SQL ตรง ๆ"""
    client.get("/?d1=2026-10-01&d2=2026-10-15")
    client.get("/cases?d1=2026-10-01&d2=2026-10-15&dep=010")
    client.get("/check?d1=2026-10-01&d2=2026-10-15")
    client.get("/api/flow.json?d=2026-10-15")
    assert fake_db
    for sql, args, _ in fake_db:
        assert "2026-10" not in sql and "'010'" not in sql, sql


def test_date_span_is_capped(client):
    today = date.today()
    d1 = (today - timedelta(days=5000)).isoformat()
    with app_mod.app.test_request_context(f"/?d1={d1}&d2={today.isoformat()}"):
        a, b, warn = app_mod._params()
    assert (date.fromisoformat(b) - date.fromisoformat(a)).days == app_mod.MAX_DAYS - 1
    assert "ไม่เกิน" in warn


def test_future_and_swapped_dates(client):
    today = date.today()
    future = (today + timedelta(days=3)).isoformat()
    with app_mod.app.test_request_context(f"/?d1={future}&d2=2026-01-01"):
        a, b, warn = app_mod._params()
    assert a == "2026-01-01" and b == today.isoformat() and "อนาคต" in warn


def test_build_survives_empty_db(fake_db):
    d = queries.build("2026-10-01", "2026-10-15")
    assert d["kpi"]["total"] == 0 and d["kpi"]["total_time"] is None
    assert isinstance(d["recs"]["items"], list)


def test_render_lock_is_exclusive(tmp_path):
    lock = app_mod._RenderLock(str(tmp_path / "x.lock"))
    assert lock.acquire(timeout=1)
    assert not lock.acquire(timeout=0.2)
    lock.release()
    assert lock.acquire(timeout=1)
    lock.release()
