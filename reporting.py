"""Result tables and labels for stakeholder-facing model outputs."""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_output_tables(
    times: np.ndarray,
    outflow_volumes_m3: dict[int, np.ndarray],
    waterlevels_m_taw: dict[int, np.ndarray],
    timestep_seconds: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build export-ready discharge, water-level, and summary tables."""
    discharges = pd.DataFrame({"datetime": pd.to_datetime(times)})
    waterlevels = pd.DataFrame({"datetime": pd.to_datetime(times)})
    summary_rows = []

    for catchment_id in sorted(outflow_volumes_m3):
        volumes = np.asarray(outflow_volumes_m3[catchment_id], dtype=float)
        discharge_m3s = volumes / timestep_seconds
        levels = np.asarray(waterlevels_m_taw[catchment_id], dtype=float)
        discharges[f"discharge_catchment_{catchment_id}_m3s"] = discharge_m3s
        waterlevels[f"water_level_catchment_{catchment_id}_m_taw"] = levels
        summary_rows.append(
            {
                "catchment_id": catchment_id,
                "total_outflow_m3": float(volumes.sum()),
                "peak_discharge_m3s": float(discharge_m3s.max(initial=0.0)),
                "max_water_level_m_taw": float(np.nanmax(levels)),
            }
        )

    return discharges, waterlevels, pd.DataFrame(summary_rows)
