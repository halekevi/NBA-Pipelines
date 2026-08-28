"""Flask blueprint: /account and /api/account/* (website + Android WebView)."""

from __future__ import annotations

import os
import secrets
from urllib.parse import urlparse

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

account_bp = Blueprint("account", __name__)

_GROUP_CHOICES = (
    "Goblin-70",
    "WNBA",
    "MLB",
    "Soccer",
    "Tennis",
    "NBA",
    "NFL",
    "CFB",
    "CBB",
    "STRONG",
)


def accounts_enabled() -> bool:
    return bool(current_app.config.get("PROPORACLE_ACCOUNTS_ENABLED", True))


def signup_code_required() -> str:
    return (os.environ.get("PROPORACLE_SIGNUP_CODE") or "").strip()


def _safe_next(raw: str | None) -> str:
    path = str(raw or "").strip()
    if not path.startswith("/") or path.startswith("//"):
        return "/account"
    parsed = urlparse(path)
    if parsed.scheme or parsed.netloc:
        return "/account"
    return path


def _store():
    try:
        from ui_runner import account_store as store
    except ImportError:
        import account_store as store  # type: ignore
    return store


def _login_user(user: dict) -> None:
    session.clear()
    session.permanent = True
    session["user_id"] = int(user["id"])


def _load_user():
    store = _store()
    try:
        uid = session.get("user_id")
    except RuntimeError:
        return None
    if not uid:
        return None
    try:
        return store.get_user(int(uid))
    except Exception:
        return None


def _pnl_mod():
    try:
        from ui_runner import placed_pnl as pnl
    except ImportError:
        import placed_pnl as pnl  # type: ignore
    return pnl


def _pnl_for_user(user: dict | None):
    if not user:
        return None
    pnl = _pnl_mod()
    raw_rows = _store().list_placed_rows(int(user["id"]))
    settled = [
        pnl.settle_snapshot(
            r.get("snapshot"),
            fingerprint=str(r.get("fingerprint") or ""),
            slate_date=str(r.get("slate_date") or ""),
            stake=r.get("stake") if r.get("stake") is not None else user.get("default_stake"),
        )
        for r in raw_rows
    ]
    return pnl.summarize(settled)


def _account_page(*, error: str = "", message: str = "", status: int = 200):
    user = _load_user() if accounts_enabled() else None
    chosen = list((user or {}).get("preferred_groups") or [])
    extra_groups = [g for g in chosen if g not in _GROUP_CHOICES]
    html = render_template(
        "account.html",
        nav_active="account",
        error=error,
        message=message,
        user=user,
        next_url=_safe_next(request.args.get("next") or request.form.get("next")),
        group_choices=_GROUP_CHOICES,
        extra_groups=extra_groups,
        signup_open=bool(signup_code_required()),
        ui_build_id=current_app.config.get("UI_BUILD_ID", ""),
        accounts_enabled=accounts_enabled(),
        pnl=_pnl_for_user(user),
    )
    return html, status


@account_bp.get("/account")
def page_account():
    if not accounts_enabled():
        return _account_page(
            error="Accounts are not configured (set SECRET_KEY / PROPORACLE_SECRET_KEY).",
            status=503,
        )
    return _account_page(
        error=str(request.args.get("err") or ""),
        message=str(request.args.get("msg") or ""),
    )


@account_bp.post("/account")
def page_account_post():
    if not accounts_enabled():
        return redirect(url_for("account.page_account"))
    store = _store()
    action = str(request.form.get("action") or "").strip().lower()
    next_url = _safe_next(request.form.get("next") or request.args.get("next"))

    if action == "logout":
        session.clear()
        return redirect(url_for("account.page_account", msg="Signed out."))

    if action == "signup":
        expected = signup_code_required()
        if not expected:
            return redirect(
                url_for("account.page_account", err="Sign-up is closed. Set PROPORACLE_SIGNUP_CODE.")
            )
        got = str(request.form.get("signup_code") or "")
        if not secrets.compare_digest(got, expected):
            return redirect(url_for("account.page_account", err="Sign-up code is incorrect.", next=next_url))
        try:
            user = store.create_user(request.form.get("email") or "", request.form.get("password") or "")
        except ValueError as exc:
            return redirect(url_for("account.page_account", err=str(exc), next=next_url))
        _login_user(user)
        dest = next_url if next_url != "/account" else url_for("account.page_account", msg="Account created.")
        return redirect(dest)

    if action == "login":
        user = store.verify_login(request.form.get("email") or "", request.form.get("password") or "")
        if not user:
            return redirect(
                url_for("account.page_account", err="Email or password is wrong.", next=next_url)
            )
        _login_user(user)
        dest = next_url if next_url != "/account" else url_for("account.page_account", msg="Signed in.")
        return redirect(dest)

    if action == "save_prefs":
        user = _load_user()
        if not user:
            return redirect(
                url_for("account.page_account", err="Sign in to save preferences.", next=next_url)
            )
        stake_raw = str(request.form.get("default_stake") or "").strip()
        stake = None
        if stake_raw:
            try:
                stake = float(stake_raw)
                if stake < 0 or stake > 10000:
                    raise ValueError
            except ValueError:
                return redirect(
                    url_for("account.page_account", err="Stake must be a number between 0 and 10000.")
                )
        groups = [g for g in request.form.getlist("preferred_groups") if g.strip()]
        extra = str(request.form.get("preferred_extra") or "")
        for part in extra.split(","):
            tok = part.strip()
            if tok and tok not in groups:
                groups.append(tok)
        try:
            store.update_prefs(int(user["id"]), default_stake=stake, preferred_groups=groups)
        except ValueError as exc:
            return redirect(url_for("account.page_account", err=str(exc)))
        return redirect(url_for("account.page_account", msg="Preferences saved."))

    return redirect(url_for("account.page_account"))


@account_bp.post("/account/logout")
def logout():
    session.clear()
    return redirect(url_for("account.page_account", msg="Signed out."))


@account_bp.get("/api/account/me")
def api_me():
    if not accounts_enabled():
        return jsonify({"logged_in": False, "accounts_enabled": False}), 200
    user = _load_user()
    if not user:
        return jsonify({"logged_in": False, "accounts_enabled": True})
    slate = str(request.args.get("slate") or "").strip()[:10]
    placed = _store().list_placed(int(user["id"]), slate) if slate else []
    return jsonify(
        {
            "logged_in": True,
            "accounts_enabled": True,
            "email": user["email"],
            "default_stake": user.get("default_stake"),
            "preferred_groups": user.get("preferred_groups") or [],
            "placed": placed,
            "slate": slate or None,
        }
    )


@account_bp.get("/api/account/pnl")
def api_pnl():
    if not accounts_enabled():
        return jsonify({"error": "accounts_disabled"}), 503
    user = _load_user()
    if not user:
        return jsonify({"error": "login_required"}), 401
    return jsonify(_pnl_for_user(user) or {})


@account_bp.post("/api/account/placed")
def api_placed():
    if not accounts_enabled():
        return jsonify({"error": "accounts_disabled"}), 503
    user = _load_user()
    if not user:
        return jsonify({"error": "login_required", "login_url": "/account?next=/tickets"}), 401
    payload = request.get_json(silent=True) or {}
    slate = str(payload.get("slate_date") or payload.get("slate") or "").strip()[:10]
    placed = bool(payload.get("placed"))
    fps = payload.get("fingerprints")
    store = _store()
    try:
        stake = float(user.get("default_stake")) if user.get("default_stake") is not None else 20.0
    except (TypeError, ValueError):
        stake = 20.0
    pnl = _pnl_mod()

    def _snap(fp: str):
        found = pnl.find_ticket(fp)
        if not found:
            return None
        ticket, gname = found
        return pnl.snapshot_from_ticket(ticket, group_name=gname, stake=stake)

    if isinstance(fps, list) and fps:
        tokens = [str(x).strip() for x in fps if str(x).strip()]
        snaps = {fp: s for fp in tokens if (s := _snap(fp))}
        store.set_placed_many(
            int(user["id"]), slate, tokens, placed, stake=stake, snapshots=snaps
        )
        return jsonify({"ok": True, "placed": store.list_placed(int(user["id"]), slate)})
    fp = str(payload.get("fingerprint") or "").strip()
    try:
        store.set_placed(int(user["id"]), slate, fp, placed, stake=stake, snapshot=_snap(fp) if placed else None)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "placed": store.list_placed(int(user["id"]), slate)})
