"""Parquet I/O for bulk feature / slate columns (DB holds pointers + keys)."""

from proporacle.data.table_io import (  # noqa: F401
    read_props_parquet,
    read_table,
    read_table_str,
    write_parquet_sidecar,
    write_props_parquet,
)

__all__ = [
    "read_props_parquet",
    "write_props_parquet",
    "read_table",
    "read_table_str",
    "write_parquet_sidecar",
]
