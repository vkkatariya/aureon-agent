from aureon_agent.doctor import check_python

def test_check_python():
    status, details = check_python()
    assert status == "✅" or status == "❌"
    assert "Python" in details


# ── check_matrix ──────────────────────────────────────────────────────────

import httpx  # noqa: E402

from aureon_agent import doctor  # noqa: E402
from aureon_agent.config import AureonConfig  # noqa: E402


def _cfg(**kw):
    base = dict(MATRIX_HOMESERVER="https://hs.example.org",
                MATRIX_USER_ID="@aureon-agent:example.org",
                MATRIX_ACCESS_TOKEN="tok",
                MATRIX_ALLOWED_USERS="@me:example.org",
                MATRIX_ENCRYPTION=False)
    base.update(kw)
    return AureonConfig(**base)


def _resp(status, payload=None):
    return httpx.Response(status, json=payload or {}, request=httpx.Request("GET", "https://x"))


def _patch(monkeypatch, cfg, get):
    monkeypatch.setattr(doctor.AureonConfig, "from_file", classmethod(lambda cls, p: cfg))
    monkeypatch.setattr(doctor.httpx, "get", get)


def test_check_matrix_not_configured(monkeypatch):
    _patch(monkeypatch, AureonConfig(), lambda *a, **k: _resp(200))
    assert doctor.check_matrix()[0] == "🟡"


def test_check_matrix_ok(monkeypatch):
    def get(url, **kw):
        if url.endswith("/versions"):
            return _resp(200, {"versions": ["v1.5"]})
        return _resp(200, {"user_id": "@aureon-agent:example.org"})
    _patch(monkeypatch, _cfg(), get)
    status, details = doctor.check_matrix()
    assert status == "✅" and "@aureon-agent:example.org" in details


def test_check_matrix_unauthorized(monkeypatch):
    def get(url, **kw):
        return _resp(200, {"versions": []}) if url.endswith("/versions") else _resp(401)
    _patch(monkeypatch, _cfg(), get)
    status, details = doctor.check_matrix()
    assert status == "❌" and "401" in details


def test_check_matrix_connection_error(monkeypatch):
    def get(url, **kw):
        raise httpx.ConnectError("refused")
    _patch(monkeypatch, _cfg(), get)
    status, details = doctor.check_matrix()
    assert status == "❌" and "unreachable" in details.lower()


def test_check_matrix_bad_allowlist(monkeypatch):
    def get(url, **kw):
        return _resp(200, {"user_id": "@aureon-agent:example.org"})
    _patch(monkeypatch, _cfg(MATRIX_ALLOWED_USERS="not-an-mxid"), get)
    assert doctor.check_matrix()[0] == "❌"


def test_check_matrix_token_for_wrong_user(monkeypatch):
    def get(url, **kw):
        return _resp(200, {"user_id": "@someone-else:example.org"})
    _patch(monkeypatch, _cfg(), get)
    assert doctor.check_matrix()[0] == "❌"


def test_check_matrix_crypto_store_warning(monkeypatch, tmp_path):
    def get(url, **kw):
        return _resp(200, {"user_id": "@aureon-agent:example.org"})
    _patch(monkeypatch, _cfg(MATRIX_ENCRYPTION=True), get)
    monkeypatch.setattr(doctor, "DATA_DIR", str(tmp_path))
    assert doctor.check_matrix()[0] == "🟡"
    (tmp_path / "matrix_crypto.db").write_text("")
    assert doctor.check_matrix()[0] == "✅"
