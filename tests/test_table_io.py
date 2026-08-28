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
