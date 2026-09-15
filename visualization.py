"""Charts for exploring simulated subcatchment results."""

from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd


WATERDEPTH_CLASSES = ["<0.01 m", "0.01-0.25 m", "0.25-0.50 m", "0.50-1 m", "1-2 m", ">2 m"]
WATERDEPTH_COLORS = ["#f7fbff", "#c6dbef", "#6baed6", "#3182bd", "#08519c", "#08306b"]


def classify_waterdepth(maximum_depth_m: np.ndarray) -> np.ndarray:
    """Assign each finite raster cell to the agreed maximum water-depth class."""
    depths = np.asarray(maximum_depth_m, dtype=float)
    return np.select(
        [depths < 0.01, depths < 0.25, depths < 0.50, depths < 1.0, depths <= 2.0],
        WATERDEPTH_CLASSES[:-1], default=WATERDEPTH_CLASSES[-1],
    )


def build_waterdepth_map(
    maximum_depth_m: np.ndarray, x_origin: float, y_origin: float, pixel_size: float
) -> alt.Chart:
    """Render the selected subcatchment's maximum water-depth raster by cell."""
    depths = np.asarray(maximum_depth_m, dtype=float)
    rows, columns = np.indices(depths.shape)
    valid = np.isfinite(depths)
    map_data = pd.DataFrame({
        "x": x_origin + (columns[valid] + 0.5) * pixel_size,
        "y": y_origin - (rows[valid] + 0.5) * pixel_size,
        "water_depth_class": classify_waterdepth(depths)[valid],
    })
    return alt.Chart(map_data).mark_rect().encode(
        x=alt.X("x:Q", title="X"),
        y=alt.Y("y:Q", title="Y"),
        color=alt.Color(
            "water_depth_class:N", title="Maximale waterdiepte",
            scale=alt.Scale(domain=WATERDEPTH_CLASSES, range=WATERDEPTH_COLORS),
        ),
        tooltip=["water_depth_class:N"],
    ).properties(title="Maximale waterdieptekaart")


def build_detail_charts(
    rainfall: pd.DataFrame,
    discharges: pd.DataFrame,
    waterlevels: pd.DataFrame,
    catchment_id: int,
    timestep_minutes: int,
) -> tuple[alt.VConcatChart, alt.Chart]:
    """Build linked rainfall/discharge panels and a water-level chart."""
    discharge_column = f"discharge_catchment_{catchment_id}_m3s"
    waterlevel_column = f"water_level_catchment_{catchment_id}_m_taw"

    rainfall_chart = alt.Chart(rainfall).mark_bar(color="#4C78A8").encode(
        x=alt.X("datetime:T", title="Datum en tijd"),
        y=alt.Y("rainfall_depth_mm:Q", title=f"Neerslagdiepte [mm/{timestep_minutes} min]"),
        tooltip=["datetime:T", alt.Tooltip("rainfall_depth_mm:Q", format=".3f")],
    ).properties(title="Neerslag")
    discharge_chart = alt.Chart(discharges).mark_line(color="#E45756").encode(
        x=alt.X("datetime:T", title="Datum en tijd"),
        y=alt.Y(f"{discharge_column}:Q", title="Afvoer [m3/s]"),
        tooltip=["datetime:T", alt.Tooltip(f"{discharge_column}:Q", format=".5g")],
    ).properties(title=f"Hydrogram - stroomgebied {catchment_id}")
    waterlevel_chart = alt.Chart(waterlevels).mark_line(color="#72B7B2").encode(
        x=alt.X("datetime:T", title="Datum en tijd"),
        y=alt.Y(f"{waterlevel_column}:Q", title="Waterpeil [m TAW]"),
        tooltip=["datetime:T", alt.Tooltip(f"{waterlevel_column}:Q", format=".3f")],
    ).properties(title=f"Waterpeil - stroomgebied {catchment_id}")

    return alt.vconcat(rainfall_chart, discharge_chart).resolve_scale(x="shared"), waterlevel_chart
