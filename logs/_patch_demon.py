from pathlib import Path
paths = [
    Path(r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp\scripts\combined_slate_tickets.py"),
    Path(r"H:\halek\ProfileFromC\Desktop\PropORACLE\scripts\combined_slate_tickets.py"),
]
old = '''    # Demon is distance-sensitive in upstream step8; without a direction/edge gate, UNDER legs
    # (or rows with missing projection → edge <= 0) can be mislabeled. PP-style Demon here
    # is only retained on OVER with strictly positive model edge; others → Goblin if
    # abs_edge suggests a softened line, else Standard.
    _pt_low = df["pick_type"].astype(str).str.strip().str.lower()
    _dmask = _pt_low.eq("demon")
    if bool(_dmask.any()):
        _dir_u = df["direction"].astype(str).str.strip().str.upper()
        _edge = pd.to_numeric(df["edge"], errors="coerce")
        _ae = pd.to_numeric(df["abs_edge"], errors="coerce")
        _ae = _ae.where(_ae.notna(), _edge.abs())
        _bad = _dmask & (~_dir_u.eq("OVER") | ~_edge.gt(0))
        if bool(_bad.any()):
            n_bad = int(_bad.sum())
            _use_gob = _bad & _ae.ge(0.5)
            _use_std = _bad & ~_use_gob
            df.loc[_use_gob, "pick_type"] = "Goblin"
            df.loc[_use_std, "pick_type"] = "Standard"
            print(
                f"  [{log_prefix}] demoted {n_bad} invalid Demon row(s) "
                "(require OVER + positive edge; Goblin if abs_edge>=0.5 else Standard)."
            )
'''
new = '''    # Demon lines sit above Standard/projection by design, so model edge vs the
    # Demon line is usually negative. Do not use edge.gt(0) — that demoted real
    # PrizePicks Demons to Goblin on the published slate. Only demote UNDER Demons.
    _pt_low = df["pick_type"].astype(str).str.strip().str.lower()
    _dmask = _pt_low.eq("demon")
    if bool(_dmask.any()):
        _dir_u = df["direction"].astype(str).str.strip().str.upper()
        _bad = _dmask & ~_dir_u.eq("OVER")
        if bool(_bad.any()):
            n_bad = int(_bad.sum())
            df.loc[_bad, "pick_type"] = "Standard"
            print(
                f"  [{log_prefix}] demoted {n_bad} UNDER Demon row(s) → Standard "
                "(PP Demons are OVER-only; edge-vs-Demon-line is not a label signal)."
            )
'''
for p in paths:
    text = p.read_text(encoding="utf-8")
    if old not in text:
        print("OLD NOT FOUND", p)
        continue
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("patched", p)
