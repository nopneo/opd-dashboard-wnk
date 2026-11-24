"""header จาก proxy เชื่อเฉพาะเครื่องเดียวกัน · ช่วง IP ภายในระบุเอง (ไม่ใช้ ip.is_private)"""
import pytest

import app as app_mod


@pytest.mark.parametrize("ip, lan", [
    ("192.168.11.5", True), ("10.1.2.3", True), ("172.20.0.1", True), ("127.0.0.1", True), ("::1", True),
    ("198.18.0.1", False), ("203.0.113.7", False), ("100.64.1.1", False), ("8.8.8.8", False),
    ("::ffff:192.168.1.1", True), ("::ffff:8.8.8.8", False), ("junk", False)])
def test_private_explicit_ranges(ip, lan):
    assert app_mod._private(ip) is lan


@pytest.mark.parametrize("peer, lan", [("192.168.1.5", True), ("198.18.0.1", False), ("203.0.113.7", False)])
def test_from_lan_direct_peer(peer, lan):
    with app_mod.app.test_request_context("/", environ_base={"REMOTE_ADDR": peer}):
        assert app_mod._from_lan() is lan


def test_lan_nets_extra_range_still_counts(monkeypatch):
    monkeypatch.setattr(app_mod, "LAN_NETS", app_mod._networks("30.25.0.0/16"))
    assert app_mod._private("30.25.1.9")


def _html(headers, peer):
    c = app_mod.app.test_client()
    return c.get("/help", headers=headers, environ_base={"REMOTE_ADDR": peer}).get_data(as_text=True)


def test_prefix_only_from_trusted_proxy():
    assert "/evil/static" not in _html({"X-Forwarded-Prefix": "/evil"}, "192.168.1.5")
    assert "/opd/static" in _html({"X-Forwarded-Prefix": "/opd"}, "127.0.0.1")


@pytest.mark.parametrize("prefix", ["//evil.example", "/opd\"><script>", "opd", "/op d"])
def test_bad_prefix_ignored(prefix):
    html = _html({"X-Forwarded-Prefix": prefix}, "127.0.0.1")
    assert "evil.example" not in html and "<script>/static" not in html and 'href="opd' not in html


def test_proto_only_http_or_https():
    c = app_mod.app.test_client()
    r = c.get("/manifest.webmanifest", headers={"X-Forwarded-Proto": "javascript"},
              environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 200 and "javascript:" not in r.get_data(as_text=True)
