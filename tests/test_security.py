"""ความปลอดภัยเมื่อเปิดแดชบอร์ดผ่านอินเทอร์เน็ต (reverse proxy / Cloudflare)"""

import time

import pytest

import app as app_mod
import render

#: คำขอจากอินเทอร์เน็ตผ่าน proxy มี X-Forwarded-For เสมอ
PUBLIC = {"X-Forwarded-For": "203.0.113.7", "X-Forwarded-Prefix": "/opd"}


@pytest.fixture
def client(fake_db, monkeypatch):
    monkeypatch.delenv("OPD_PUBLIC_DRILLDOWN", raising=False)
    app_mod._export_cache._data.clear()
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


@pytest.mark.parametrize("url", ["/cases", "/cases?dep=010", "/check"])
def test_drilldown_blocked_from_internet(client, url):
    r = client.get(url, headers=PUBLIC)
    assert r.status_code == 403 and "เครือข่ายของโรงพยาบาล" in r.get_data(as_text=True)


@pytest.mark.parametrize("url", ["/cases", "/check"])
def test_drilldown_open_on_lan(client, url):
    assert client.get(url, environ_base={"REMOTE_ADDR": "192.168.1.20"}).status_code == 200


def test_drilldown_can_be_made_public(client, monkeypatch):
    monkeypatch.setenv("OPD_PUBLIC_DRILLDOWN", "1")
    assert client.get("/cases", headers=PUBLIC).status_code == 200


def test_dashboard_hides_drilldown_links_from_internet(client):
    public = client.get("/", headers=PUBLIC).get_data(as_text=True)
    lan = client.get("/").get_data(as_text=True)
    assert "/cases" not in public and "/check" not in public
    assert "/cases" in lan and "/check" in lan
    assert client.get("/", headers=PUBLIC).status_code == 200      # ผู้บริหารยังดูแดชบอร์ดได้


def test_export_busy_answers_immediately(client, monkeypatch):
    """งานส่งออกค้างอยู่ — คำขอใหม่ต้องได้ 503 ทันที ไม่นั่งรอกิน worker"""
    monkeypatch.setattr(app_mod, "EXPORT_WAIT", 0)
    assert app_mod._render_lock.acquire(timeout=1)
    try:
        t = time.monotonic()
        r = client.get("/export.png", headers=PUBLIC)
        assert r.status_code == 503 and r.headers["Retry-After"]
        assert time.monotonic() - t < 1
        assert client.get("/help.pdf").status_code == 503
    finally:
        app_mod._render_lock.release()


def test_export_reuses_recent_file(client, monkeypatch):
    calls = []

    def fake_render(fmt, url, out):
        calls.append(url)
        open(out, "wb").write(b"PNG")

    monkeypatch.setattr(app_mod.render, "render_to", fake_render)
    for _ in range(3):
        r = client.get("/export.png?d1=2026-10-01&d2=2026-10-15")
        assert r.status_code == 200 and r.data == b"PNG"
    assert len(calls) == 1
    client.get("/export.png?d1=2026-10-02&d2=2026-10-15")          # ช่วงอื่น = เรนเดอร์ใหม่
    assert len(calls) == 2


def test_security_headers(client):
    r = client.get("/", headers=PUBLIC)
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "same-origin"


@pytest.mark.parametrize("euid, env, want", [(0, None, True), (1000, None, False), (1000, "1", True)])
def test_chromium_sandbox_only_disabled_when_needed(monkeypatch, euid, env, want):
    monkeypatch.setattr(render.os, "geteuid", lambda: euid, raising=False)
    if env:
        monkeypatch.setenv("OPD_CHROME_NO_SANDBOX", env)
    else:
        monkeypatch.delenv("OPD_CHROME_NO_SANDBOX", raising=False)
    assert ("--no-sandbox" in render._base_args("/usr/bin/chromium", "/tmp/p")) is want
