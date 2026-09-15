"""Result tables and labels for stakeholder-facing model outputs."""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_output_tables(
    times: np.ndarray,
    outflow_volumes_m3: dict[int, np.ndarray],
    waterlevels_m_taw: dict[int, np.ndarray],
    timestep_seconds: float,
    rainfall_depths_mm: np.ndarray | None = None,
    terrain_by_catchment: dict[int, np.ndarray] | None = None,
    pixel_area_m2: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build export-ready discharge, water-level, and summary tables."""
    discharges = pd.DataFrame({"datetime": pd.to_datetime(times)})
    waterlevels = pd.DataFrame({"datetime": pd.to_datetime(times)})
    summary_rows = []
    rainfall_start = None
    if rainfall_depths_mm is not None:
        rainfall_indices = np.flatnonzero(np.asarray(rainfall_depths_mm, dtype=float) > 0.0)
        if rainfall_indices.size:
            rainfall_start = int(rainfall_indices[0])

    for catchment_id in sorted(outflow_volumes_m3):
        volumes = np.asarray(outflow_volumes_m3[catchment_id], dtype=float)
        discharge_m3s = volumes / timestep_seconds
        levels = np.asarray(waterlevels_m_taw[catchment_id], dtype=float)
        discharges[f"discharge_catchment_{catchment_id}_m3s"] = discharge_m3s
        waterlevels[f"water_level_catchment_{catchment_id}_m_taw"] = levels
        row = {
            "catchment_id": catchment_id,
            "total_outflow_m3": float(volumes.sum()),
            "peak_discharge_m3s": float(discharge_m3s.max(initial=0.0)),
            "max_water_level_m_taw": float(np.nanmax(levels)),
        }
        if rainfall_depths_mm is not None:
            row["time_to_peak_minutes"] = np.nan
            if rainfall_start is not None:
                peak_index = int(np.argmax(discharge_m3s))
                row["time_to_peak_minutes"] = (
                    max(0, peak_index - rainfall_start) * timestep_seconds / 60.0
                )
        if terrain_by_catchment is not None and pixel_area_m2 is not None:
            maximum_depth = np.maximum(float(np.nanmax(levels)) - terrain_by_catchment[catchment_id], 0.0)
            valid_depths = maximum_depth[np.isfinite(maximum_depth)]
            row["max_water_depth_m"] = float(valid_depths.max(initial=0.0))
            for threshold, column in ((0.01, "flooded_area_0_01m_ha"), (0.10, "flooded_area_0_10m_ha")):
                row[column] = float(
                    (valid_depths >= threshold).sum() * pixel_area_m2 / 10_000.0
                )
        summary_rows.append(row)

    return discharges, waterlevels, pd.DataFrame(summary_rows)
