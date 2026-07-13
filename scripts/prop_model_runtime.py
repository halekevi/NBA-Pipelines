"""Runtime knobs for per-sport prop_model use in step7."""
from __future__ import annotations

import os


def skip_prop_model_inference() -> bool:
    """
    When True, step7 skips loading / predicting with prop_model_*.pkl.

    Production tickets use step7b's unified edge model for ml_prob (overwrites step7).
    Default: skip (faster pipeline). Restore with PROPORACLE_STEP7_SKIP_PROP_MODEL=0.
    """
    raw = os.getenv("PROPORACLE_STEP7_SKIP_PROP_MODEL", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def skip_prop_model_log(sport: str) -> None:
    print(
        f"⏩ [{sport}] skipping prop_model inference "
        f"(step7b owns production ml_prob; PROPORACLE_STEP7_SKIP_PROP_MODEL=0 to restore)"
    )
