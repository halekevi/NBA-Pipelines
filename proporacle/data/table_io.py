"""CSV/Excel stay human-facing; Parquet is the fast machine hop.

Writers keep emitting CSV/XLSX. Readers prefer a sibling ``.parquet`` when
pyarrow is installed. Railway/web does not need pyarrow — loaders fall back
to CSV/XLSX automatically.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

_PARQUET_ENGINES = ("pyarrow", "fastparquet")


def parquet_sidecar_path(path: str | Path) -> Path:
    return Path(path).with_suffix(".parquet")


def parquet_available() -> bool:
    try:
        import pyarrow  # noqa: F401

        return True
    except ImportError:
        try:
            import fastparquet  # noqa: F401

            return True
        except ImportError:
            return False


def table_exists(path: str | Path) -> bool:
    p = Path(path)
    return p.is_file() or parquet_sidecar_path(p).is_file()


def _dedupe_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.loc[:, ~df.columns.duplicated()].copy()


def _prepare_for_parquet(df: pd.DataFrame) -> pd.DataFrame:
    out = _dedupe_columns(df)
    out.columns = [str(c) for c in out.columns]
    for col in list(out.columns):
        s = out[col]
        if s.dtype == object:
            mapped = s.map(_parquet_cell)
            types = {type(v) for v in mapped.dropna()}
            if len(types) > 1:
                out[col] = mapped.map(lambda v: None if v is None else str(v))
            else:
                out[col] = mapped
            continue
        try:
            if s.dropna().map(lambda v: isinstance(v, str)).any():
                out[col] = s.map(_parquet_cell).map(
                    lambda v: None if v is None else str(v)
                )
        except Exception:
            out[col] = s.astype(object).map(_parquet_cell)
    return out


def _stringify_objects(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        out[col] = out[col].map(_parquet_cell).map(lambda v: None if v is None else str(v))
    return out


def _parquet_cell(v: Any) -> Any:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def write_parquet_sidecar(df: pd.DataFrame, path: str | Path) -> Path | None:
    """Write ``<stem>.parquet`` next to csv/xlsx ``path``. No-op without pyarrow."""
    if df is None or not parquet_available():
        return None
    p = Path(path)
    if not str(p):
        return None
    pq = parquet_sidecar_path(p)
    pq.parent.mkdir(parents=True, exist_ok=True)
    body = _prepare_for_parquet(df)
    try:
        body.to_parquet(pq, index=False)
    except Exception:
        try:
            _stringify_objects(body).to_parquet(pq, index=False)
        except Exception as exc:
            print(f"[table_io] WARN parquet sidecar skipped ({pq.name}): {exc}")
            return None
    print(f"[table_io] parquet sidecar -> {pq}")
    return pq


def write_parquet_sidecars(df: pd.DataFrame, *paths: str | Path) -> list[Path]:
    written: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        if not path:
            continue
        key = str(parquet_sidecar_path(path).resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        out = write_parquet_sidecar(df, path)
        if out is not None:
            written.append(out)
    return written


def copy_parquet_sidecar(src: str | Path, dest: str | Path) -> Path | None:
    """Copy ``src``'s parquet sidecar next to ``dest`` (dated outputs/)."""
    src_pq = parquet_sidecar_path(src)
    if not src_pq.is_file():
        return None
    dest_pq = parquet_sidecar_path(dest)
    dest_pq.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(src_pq, dest_pq)
    except OSError as exc:
        print(f"[table_io] WARN parquet copy skipped ({dest_pq.name}): {exc}")
        return None
    return dest_pq


def _drop_arrow_backend(df: pd.DataFrame) -> pd.DataFrame:
    """Arrow-backed string cols reject numeric assignment (combined L5 truth)."""
    out = df.copy()
    for col in out.columns:
        dtype = out[col].dtype
        name = str(dtype)
        if (
            "pyarrow" in name
            or name.startswith("string")
            or type(dtype).__name__ == "ArrowDtype"
        ):
            out[col] = out[col].astype(object)
    return out


def _read_parquet(path: Path) -> pd.DataFrame:
    try:
        raw = pd.read_parquet(path, dtype_backend="numpy_nullable")
    except TypeError:
        raw = pd.read_parquet(path)
    out = _drop_arrow_backend(_dedupe_columns(raw))
    # Excel-era callers use `x or ""`; pandas NA is not boolean-falsy.
    return out.astype(object).mask(out.isna(), None)


def _pick_excel_sheet(path: Path, sheet: str | None, sheet_order: tuple[str, ...] | None) -> str | int:
    if sheet:
        return sheet
    xl = pd.ExcelFile(path, engine="openpyxl")
    names = list(xl.sheet_names)
    if sheet_order:
        for name in sheet_order:
            if name in names:
                return name
    return names[0] if names else 0


def stringify_cells(df: pd.DataFrame) -> pd.DataFrame:
    """Match step8 ``pd.read_excel(..., dtype=str).fillna('')`` without Excel."""
    if df is None:
        return pd.DataFrame()
    out = _dedupe_columns(df)
    if out.empty:
        return out
    for col in out.columns:
        out[col] = out[col].map(_excel_str_cell)
    return out


def _excel_str_cell(v: Any) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(v)
    if s.lower() in {"nan", "<na>", "none", "nat", "<nat>"}:
        return ""
    return s


def read_table(
    path: str | Path,
    *,
    sheet: str | None = None,
    sheet_order: tuple[str, ...] | None = None,
    prefer_parquet: bool = True,
    **csv_kwargs: Any,
) -> pd.DataFrame:
    """Read parquet sidecar if present, else CSV/XLSX/parquet at ``path``."""
    p = Path(path)
    sidecar = parquet_sidecar_path(p)
    if prefer_parquet and sidecar.is_file() and parquet_available():
        try:
            return _read_parquet(sidecar)
        except Exception as exc:
            print(f"[table_io] WARN parquet read failed ({sidecar.name}), falling back: {exc}")

    suffix = p.suffix.lower()
    if suffix == ".parquet":
        return _read_parquet(p)
    if suffix in {".csv", ".txt"}:
        kwargs = {"encoding": "utf-8-sig", "low_memory": False, **csv_kwargs}
        return _dedupe_columns(pd.read_csv(p, **kwargs))
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        chosen = _pick_excel_sheet(p, sheet, sheet_order)
        return _dedupe_columns(pd.read_excel(p, sheet_name=chosen, engine="openpyxl"))
    if sidecar.is_file() and parquet_available():
        return _read_parquet(sidecar)
    raise FileNotFoundError(f"Unsupported table path: {p}")


def read_table_str(
    path: str | Path,
    *,
    sheet: str | None = None,
    sheet_order: tuple[str, ...] | None = None,
    prefer_parquet: bool = True,
    **csv_kwargs: Any,
) -> pd.DataFrame:
    """``read_table`` then stringify cells (step8 ranked-board hop)."""
    return stringify_cells(
        read_table(
            path,
            sheet=sheet,
            sheet_order=sheet_order,
            prefer_parquet=prefer_parquet,
            **csv_kwargs,
        )
    )


def write_props_parquet(df: pd.DataFrame, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = _prepare_for_parquet(df)
    try:
        body.to_parquet(p, index=False)
    except Exception:
        _stringify_objects(body).to_parquet(p, index=False)
    return p


def read_props_parquet(path: str | Path) -> pd.DataFrame:
    return _read_parquet(Path(path))


def iter_engine_names() -> Iterable[str]:
    return _PARQUET_ENGINES


def xlsxwriter_available() -> bool:
    try:
        import xlsxwriter  # noqa: F401

        return True
    except ImportError:
        return False


def _xl_col_name(idx: int) -> str:
    try:
        from xlsxwriter.utility import xl_col_to_name

        return xl_col_to_name(idx)
    except Exception:
        n = idx + 1
        letters = ""
        while n:
            n, rem = divmod(n - 1, 26)
            letters = chr(65 + rem) + letters
        return letters


def _sanitize_excel_df(df: pd.DataFrame) -> pd.DataFrame:
    out = _dedupe_columns(df if df is not None else pd.DataFrame())
    out.columns = [str(c) for c in out.columns]
    try:
        import numpy as np

        return out.replace([np.inf, -np.inf], np.nan)
    except Exception:
        return out


_TIER_FILL = {
    "A": ("1E8449", "FFFFFF"),
    "B": ("2874A6", "FFFFFF"),
    "C": ("D4AC0D", "000000"),
    "D": ("717D7E", "FFFFFF"),
}


def _style_xlsxwriter_sheet(writer, sheet_name: str, df: pd.DataFrame, header_color: str, header_font: str) -> None:
    wb = writer.book
    ws = writer.sheets[sheet_name]
    hdr = wb.add_format(
        {
            "bold": True,
            "font_color": header_font,
            "bg_color": header_color,
            "align": "center",
            "valign": "vcenter",
            "text_wrap": True,
        }
    )
    cols = [str(c) for c in df.columns]
    for i, col in enumerate(cols):
        ws.write(0, i, col, hdr)
        ws.set_column(i, i, min(36, max(10, len(col) + 2)))
    ws.freeze_panes(1, 0)
    nrows = len(df)
    ncols = max(len(cols), 1)
    ws.autofilter(0, 0, max(nrows, 1), ncols - 1)
    if nrows == 0 or not cols:
        return
    last_r, last_c = nrows, ncols - 1
    for cand in ("Tier", "tier"):
        if cand not in cols:
            continue
        letter = _xl_col_name(cols.index(cand))
        for grade, (bg, fg) in _TIER_FILL.items():
            fmt = wb.add_format({"bg_color": bg, "font_color": fg})
            ws.conditional_format(
                1,
                0,
                last_r,
                last_c,
                {
                    "type": "formula",
                    "criteria": f'=${letter}2="{grade}"',
                    "format": fmt,
                },
            )
        break
    for cand in ("Direction", "direction"):
        if cand not in cols:
            continue
        cidx = cols.index(cand)
        letter = _xl_col_name(cidx)
        over = wb.add_format({"bg_color": "C8F7C5", "bold": True})
        under = wb.add_format({"bg_color": "F7C5C5", "bold": True})
        ws.conditional_format(
            1, cidx, last_r, cidx,
            {"type": "formula", "criteria": f'=${letter}2="OVER"', "format": over},
        )
        ws.conditional_format(
            1, cidx, last_r, cidx,
            {"type": "formula", "criteria": f'=${letter}2="UNDER"', "format": under},
        )
        break


def write_excel_sheets(
    path: str | Path,
    sheets: dict[str, pd.DataFrame],
    *,
    header_color: str = "1C1C1C",
    header_font: str = "FFFFFF",
    style: bool = True,
) -> Path:
    """Bulk-write an .xlsx. Prefers xlsxwriter (~5x vs openpyxl cell loops)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    cleaned: dict[str, pd.DataFrame] = {}
    for name, df in sheets.items():
        key = str(name or "Sheet")[:31]
        if key in cleaned:
            key = f"{key[:28]}_{len(cleaned)}"
        cleaned[key] = _sanitize_excel_df(df)

    engine = "xlsxwriter" if xlsxwriter_available() else "openpyxl"
    kwargs: dict[str, Any] = {}
    if engine == "xlsxwriter":
        kwargs["engine_kwargs"] = {"options": {"strings_to_urls": False}}
    with pd.ExcelWriter(p, engine=engine, **kwargs) as writer:
        for name, df in cleaned.items():
            body = df if not df.empty else pd.DataFrame(columns=df.columns)
            body.to_excel(writer, sheet_name=name, index=False)
            if style and engine == "xlsxwriter":
                try:
                    _style_xlsxwriter_sheet(writer, name, body, header_color, header_font)
                except Exception as exc:
                    print(f"[table_io] WARN xlsx style skipped ({name}): {exc}")
    print(f"[table_io] excel -> {p.name} engine={engine} sheets={list(cleaned)}")
    return p
