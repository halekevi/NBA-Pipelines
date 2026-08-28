"""Machine-hop Parquet sidecar next to CSV/XLSX."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from proporacle.data.table_io import (
    copy_parquet_sidecar,
    parquet_available,
    parquet_sidecar_path,
    read_table,
    read_table_str,
    table_exists,
    write_excel_sheets,
    write_parquet_sidecar,
)


pytestmark = pytest.mark.skipif(not parquet_available(), reason="pyarrow/fastparquet not installed")


def test_parquet_sidecar_preferred_over_csv(tmp_path: Path):
    csv_path = tmp_path / "step8_wnba_direction.csv"
    pd.DataFrame({"player": ["A"], "line": [1.5]}).to_csv(csv_path, index=False)
    write_parquet_sidecar(pd.DataFrame({"player": ["B"], "line": [9.5]}), csv_path)
    assert parquet_sidecar_path(csv_path).is_file()
    df = read_table(csv_path)
    assert list(df["player"]) == ["B"]
    assert float(df["line"].iloc[0]) == 9.5


def test_read_falls_back_to_csv_when_parquet_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    csv_path = tmp_path / "board.csv"
    pd.DataFrame({"player": ["csv"]}).to_csv(csv_path, index=False)
    write_parquet_sidecar(pd.DataFrame({"player": ["pq"]}), csv_path)
    monkeypatch.setattr("proporacle.data.table_io.parquet_available", lambda: False)
    df = read_table(csv_path)
    assert list(df["player"]) == ["csv"]


def test_table_exists_sees_sidecar_only(tmp_path: Path):
    xlsx = tmp_path / "step8_mlb_direction_clean.xlsx"
    write_parquet_sidecar(pd.DataFrame({"player": ["X"]}), xlsx)
    assert not xlsx.is_file()
    assert table_exists(xlsx)
    df = read_table(xlsx)
    assert list(df["player"]) == ["X"]


def test_copy_parquet_sidecar(tmp_path: Path):
    src = tmp_path / "step8.xlsx"
    dest = tmp_path / "dated" / "step8_clean.xlsx"
    write_parquet_sidecar(pd.DataFrame({"n": [1]}), src)
    copied = copy_parquet_sidecar(src, dest)
    assert copied is not None and copied.is_file()
    assert list(read_table(dest)["n"]) == [1]


def test_read_table_str_stringifies_parquet(tmp_path: Path):
    xlsx = tmp_path / "step7_ranked.xlsx"
    write_parquet_sidecar(pd.DataFrame({"player": ["A"], "line": [12.5], "n": [None]}), xlsx)
    df = read_table_str(xlsx, sheet="ALL")
    assert list(df["player"]) == ["A"]
    assert df["line"].iloc[0] == "12.5"
    assert df["n"].iloc[0] == ""


def test_write_excel_sheets_roundtrip(tmp_path: Path):
    path = tmp_path / "step7_ranked.xlsx"
    write_excel_sheets(
        path,
        {
            "ALL": pd.DataFrame({"Tier": ["A"], "player": ["X"]}),
            "ELIGIBLE": pd.DataFrame({"Tier": ["A"], "player": ["X"]}),
        },
    )
    assert path.is_file()
    df = pd.read_excel(path, sheet_name="ALL")
    assert list(df["player"]) == ["X"]
    assert list(df["Tier"]) == ["A"]


def test_step7b_refresh_keeps_parquet_in_sync(tmp_path: Path):
    """step8 prefers parquet; scoring the xlsx must rewrite the sidecar too."""
    xlsx = tmp_path / "step7_ranked.xlsx"
    df = pd.DataFrame({"player": ["A"], "eligible": [1], "ml_prob": [0.4]})
    write_excel_sheets(xlsx, {"ALL": df, "ELIGIBLE": df})
    write_parquet_sidecar(df, xlsx)
    scored = df.copy()
    scored["ml_prob"] = 0.81
    write_excel_sheets(xlsx, {"ALL": scored, "ELIGIBLE": scored})
    write_parquet_sidecar(scored, xlsx)
    hop = read_table(xlsx)
    assert float(hop["ml_prob"].iloc[0]) == pytest.approx(0.81)
