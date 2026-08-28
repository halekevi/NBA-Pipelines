"""Flask /account routes: signup, login, placed API."""

from __future__ import annotations


def test_account_http_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("PROPORACLE_ACCOUNTS_DB", str(tmp_path / "acct.db"))
    monkeypatch.setenv("PROPORACLE_SIGNUP_CODE", "letmein")
    monkeypatch.setenv("PROPORACLE_SECRET_KEY", "test-secret-key-not-for-prod")
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    from ui_runner.app import app

    app.config["PROPORACLE_ACCOUNTS_ENABLED"] = True
    app.config["TESTING"] = True
    client = app.test_client()

    home = client.get("/account")
    assert home.status_code == 200
    assert b"Create account" in home.data

    bad = client.post(
        "/account",
        data={"action": "signup", "email": "me@x.com", "password": "password123", "signup_code": "nope"},
        follow_redirects=True,
    )
    assert b"incorrect" in bad.data.lower() or b"Sign-up code" in bad.data

    created = client.post(
        "/account",
        data={
            "action": "signup",
            "email": "me@x.com",
            "password": "password123",
            "signup_code": "letmein",
            "next": "/tickets",
        },
        follow_redirects=False,
    )
    assert created.status_code in (302, 303)
    assert created.headers["Location"].endswith("/tickets")

    me = client.get("/api/account/me?slate=2026-08-27")
    assert me.status_code == 200
    body = me.get_json()
    assert body["logged_in"] is True
    assert body["email"] == "me@x.com"

    client.post(
        "/account",
        data={
            "action": "save_prefs",
            "default_stake": "20",
            "preferred_groups": ["WNBA", "Goblin-70"],
        },
        follow_redirects=True,
    )
    me2 = client.get("/api/account/me").get_json()
    assert me2["default_stake"] == 20.0
    assert "WNBA" in me2["preferred_groups"]

    placed = client.post(
        "/api/account/placed",
        json={"slate_date": "2026-08-27", "fingerprint": "p|pts|10.5|OVER", "placed": True},
    )
    assert placed.status_code == 200
    assert "p|pts|10.5|OVER" in placed.get_json()["placed"]
