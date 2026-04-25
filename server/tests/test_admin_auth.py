from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def _client() -> TestClient:
    from app.dependencies.admin_auth import require_admin_token

    app = FastAPI()

    @app.get("/probe", dependencies=[Depends(require_admin_token)])
    def probe():
        return {"authorized": True}

    return TestClient(app)


def test_admin_token_config_treats_missing_and_blank_as_unset(admin_token_env):
    from app.config import get_admin_token

    admin_token_env(None)
    assert get_admin_token() == ""

    admin_token_env("")
    assert get_admin_token() == ""

    admin_token_env("   ")
    assert get_admin_token() == ""

    admin_token_env("  secret-token  ")
    assert get_admin_token() == "secret-token"


def test_admin_auth_fails_closed_when_token_unset(admin_token_env):
    admin_token_env(None)

    response = _client().get("/probe", headers={"Authorization": "Bearer anything"})

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Admin API disabled: DEJAQ_ADMIN_TOKEN not configured"
    }


def test_admin_auth_rejects_missing_malformed_and_wrong_tokens(admin_token_env):
    admin_token_env("admin-secret")
    client = _client()

    missing = client.get("/probe")
    malformed = client.get("/probe", headers={"Authorization": "Basic admin-secret"})
    empty_bearer = client.get("/probe", headers={"Authorization": "Bearer "})
    wrong = client.get("/probe", headers={"Authorization": "Bearer wrong"})

    assert missing.status_code == 401
    assert missing.json() == {"detail": "Admin token required"}
    assert malformed.status_code == 401
    assert malformed.json() == {"detail": "Admin token required"}
    assert empty_bearer.status_code == 401
    assert empty_bearer.json() == {"detail": "Admin token required"}
    assert wrong.status_code == 401
    assert wrong.json() == {"detail": "Invalid admin token"}


def test_admin_auth_accepts_valid_token(admin_token_env):
    admin_token_env("admin-secret")

    response = _client().get("/probe", headers={"Authorization": "Bearer admin-secret"})

    assert response.status_code == 200
    assert response.json() == {"authorized": True}


def test_startup_logs_warning_when_admin_token_unset(monkeypatch, caplog):
    from app import main

    monkeypatch.setattr(main, "get_admin_token", lambda: "")

    with caplog.at_level("WARNING", logger="dejaq.admin"):
        main._log_admin_api_status()

    assert any(
        "DEJAQ_ADMIN_TOKEN not set; /admin/v1/* disabled" in record.message
        for record in caplog.records
    )


def test_api_key_middleware_skips_admin_paths(monkeypatch, caplog):
    from app.middleware import api_key
    from app.middleware.api_key import ApiKeyMiddleware

    def _fail_resolve(_token: str):
        raise AssertionError("admin token should not be resolved as an org API key")

    monkeypatch.setattr(api_key._KEY_CACHE, "resolve", _fail_resolve)

    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware)

    @app.get("/admin/v1/whoami")
    def whoami():
        return {"authorized": True}

    with caplog.at_level("WARNING", logger="dejaq.middleware.api_key"):
        response = TestClient(app).get(
            "/admin/v1/whoami",
            headers={"Authorization": "Bearer admin-secret"},
        )

    assert response.status_code == 200
    assert response.json() == {"authorized": True}
    assert not [
        record for record in caplog.records if "Unrecognized API key" in record.message
    ]


def test_all_admin_routes_share_auth_dependency(admin_token_env):
    from app.main import app

    cases = [
        ("GET", "/admin/v1/whoami", None),
        ("GET", "/admin/v1/orgs", None),
        ("POST", "/admin/v1/orgs", {"name": "Acme"}),
        ("DELETE", "/admin/v1/orgs/acme", None),
        ("GET", "/admin/v1/departments", None),
        ("POST", "/admin/v1/orgs/acme/departments", {"name": "Eng"}),
        ("DELETE", "/admin/v1/orgs/acme/departments/eng", None),
        ("GET", "/admin/v1/orgs/acme/keys", None),
        ("POST", "/admin/v1/orgs/acme/keys", None),
        ("DELETE", "/admin/v1/keys/1", None),
        ("GET", "/admin/v1/stats/orgs", None),
        ("GET", "/admin/v1/stats/orgs/acme/departments", None),
        ("GET", "/admin/v1/orgs/acme/llm-config", None),
        ("PUT", "/admin/v1/orgs/acme/llm-config", {"external_model": None}),
        ("GET", "/admin/v1/feedback", None),
        ("POST", "/admin/v1/feedback", {"org": "acme", "response_id": "acme--default:doc", "rating": "positive"}),
    ]

    admin_token_env(None)
    client = TestClient(app)
    for method, path, body in cases:
        response = client.request(method, path, json=body, headers={"Authorization": "Bearer anything"})
        assert response.status_code == 503, f"{method} {path}"

    admin_token_env("admin-secret")
    client = TestClient(app)
    for method, path, body in cases:
        missing = client.request(method, path, json=body)
        wrong = client.request(method, path, json=body, headers={"Authorization": "Bearer wrong"})
        assert missing.status_code == 401, f"{method} {path}"
        assert wrong.status_code == 401, f"{method} {path}"
