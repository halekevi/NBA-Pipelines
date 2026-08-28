"""Account SQLite store: create, login, prefs, placed slips."""

from pathlib import Path

import pytest


def test_create_login_prefs_placed(tmp_path, monkeypatch):
    db = tmp_path / "accounts.db"
    monkeypatch.setenv("PROPORACLE_ACCOUNTS_DB", str(db))
    from ui_runner import account_store as store

    with pytest.raises(ValueError):
        store.create_user("not-an-email", "password123")
    with pytest.raises(ValueError):
        store.create_user("a@b.com", "short")

    user = store.create_user("A@B.COM", "password123")
    assert user["email"] == "a@b.com"
    assert store.verify_login("a@b.com", "wrong") is None
    logged = store.verify_login("A@b.com", "password123")
    assert logged and logged["id"] == user["id"]

    with pytest.raises(ValueError):
        store.create_user("a@b.com", "password123")

    updated = store.update_prefs(
        user["id"], default_stake=25.0, preferred_groups=["Goblin-70", "WNBA", ""]
    )
    assert updated["default_stake"] == 25.0
    assert updated["preferred_groups"] == ["Goblin-70", "WNBA"]

    fp = "aja wilson|points|22.5|OVER;jackie young|assists|5.5|OVER"
    store.set_placed(user["id"], "2026-08-27", fp, True)
    assert store.list_placed(user["id"], "2026-08-27") == [fp]
    store.set_placed(user["id"], "2026-08-27", fp, False)
    assert store.list_placed(user["id"], "2026-08-27") == []
    store.set_placed_many(user["id"], "2026-08-27", [fp, "x|y|1|OVER"], True)
    assert len(store.list_placed(user["id"], "2026-08-27")) == 2
    assert Path(db).is_file()
