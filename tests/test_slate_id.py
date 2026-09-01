from utils.pipeline_dated_outputs import copy_pipeline_output_to_dated_dirs, earliest_slate_date_iso
from utils.slate_id import SlateId, dated_copy_ymd, parse_pipeline_ymd
import pandas as pd


def test_parse_pipeline_ymd_rejects_clock_and_junk():
    assert parse_pipeline_ymd("2026-09-01") == "2026-09-01"
    assert parse_pipeline_ymd("2026-09-01T19:00:00Z") == "2026-09-01"
    assert parse_pipeline_ymd("") is None
    assert parse_pipeline_ymd("today") is None
    assert parse_pipeline_ymd(None) is None


def test_slate_id_from_pipeline_date():
    sid = SlateId.from_pipeline_date("2026-09-01")
    assert sid is not None
    assert sid.et_date == "2026-09-01"
    assert SlateId.from_pipeline_date("") is None


def test_dated_copy_ymd_skips_without_date(capsys):
    assert dated_copy_ymd("", context="NBA step8") is None
    err = capsys.readouterr().out
    assert "skipping dated copy" in err
    assert dated_copy_ymd("2026-09-01", context="NBA step8") == "2026-09-01"


def test_pipeline_dated_copy_prefers_pipeline_date(tmp_path):
    src = tmp_path / "step4.csv"
    src.write_text("a,b\n1,2\n", encoding="utf-8")
    df = pd.DataFrame({"game_date": ["2026-09-03", "2026-09-04"]})
    assert earliest_slate_date_iso(df) == "2026-09-03"
    copy_pipeline_output_to_dated_dirs(
        output_path=src,
        df=df,
        sport_dir_name="cfb",
        repo_root=tmp_path,
        pipeline_date="2026-09-01",
    )
    dest = tmp_path / "outputs" / "2026-09-01" / "step4.csv"
    assert dest.is_file()
    wrong = tmp_path / "outputs" / "2026-09-03" / "step4.csv"
    assert not wrong.exists()
