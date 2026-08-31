from utils.team_share import attach_share_fields, enrich_matchup_edge_payload


def test_attach_share_fields_fills_team_avg_and_vs_line():
    share = {
        "applicable": True,
        "by_player": {
            "CHI|kamilla cardoso|Points": {
                "team_avg": 81.11,
                "share_pct": 20.0,
                "player_avg": 16.22,
            }
        },
        "team_aliases": {},
    }
    p = {"player": "Kamilla Cardoso", "pp_line": 9.5}
    attach_share_fields(p, share, team="CHI", category_id="pts")
    assert p["team_avg"] == 81.11
    assert p["share_pct"] == 20.0
    assert p["avg_vs_line"] == 6.72


def test_enrich_matchup_edge_payload_stamps_block_players(monkeypatch):
    share = {
        "applicable": True,
        "sport": "wnba",
        "by_player": {
            "CHI|kamilla cardoso|Points": {
                "team_avg": 81.11,
                "share_pct": 20.0,
                "player_avg": 16.22,
            }
        },
        "team_aliases": {},
    }
    monkeypatch.setattr("utils.team_share.load_share_payload", lambda *a, **k: share)
    payload = {
        "players_by_team_cat": {
            "CHI|pts": {
                "team_slate": "CHI",
                "category": "pts",
                "players": [{"player": "Kamilla Cardoso", "season_avg": 16.22}],
            }
        }
    }
    out = enrich_matchup_edge_payload(payload, "wnba")
    row = out["players_by_team_cat"]["CHI|pts"]["players"][0]
    assert row["team_avg"] == 81.11
    assert row["share_pct"] == 20.0
    assert out["team_share"]["applicable"] is True
