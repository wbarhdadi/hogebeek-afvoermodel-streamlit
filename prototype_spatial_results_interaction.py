"""THROWAWAY UI PROTOTYPE — spatial results contract and PyDeck interaction.

Question: how should catchment polygons, maximum-depth rasters, comparison
deltas, selection, and invalid spatial data work together in the map-first
Hoge Beek results workspace?

Run: streamlit run prototype_spatial_results_interaction.py
Switch: ?variant=A, ?variant=B, or ?variant=C (or use the bottom switcher).
This uses fabricated data only; it is not production code or model output.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st


st.set_page_config(page_title="Prototype — spatial results", layout="wide")

VARIANTS = {
    "A": "Stroomgebieden eerst",
    "B": "Diepteraster eerst",
    "C": "Verschil eerst",
}
DEPTH_CLASSES = [
    ("< 0,01 m", "#f7fbff"), ("0,01–0,25 m", "#c6dbef"),
    ("0,25–0,50 m", "#6baed6"), ("0,50–1 m", "#3182bd"),
    ("1–2 m", "#08519c"), ("> 2 m", "#08306b"),
]
CATCHMENTS = pd.DataFrame([
    {"id": "SB-01", "naam": "Bovenloop", "max_depth_m": .18, "peak_m3s": .42, "flooded_ha": 1.2, "delta_depth_m": -.04, "valid": True, "polygon": [[[3.260, 50.823], [3.276, 50.823], [3.279, 50.815], [3.263, 50.813]]]},
    {"id": "SB-02", "naam": "Dorpskern", "max_depth_m": .46, "peak_m3s": .81, "flooded_ha": 3.5, "delta_depth_m": -.11, "valid": True, "polygon": [[[3.280, 50.819], [3.298, 50.819], [3.300, 50.809], [3.281, 50.808]]]},
    {"id": "SB-03", "naam": "Benedenloop", "max_depth_m": .72, "peak_m3s": 1.14, "flooded_ha": 6.7, "delta_depth_m": -.03, "valid": True, "polygon": [[[3.301, 50.812], [3.321, 50.812], [3.323, 50.802], [3.303, 50.801]]]},
    {"id": "SB-04", "naam": "Monding", "max_depth_m": .29, "peak_m3s": .63, "flooded_ha": 2.1, "delta_depth_m": 0.00, "valid": False, "polygon": [[[3.324, 50.806], [3.341, 50.806], [3.343, 50.797], [3.326, 50.796]]]},
])


def initialise() -> None:
    st.session_state.setdefault("spatial_variant", "A")
    st.session_state.setdefault("spatial_selected", "SB-02")
    st.session_state.setdefault("spatial_run", "Maatregelen oktober")
    st.session_state.setdefault("spatial_show_raster", True)
    st.session_state.setdefault("spatial_large_raster", False)


def selected() -> pd.Series:
    return CATCHMENTS.set_index("id").loc[st.session_state.spatial_selected]


def depth_colour(depth: float) -> list[int]:
    colours = [[247, 251, 255], [198, 219, 239], [107, 174, 214], [49, 130, 189], [8, 81, 156], [8, 48, 107]]
    return colours[next(i for i, edge in enumerate([.01, .25, .50, 1, 2, float("inf")]) if depth < edge)]


def raster_cells() -> pd.DataFrame:
    # Deliberately capped display cells: a production map must not turn every
    # source raster cell into a browser feature.
    rows = []
    density = 18 if st.session_state.spatial_large_raster else 7
    for item in CATCHMENTS.itertuples():
        if not item.valid:
            continue
        west, north = item.polygon[0][0]
        for x in range(density):
            for y in range(density):
                depth = max(0.0, item.max_depth_m * (1 - (x + y) / (2 * density)))
                rows.append({"position": [west + .0012 * x, north - .0012 * y], "depth_m": depth, "colour": depth_colour(depth) + [170]})
    return pd.DataFrame(rows)


def deck(show_raster: bool, comparison: bool = False) -> pdk.Deck:
    polygons = CATCHMENTS.copy()
    polygons["fill"] = polygons.apply(
        lambda row: ([225, 87, 89, 220] if row.id == st.session_state.spatial_selected else depth_colour(row.max_depth_m) + [125]) if row.valid else [120, 120, 120, 75], axis=1
    )
    polygons["border"] = polygons["id"].eq(st.session_state.spatial_selected).map({True: [225, 87, 89, 255], False: [35, 65, 80, 220]})
    if comparison:
        polygons["fill"] = polygons["delta_depth_m"].map(lambda value: [46, 125, 50, 180] if value < 0 else [190, 50, 40, 120])
    layers = [pdk.Layer("PolygonLayer", polygons, get_polygon="polygon", get_fill_color="fill", get_line_color="border", line_width_min_pixels=2, pickable=True)]
    if show_raster:
        cells = raster_cells()
        layers.append(pdk.Layer("ScatterplotLayer", cells, get_position="position", get_fill_color="colour", get_radius=65 if not st.session_state.spatial_large_raster else 28, pickable=True))
    return pdk.Deck(
        initial_view_state=pdk.ViewState(latitude=50.808, longitude=3.302, zoom=12.3, pitch=0),
        layers=layers,
        tooltip={"html": "<b>{naam} · {id}</b><br/>Max. waterdiepte: {max_depth_m} m<br/>Piekafvoer: {peak_m3s} m³/s<br/>Overstroomd areaal: {flooded_ha} ha", "style": {"backgroundColor": "#172b35"}},
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    )


def map_panel(show_raster: bool, comparison: bool = False) -> None:
    selection = st.pydeck_chart(deck(show_raster, comparison), height=460, on_select="rerun", selection_mode="single-object")
    picked = selection.selection.get("objects", {}).get("PolygonLayer", []) if selection else []
    if picked and picked[0].get("id") in set(CATCHMENTS.id):
        st.session_state.spatial_selected = picked[0]["id"]
    st.caption("Hover toont waarden. Klik op een stroomgebied om kaart, kengetallen en hydrogram te koppelen.")


def legend(comparison: bool = False) -> None:
    if comparison:
        st.caption("Groen = lagere maximale waterdiepte dan basis · rood = hoger · grijs = ruimtelijk resultaat ongeldig of ontbrekend.")
    else:
        st.caption(" · ".join(f"{label}" for label, _ in DEPTH_CLASSES) + "  — maximale waterdiepte")


def detail() -> None:
    item = selected()
    if not item.valid:
        st.warning(f"{item['naam']} heeft geen geldig ruimtelijk resultaat (ongeldige CRS, geometrie of rasterdekking). De kaart toont geen dieptelaag; tabellen en het hydrogram blijven beschikbaar.")
    a, b, c = st.columns(3)
    a.metric("Max. waterdiepte", "—" if not item.valid else f"{item['max_depth_m']:.2f} m")
    b.metric("Piekafvoer", f"{item['peak_m3s']:.2f} m³/s")
    c.metric("Overstroomd areaal", "—" if not item.valid else f"{item['flooded_ha']:.1f} ha")
    started = datetime(2025, 10, 3, 8)
    series = pd.DataFrame({"tijd": [started + timedelta(hours=h) for h in range(18)], "afvoer": [max(0, item.peak_m3s * (1 - abs(h - 8) / 7)) for h in range(18)]})
    st.altair_chart(alt.Chart(series).mark_line(color="#1e5f87", strokeWidth=3).encode(x=alt.X("tijd:T", title=None), y=alt.Y("afvoer:Q", title="Afvoer [m³/s]"), tooltip=["tijd:T", alt.Tooltip("afvoer:Q", format=".3f")]).properties(height=180), width="stretch")


def state_dump() -> None:
    st.sidebar.markdown("**Volledige prototype-status**")
    st.sidebar.json({"scenario": st.session_state.spatial_run, "selected_subcatchment": st.session_state.spatial_selected, "depth_layer": "display decimation" if st.session_state.spatial_large_raster else "overview cells", "invalid_spatial_results": CATCHMENTS.loc[~CATCHMENTS.valid, "id"].tolist()})


def controls() -> None:
    labels = {row.id: f"{row.id} · {row.naam}" for row in CATCHMENTS.itertuples()}
    st.selectbox("Scenario", ["Maatregelen oktober", "Basisscenario oktober"], key="spatial_run")
    st.selectbox("Geselecteerd stroomgebied", list(labels), format_func=labels.get, key="spatial_selected")
    st.checkbox("Toon maximale-waterdiepte rasterlaag", key="spatial_show_raster")
    st.checkbox("Simuleer groot raster (weergave wordt uitgedund)", key="spatial_large_raster")


def variant_a() -> None:
    st.header("Kaartoverzicht per stroomgebied")
    st.write("De snelle, altijd beschikbare overzichtslaag is een klikbaar stroomgebiedpolygoon. De rasterlaag is context voor het geselecteerde gebied, nooit de primaire selectielaag.")
    left, right = st.columns([3, 2])
    with left:
        map_panel(st.session_state.spatial_show_raster)
        legend()
    with right:
        st.subheader(f"{selected()['naam']} · detail")
        detail()


def variant_b() -> None:
    st.header("Dieptekaart als onderzoekslaag")
    st.write("Hier draagt het raster de hoofdboodschap. Vergelijk de leesbaarheid en laadtijd met de stroomgebied-eerste variant, vooral bij grote rasters.")
    map_panel(True)
    legend()
    st.subheader(f"{selected()['naam']} · gekoppeld hydrogram")
    detail()


def variant_c() -> None:
    st.header("Vergelijking als besliskaart")
    st.write("De kaart toont het verschil in maximale waterdiepte tussen een basis- en maatregelen-scenario. Absolute diepteklassen blijven beschikbaar via variant A of B.")
    map_panel(False, comparison=True)
    legend(comparison=True)
    st.subheader(f"{selected()['naam']} · resultaat in geselecteerd scenario")
    detail()


def switcher(variant: str) -> None:
    choices = list(VARIANTS)
    st.markdown(f"""<style>.switcher{{position:fixed;bottom:1rem;left:50%;transform:translateX(-50%);z-index:999;background:#172b35;color:#fff;padding:.6rem 1rem;border-radius:999px}}.switcher a{{color:#fff;padding:.4rem;text-decoration:none}}</style><div class='switcher'><a href='?variant={choices[(choices.index(variant)-1)%3]}'>←</a> {variant} · {VARIANTS[variant]} <a href='?variant={choices[(choices.index(variant)+1)%3]}'>→</a></div>""", unsafe_allow_html=True)


initialise()
variant = str(st.query_params.get("variant", "A")).upper()
variant = variant if variant in VARIANTS else "A"
st.title("Hoge Beek · ruimtelijke resultaten")
st.caption("THROWAWAY UI-PROTOTYPE · verzonnen data, geen bestandsinvoer, geen modelberekening of opslag")
with st.sidebar:
    controls()
    state_dump()
{"A": variant_a, "B": variant_b, "C": variant_c}[variant]()
switcher(variant)
