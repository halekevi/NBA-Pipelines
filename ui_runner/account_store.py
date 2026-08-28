"""SQLite store for PropORACLE website/app accounts (not PrizePicks)."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

_LOCK = threading.Lock()
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  default_stake REAL,
  preferred_groups TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS placed_slips (
  user_id INTEGER NOT NULL,
  slate_date TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  placed_at TEXT NOT NULL,
  PRIMARY KEY (user_id, slate_date, fingerprint)
);
"""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def accounts_db_path() -> Path:
    raw = (os.environ.get("PROPORACLE_ACCOUNTS_DB") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    income = (os.environ.get("PROPORACLE_DB_PATH") or "").strip()
    if income:
        parent = Path(income).expanduser().resolve().parent
        return parent / "proporacle_accounts.db"
    try:
        from utils.proporacle_data_root import persistent_data_dir

        return persistent_data_dir(_repo_root()) / "proporacle_accounts.db"
    except Exception:
        return _repo_root() / "data" / "proporacle_accounts.db"


def _connect() -> sqlite3.Connection:
    path = accounts_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def email_ok(email: str) -> bool:
    return bool(_EMAIL_RE.match(normalize_email(email)))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _prefs_from_row(row: sqlite3.Row) -> dict[str, Any]:
    groups: list[str] = []
    raw = row["preferred_groups"] if row else "[]"
    try:
        parsed = json.loads(raw or "[]")
        if isinstance(parsed, list):
            groups = [str(x).strip() for x in parsed if str(x).strip()]
    except (TypeError, json.JSONDecodeError):
        groups = []
    stake = row["default_stake"] if row else None
    try:
        stake_f = float(stake) if stake is not None else None
    except (TypeError, ValueError):
        stake_f = None
    return {
        "id": int(row["id"]),
        "email": str(row["email"]),
        "default_stake": stake_f,
        "preferred_groups": groups,
        "created_at": str(row["created_at"] or ""),
    }


def get_user(user_id: int) -> dict[str, Any] | None:
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
            return _prefs_from_row(row) if row else None
        finally:
            conn.close()


def get_user_by_email(email: str) -> dict[str, Any] | None:
    em = normalize_email(email)
    if not em:
        return None
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (em,)).fetchone()
            return _prefs_from_row(row) if row else None
        finally:
            conn.close()


def create_user(email: str, password: str) -> dict[str, Any]:
    em = normalize_email(email)
    if not email_ok(em):
        raise ValueError("Enter a valid email.")
    if len(str(password or "")) < 8:
        raise ValueError("Password must be at least 8 characters.")
    pw_hash = generate_password_hash(password)
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO users (email, password_hash, preferred_groups, created_at) "
                "VALUES (?, ?, '[]', ?)",
                (em, pw_hash, _now()),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE email = ?", (em,)).fetchone()
            return _prefs_from_row(row)
        except sqlite3.IntegrityError as exc:
            raise ValueError("An account with that email already exists.") from exc
        finally:
            conn.close()


def verify_login(email: str, password: str) -> dict[str, Any] | None:
    em = normalize_email(email)
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (em,)).fetchone()
            if not row:
                return None
            if not check_password_hash(str(row["password_hash"]), str(password or "")):
                return None
            return _prefs_from_row(row)
        finally:
            conn.close()


def update_prefs(user_id: int, *, default_stake: float | None, preferred_groups: list[str]) -> dict[str, Any]:
    groups = [str(x).strip() for x in (preferred_groups or []) if str(x).strip()]
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE users SET default_stake = ?, preferred_groups = ? WHERE id = ?",
                (default_stake, json.dumps(groups), int(user_id)),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
            if not row:
                raise ValueError("Account not found.")
            return _prefs_from_row(row)
        finally:
            conn.close()


def list_placed(user_id: int, slate_date: str) -> list[str]:
    day = str(slate_date or "").strip()[:10]
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT fingerprint FROM placed_slips WHERE user_id = ? AND slate_date = ?",
                (int(user_id), day),
            ).fetchall()
            return [str(r["fingerprint"]) for r in rows]
        finally:
            conn.close()


def set_placed(user_id: int, slate_date: str, fingerprint: str, placed: bool) -> None:
    day = str(slate_date or "").strip()[:10]
    fp = str(fingerprint or "").strip()
    if not day or not fp:
        raise ValueError("Missing slate date or ticket fingerprint.")
    with _LOCK:
        conn = _connect()
        try:
            if placed:
                conn.execute(
                    "INSERT OR IGNORE INTO placed_slips "
                    "(user_id, slate_date, fingerprint, placed_at) VALUES (?, ?, ?, ?)",
                    (int(user_id), day, fp, _now()),
                )
            else:
                conn.execute(
                    "DELETE FROM placed_slips WHERE user_id = ? AND slate_date = ? AND fingerprint = ?",
                    (int(user_id), day, fp),
                )
            conn.commit()
        finally:
            conn.close()


def set_placed_many(user_id: int, slate_date: str, fingerprints: list[str], placed: bool) -> None:
    for fp in fingerprints:
        if str(fp or "").strip():
            set_placed(user_id, slate_date, str(fp).strip(), placed)
