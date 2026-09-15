"""Validated rainfall inputs for the Hoge Beek simulation.

The model consumes rainfall *depth per model timestep* in millimetres.  This
module is the single conversion seam for both Waterinfo and uploaded CSV data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


DATETIME_COLUMN = "datetime"
DEPTH_COLUMN = "rainfall_mm"
INTENSITY_COLUMN = "rainfall_mmh"


def waterinfo_value_kind(metadata: pd.DataFrame) -> tuple[str, str]:
    """Return the unit kind and displayed unit for a Waterinfo series.

    Waterinfo's ``Value`` has no unit in the values response; the unit lives in
    the series metadata.  Never infer it from magnitude or station name.
    """
    if metadata.empty or "ts_unitsymbol" not in metadata.columns:
        raise ValueError("Waterinfo gaf geen eenheidsmetadata voor deze tijdreeks.")
    unit = str(metadata.iloc[0]["ts_unitsymbol"]).strip().lower()
    if unit in {"mm/h", "mm/hr", "mm per hour", "millimeter per hour"}:
        return "intensity", "mm/h"
    if unit in {"mm", "millimeter", "millimetre"}:
        return "depth", "mm"
    raise ValueError(f"Onbekende Waterinfo-eenheid: {unit!r}. Kies een geschikte reeks.")


@dataclass(frozen=True)
class RainfallDiagnostics:
    total_depth_mm: float
    peak_interval_depth_mm: float
    peak_intensity_mmh: float
    source_interval_minutes: float


def prepare_rainfall(
    data: pd.DataFrame,
    *,
    value_kind: str,
    timestep_minutes: int,
    datetime_column: str = DATETIME_COLUMN,
    value_column: str | None = None,
) -> pd.DataFrame:
    """Return ``datum`` and ``rf`` (mm per model timestep).

    ``value_kind`` is either ``"depth"`` (mm during each source interval) or
    ``"intensity"`` (mm/h averaged over each source interval).  Source records
    must be regular and the requested model timestep must be an integer multiple
    of the source timestep; this deliberately prevents ambiguous upsampling.
    """
    if value_kind not in {"depth", "intensity"}:
        raise ValueError("Rainfall type must be 'depth' or 'intensity'.")

    expected_value_column = DEPTH_COLUMN if value_kind == "depth" else INTENSITY_COLUMN
    value_column = value_column or expected_value_column
    required = {datetime_column, value_column}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(
            "Rainfall file is missing required column(s): " + ", ".join(sorted(missing))
        )

    rainfall = data[[datetime_column, value_column]].copy()
    rainfall.columns = ["datum", "value"]
    rainfall["datum"] = pd.to_datetime(rainfall["datum"], errors="coerce")
    rainfall["value"] = pd.to_numeric(rainfall["value"], errors="coerce")
    if rainfall.isna().any().any():
        raise ValueError("Rainfall timestamps and values must be present and valid.")
    if (rainfall["value"] < 0).any():
        raise ValueError("Rainfall values cannot be negative.")

    rainfall = rainfall.sort_values("datum")
    if rainfall["datum"].duplicated().any():
        raise ValueError("Rainfall timestamps must be unique.")
    if len(rainfall) < 2:
        raise ValueError("At least two rainfall records are required to determine a timestep.")

    intervals = rainfall["datum"].diff().dropna()
    source_interval = intervals.iloc[0]
    if source_interval <= pd.Timedelta(0) or not (intervals == source_interval).all():
        raise ValueError("Rainfall timestamps must have one regular, gap-free interval.")

    source_minutes = source_interval.total_seconds() / 60
    if timestep_minutes < source_minutes or timestep_minutes % source_minutes != 0:
        raise ValueError(
            "The model timestep must be an integer multiple of the rainfall interval "
            f"({source_minutes:g} minutes); upsampling is not supported."
        )

    frequency = f"{int(timestep_minutes)}min"
    if value_kind == "depth":
        depths = rainfall.set_index("datum")["value"].resample(frequency).sum()
    else:
        average_intensity = rainfall.set_index("datum")["value"].resample(frequency).mean()
        depths = average_intensity * (timestep_minutes / 60.0)

    result = depths.rename("rf").reset_index()
    result["rf"] = result["rf"].astype(float)
    return result


def rainfall_diagnostics(rainfall: pd.DataFrame, timestep_minutes: int) -> RainfallDiagnostics:
    """Summarise normalized rainfall for display and plausibility review."""
    depths = rainfall["rf"].to_numpy(dtype=float)
    return RainfallDiagnostics(
        total_depth_mm=float(np.sum(depths)),
        peak_interval_depth_mm=float(np.max(depths, initial=0.0)),
        peak_intensity_mmh=float(np.max(depths, initial=0.0) * 60.0 / timestep_minutes),
        source_interval_minutes=float(timestep_minutes),
    )
