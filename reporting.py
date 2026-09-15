"""Result tables and labels for stakeholder-facing model outputs."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd


FLOODED_DEPTH_CLASSES = (
    (0.01, 0.25, "flooded_area_0_01_to_0_25m_ha"),
    (0.25, 0.50, "flooded_area_0_25_to_0_50m_ha"),
    (0.50, 1.00, "flooded_area_0_50_to_1m_ha"),
    (1.00, 2.00, "flooded_area_1_to_2m_ha"),
    (2.00, np.inf, "flooded_area_over_2m_ha"),
)


def build_output_tables(
    times: np.ndarray,
    outflow_volumes_m3: dict[int, np.ndarray],
    waterlevels_m_taw: dict[int, np.ndarray],
    timestep_seconds: float,
    rainfall_depths_mm: np.ndarray | None = None,
    terrain_by_catchment: dict[int, np.ndarray] | None = None,
    pixel_area_m2: float | None = None,
    terminal_outlet_ids: set[int] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build export-ready terminal-outlet, subcatchment, and total result tables.

    Every discharge column is a terminal-outlet hydrograph.  ``terminal_outlet_ids``
    selects them from ``outflow_volumes_m3`` so routed upstream water is not
    reported twice. The summary includes every supplied subcatchment. The
    ``whole_catchment`` summary row sums depth-class areas from the
    individual subcatchment rows; its classes are mutually exclusive.
    """
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
        if terminal_outlet_ids is None or catchment_id in terminal_outlet_ids:
            discharges[f"discharge_catchment_{catchment_id}_m3s"] = discharge_m3s
            waterlevels[f"water_level_catchment_{catchment_id}_m_taw"] = levels
        row = {
            "catchment_id": catchment_id,
            "summary_scope": "subcatchment",
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
            for lower_bound, upper_bound, column in FLOODED_DEPTH_CLASSES:
                row[column] = float(
                    ((valid_depths >= lower_bound) & (valid_depths < upper_bound)).sum()
                    * pixel_area_m2 / 10_000.0
                )
        summary_rows.append(row)

    summary = pd.DataFrame(summary_rows)
    if terrain_by_catchment is not None and pixel_area_m2 is not None and not summary.empty:
        class_columns = [depth_class[2] for depth_class in FLOODED_DEPTH_CLASSES]
        whole_catchment = {
            "catchment_id": "whole_catchment",
            "summary_scope": "sum_of_subcatchments",
            **{column: summary[column].sum() for column in class_columns},
        }
        summary = pd.concat([summary, pd.DataFrame([whole_catchment])], ignore_index=True)

    return discharges, waterlevels, summary


def build_results_zip(
    discharges: pd.DataFrame, waterlevels: pd.DataFrame, summary: pd.DataFrame,
    rainfall: pd.DataFrame, rainfall_filename: str, depth_files: list[Path] | None = None,
) -> bytes:
    """Package the documented CSV exports and optional maximum-depth GeoTIFFs."""
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, table in (
            ("catchment_discharges_m3s.csv", discharges),
            ("catchment_waterlevels_m_taw.csv", waterlevels),
            ("catchment_summary.csv", summary),
            (rainfall_filename, rainfall),
        ):
            zf.writestr(filename, table.to_csv(index=False))
        for depth_file in depth_files or []:
            zf.write(depth_file, f"max_waterdepth/{depth_file.name}")
    return archive.getvalue()
