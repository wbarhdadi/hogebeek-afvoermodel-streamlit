"""Charts for exploring simulated subcatchment results."""

from __future__ import annotations

import altair as alt
import pandas as pd


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
