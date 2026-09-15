import math
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Tuple, List, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import streamlit as st
from rasterio.transform import from_origin

# Probeer pywaterinfo te importeren
try:
    from pywaterinfo import Waterinfo
    HAS_WATERINFO = True
except ImportError:
    HAS_WATERINFO = False



# ============================================================
# Station ts_id's
# ============================================================

# Keuzelijst stations (Waterinfo ts_id -> stationnaam)
STATIONS = [
    (60834042, "Zarren_P"),
    (60912042, "Ieper_P"),
    (60916042, "Sint-Joris_P"),
    (60920042, "De Panne_P"),
    (60924042, "Poperinge_P"),
    (60928042, "Oostkamp_P"),
    (60932042, "Klemskerke_P"),
    (60936042, "Dudzele_P"),
    (60940042, "Vinderhoute_P"),
    (60944042, "Boekhoute_P"),
    (60948042, "Stekene_P"),
    (60952042, "Ertvelde_P"),
    (60956042, "Melsele_P"),
    (60960042, "Massemen_P"),
    (60964042, "Wilrijk_P"),
    (60968042, "Waregem_P"),
    (60972042, "Geluwe_P"),
    (60976042, "Roeselare_P"),
    (60980042, "Maarke-Kerkem_P"),
    (60984042, "Zingem_P"),
    (60988042, "Liedekerke_P"),
    (60992042, "Moerbeke_P"),
    (60996042, "Denderbelle_P"),
    (61000042, "St-Pieters-Leeuw_P"),
    (61004042, "Korbeek-Dijle_P"),
    (61008042, "Bonheiden_P"),
    (61012042, "Rotselaar_P"),
    (61016042, "Heverlee_P"),
    (61020042, "Nossegem_P"),
    (61024042, "Niel-bij-St.-Truiden_P"),
    (61028042, "Lummen_P"),
    (61032042, "Houthalen_P"),
    (61036042, "Runkelen_P"),
    (61040042, "Tienen_P"),
    (61044042, "Tessenderlo_P"),
    (61048042, "Beverst_P"),
    (61052042, "Herentals_P"),
    (61056042, "Vosselaar_P"),
    (61060042, "Overpelt_P"),
    (61064042, "Loenhout_P"),
    (61068042, "Kanne_P"),
    (61072042, "Neeroeteren_P"),
    (86110042, "Lembeek_P"),
]


# ============================================================
# Streamlit config
# ============================================================

st.set_page_config(
    page_title="Hoge Beek – Travel-time model (Waterinfo, max 3 dagen)",
    layout="wide",
)

st.title("Hoge Beek – Travel-time neerslag–afvoermodel (Waterinfo)")
st.markdown(
    """
Deze app draait het **Hoge Beek** travel-time / bakjesmodel op neerslag
gedownload van **waterinfo.be** met `pywaterinfo`.

- Tijdstap: **gebruikerskeuze** (standaard 1 uur)
- Maximale duur: **3 dagen** (totale simulatieperiode)

**Benodigde inputbestanden:**

- `Hogebeek_geodata.parquet`
- `catchments.gpkg`
- `inlets_pts.gpkg` (geopackage met inlet-punten)
- één of meerdere `maatregelen`-shapefiles (optioneel – punten, lijnen, polygonen)

**Neerslag:**

- Wordt opgehaald bij **Waterinfo (VMM)** met een `ts_id` en begin–einddatum.
- Standaardperiode: **2025-10-03** t.e.m. **2025-10-06** (3 dagen).
- Wordt geaggregeerd naar de gekozen tijdstap en afgekapt op max. 3 dagen.
"""
)

# ============================================================
# MODEL HELPER FUNCTIES
# ============================================================

def compute_effective_recharge(P_current: float, ro_catchment: np.ndarray) -> np.ndarray:
    """Effectieve neerslag (mm) = runoff (%) / 100 * P_current (mm)."""
    ro = ro_catchment.copy().astype(float)
    ro[ro == -9999] = np.nan
    return ro / 100.0 * P_current


DIRECTION_MAP = {
    1: (-1, 1),
    2: (0, 1),
    4: (1, 1),
    8: (1, 0),
    16: (1, -1),
    32: (0, -1),
    64: (-1, -1),
    128: (-1, 0),
}


def route_Q_channel(
    fd_catchment: np.ndarray,
    dtm_catchment: np.ndarray,
    channel_mask: np.ndarray,
    inlet_flow_dict: Dict[int, float],
    inlet_indices_dict: Dict[int, Tuple[int, int]],
    effective_rain_depth: np.ndarray,
    outlet_indices: Tuple[int, int],
    L: float,
) -> np.ndarray:
    """
    Routeer debiet door kanaalcellen met D8-richtingen.
    Volumes in m³ per tijdstap (T).
    """
    H, W = fd_catchment.shape
    candidate_dict_sorted_by_dtm: Dict[Tuple[int, int], float] = {}
    Q = np.zeros_like(fd_catchment, dtype=float)
    processed = set()

    chan_rows, chan_cols = np.where(channel_mask)
    chan_dtm_vals = dtm_catchment[channel_mask]
    sort_idx = np.argsort(chan_dtm_vals)

    for idx in sort_idx:
        r = int(chan_rows[idx])
        c = int(chan_cols[idx])
        cell_rc = (r, c)
        candidate_dict_sorted_by_dtm[cell_rc] = float(dtm_catchment[cell_rc])

    while len(candidate_dict_sorted_by_dtm) > 0:
        current_cell = list(candidate_dict_sorted_by_dtm.keys())[-1]
        candidate_dict_sorted_by_dtm.pop(current_cell)
        prev_Q = 0.0

        if current_cell in processed:
            continue

        while True:
            r, c = current_cell
            if current_cell not in processed:
                exo = 0.0
                # instroom vanuit bovenstroomse deelbekkens
                for inlet_id, inlet_rc in inlet_indices_dict.items():
                    if current_cell == inlet_rc:
                        exo = float(inlet_flow_dict.get(inlet_id, 0.0))

                # laterale instroom van hellingcellen
                lateral = 0.0
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        nr, nc = r + dr, c + dc
                        if nr < 0 or nr >= H or nc < 0 or nc >= W:
                            continue
                        code_n = fd_catchment[nr, nc]
                        if np.isnan(code_n):
                            continue
                        # buur die afwatert naar (r, c)
                        if DIRECTION_MAP.get(int(code_n)) == (r - nr, c - nc):
                            depth = float(effective_rain_depth[nr, nc])
                            if depth > 0.0:
                                # mm -> m, maal pixeloppervlak -> m³
                                lateral += depth * 0.001 * L**2

                Q_here = prev_Q + exo + lateral
                Q[current_cell] = Q_here
                prev_Q = Q_here
                processed.add(current_cell)
            else:
                Q[current_cell] += prev_Q

            if current_cell == tuple(outlet_indices):
                break
            else:
                dir_val = fd_catchment[current_cell]
                if np.isnan(dir_val) or int(dir_val) not in DIRECTION_MAP:
                    break
                dr, dc = DIRECTION_MAP[int(dir_val)]
                current_cell = (r + dr, c + dc)

    return Q


def accumulate_travel_time(
    travel_time: np.ndarray,
    flow_dir: np.ndarray,
    outlet: Tuple[int, int],
) -> np.ndarray:
    """
    Accumuleer reistijden langs D8-stroomlijnen naar de uitlaat.
    Geeft een array terug met totale reistijd [s] van elke cel tot aan de uitlaat.
    """
    rows, cols = travel_time.shape
    acc_time = np.full_like(travel_time, np.nan, dtype=float)
    visited = np.zeros_like(travel_time, dtype=bool)

    def follow_path(r: int, c: int) -> float:
        if np.isnan(travel_time[r, c]):
            return np.nan
        if visited[r, c]:
            return acc_time[r, c]

        dir_val = flow_dir[r, c]
        if np.isnan(dir_val) or int(dir_val) not in DIRECTION_MAP:
            return np.inf

        dr, dc = DIRECTION_MAP[int(dir_val)]
        nr, nc = r + dr, c + dc

        if (r, c) == outlet:
            acc_time[r, c] = 0.0
        else:
            downstream_time = follow_path(nr, nc)
            acc_time[r, c] = travel_time[r, c] + downstream_time

        visited[r, c] = True
        return acc_time[r, c]

    for r in range(rows):
        for c in range(cols):
            follow_path(r, c)

    return acc_time


def tv_convolve_next(PU: np.ndarray, timestep: int) -> float:
    """
    Time-varying convolutie (alleen de volgende outputstap).

    PU: (L, T_out) time-varying unit responses.
        PU[lag, t_out] = respons op tijdstip t_out door een impuls lag stappen eerder.
    """
    PU = np.asarray(PU)
    # Neem altijd de laatste kolom (huidige tijd) en sommeer over alle lags
    return float(PU[:, -1].sum())


# ============================================================
# LOGGING (één plek, genummerd, zonder herhaling)
# ============================================================

if "logs" not in st.session_state:
    st.session_state["logs"] = []


# ============================================================
# STREAMLIT UI – LAYOUT
# ============================================================

with st.sidebar:
    st.header("Invoerbestanden")

    geodata_file = st.file_uploader("Hogebeek_geodata.parquet", type=["parquet"])
    catchments_file = st.file_uploader("catchments.gpkg", type=["gpkg"])

    st.markdown("**Inlets (geopackage)** – upload `inlets_pts.gpkg`")
    inlets_file = st.file_uploader(
        "inlets_pts.gpkg",
        type=["gpkg"],
    )

    st.markdown(
        "**Maatregelen shapefiles (optioneel)** – je mag meerdere shapefiles uploaden "
        "(punten, lijnen, polygonen), telkens met alle bijhorende bestanden."
    )
    maatregelen_files = st.file_uploader(
        "maatregelen.* (alle shapefile-bestanden, optioneel; meerdere toegestaan)",
        accept_multiple_files=True,
    )

    st.markdown("---")
    st.subheader("Neerslag – Waterinfo (VMM)")

    if not HAS_WATERINFO:
        st.error("`pywaterinfo` is niet geïnstalleerd. Installeer met `pip install pywaterinfo`.")
        timestep_minutes = 60
    else:
        # Toon labels in dropdown, maar bewaar echte ts_id apart
        station_labels = [f"{name} ({sid})" for sid, name in STATIONS]
        
        # Default: wat je nu als value gebruikte ("210400042") zit niet in je lijst,
        # dus kiezen we een veilige default (eerste item). Je kan dit aanpassen.
        default_index = 0
        
        selected_label = st.selectbox(
            "Station (neerslagreeks)",
            options=station_labels,
            index=default_index,
            help="Kies het station; de juiste Waterinfo ts_id wordt automatisch gebruikt.",
        )
        
        # Haal ts_id uit het gekozen label (alles tussen haakjes)
        selected_id = selected_label.split("(")[-1].rstrip(")")
        ts_id = str(selected_id)

        
        start_date = st.text_input("Begindatum (JJJJ-MM-DD)", value="2025-10-03")
        end_date = st.text_input("Einddatum (JJJJ-MM-DD)", value="2025-10-06")
        timestep_minutes = st.number_input(
            "Modeltijdstap [minuten]",
            min_value=5,
            max_value=180,
            value=60,
            step=5,
            help="Tijdstap voor aggregatie van neerslag en modeltijd (max. 3 dagen totale duur).",
        )
        st.caption(
            "Neerslag wordt opgehaald voor [start, einde], geaggregeerd naar de gekozen tijdstap "
            "en afgekapt op maximaal 3 dagen."
        )

    st.markdown("---")
    st.subheader("Modelparameters")

    slope_factor = st.number_input("Factor helling (D8slope)", value=1.0)
    manning_factor = st.number_input("Factor Manning n", value=1.0)
    runoff_factor = st.number_input("Factor runoff (%)", value=1.0)
    A_threshold = st.number_input(
        "Drempel stroomopwaarts gebied A_threshold [m²] (kanaalcel)",
        value=100000.0,
        min_value=0.0,
    )

    st.markdown("---")
    export_depths = st.checkbox("Maximale waterdiepte per stroomgebied exporteren (GeoTIFF)", value=True)
    run_button = st.button("Model draaien")


col_left, col_right = st.columns([2, 1])

with col_left:
    st.subheader("Status / logboek")
    log_placeholder = st.empty()
    progress_bar = st.progress(0)
    timestep_text = st.empty()

with col_right:
    st.subheader("Resultaten")

    st.markdown("#### Mogelijke maatregelen en geometrietype")
    maatregelen_info = pd.DataFrame(
        {
            "Naam maatregel": [
                "drempel",
                "gracht",
                "houthaksel",
                "houtkant",
                "infiltratiestraat",
                "swale",
                "bufferbekken",
                "grasbufferstrook",
                "ontharding",
                "sponsakker",
                "sponstuin",
            ],
            "Geometrietype": [
                "punt",
                "lijn",
                "lijn",
                "lijn",
                "lijn",
                "lijn",
                "polygoon",
                "polygoon",
                "polygoon",
                "polygoon",
                "polygoon",
            ],
        }
    )
    st.table(maatregelen_info)

    plot_container = st.empty()
    download_container = st.empty()


def render_logs():
    """Toon alle logs in één blok, genummerd."""
    if st.session_state["logs"]:
        txt = "\n".join(
            f"{i}. {m}" for i, m in enumerate(st.session_state["logs"], start=1)
        )
    else:
        txt = "_Nog geen stappen..._"
    log_placeholder.markdown(txt)


def log(message: str):
    """Voeg één stap toe en herteken het logboek."""
    st.session_state["logs"].append(str(message))
    render_logs()


# Toon bestaande logs (bij her-run)
render_logs()


# ------------------------------------------------------------
# Maatregelen toepassen
# ------------------------------------------------------------

def apply_maatregelen(
    geodata: gpd.GeoDataFrame,
    maatregelen_gdf: Optional[gpd.GeoDataFrame],
) -> gpd.GeoDataFrame:
    """
    Pas maatregelen toe op geodata:
    - behoud alleen maatregelen met niet-lege 'type'
    - behoud enkel maatregelen die een stroomgebied snijden
    - log hoeveel maatregelen verwerkt worden
    - pas DTM / helling / runoff / Manning aan per maatregeltype.
    """
    if maatregelen_gdf is None:
        return geodata

    if "type" not in maatregelen_gdf.columns:
        log("Maatregelen-laag heeft geen kolom 'type' – maatregelen worden overgeslagen.")
        return geodata

    # Enkel maatregelen met type
    maatregelen_gdf = maatregelen_gdf[~maatregelen_gdf["type"].isna()].copy()
    if maatregelen_gdf.empty:
        log("Geen maatregelen met ingevuld 'type' gevonden – niets toe te passen.")
        return geodata

    # Enkel maatregelen die een stroomgebied snijden
    maatregelen_gdf = gpd.sjoin(
        maatregelen_gdf,
        catchments[["uitstroompunt_nummer", "geometry"]],
        how="inner",
        predicate="intersects",
    ).drop(columns=["index_right"])

    if maatregelen_gdf.empty:
        log("Geen maatregelen die stroomgebieden snijden – niets toe te passen.")
        return geodata

    # Log aantal maatregelen
    n_maatregelen = len(maatregelen_gdf)
    log(
        f"Stap: maatregelen toepassen – {n_maatregelen} maatregel(en) met type + intersectie met stroomgebieden."
    )

    # Zorg dat x/y aanwezig zijn
    if "x" not in geodata.columns or "y" not in geodata.columns:
        geodata = geodata.copy()
        geodata["x"] = geodata.geometry.x
        geodata["y"] = geodata.geometry.y

    # DTM-kolom die in het model wordt gebruikt
    if "breachedburnedDTM_5m" not in geodata.columns:
        raise KeyError(
            "Kolom 'breachedburnedDTM_5m' ontbreekt in geodata; "
            "nodig voor DTM-aanpassingen door maatregelen."
        )

    # Minimum DTM per stroomgebied
    min_dtm_per_catchment = geodata.groupby("catchment_id")["breachedburnedDTM_5m"].min()

    # Doorloop alle maatregelen
    for _, maatregel in maatregelen_gdf.iterrows():
        geom = maatregel.geometry
        geom_type = geom.geom_type
        mtype = str(maatregel.type).lower()

        # --------------------------------------------------
        # PUNT-MAATREGELEN
        # --------------------------------------------------
        if geom_type in ("Point", "MultiPoint"):
            if mtype == "drempel":
                # Zoek dichtstbijzijnde cel in geodata (op basis van x,y)
                px, py = geom.x, geom.y

                xs = np.sort(geodata["x"].unique())
                ys = np.sort(geodata["y"].unique())

                col_idx = int(np.abs(xs - px).argmin())
                row_idx = int(np.abs(ys - py).argmin())

                x_val = xs[col_idx]
                y_val = ys[row_idx]

                candidate = geodata[(geodata["x"] == x_val) & (geodata["y"] == y_val)]
                if candidate.empty:
                    continue

                cell_idx = candidate.index[0]
                catchment_id = geodata.loc[cell_idx, "catchment_id"]

                # laagste helling in het stroomgebied
                min_slope = geodata.loc[
                    geodata["catchment_id"] == catchment_id, "D8slope"
                ].min()
                geodata.at[cell_idx, "D8slope"] = min_slope

                min_dtm = min_dtm_per_catchment.loc[catchment_id]
                geodata.at[cell_idx, "breachedburnedDTM_5m"] = min_dtm - 0.3

        # --------------------------------------------------
        # LIJN-MAATREGELEN
        # --------------------------------------------------
        if geom_type in ("LineString", "MultiLineString"):
            buffer = geom.buffer(5)

            if mtype == "gracht":
                idxs = geodata[geodata.geometry.within(buffer)].index
                if len(idxs) > 0:
                    min_slope = geodata.loc[idxs, "D8slope"].min()
                    geodata.loc[idxs, "D8slope"] = min_slope
                    for cell_idx in idxs:
                        catchment_id = geodata.loc[cell_idx, "catchment_id"]
                        min_dtm = min_dtm_per_catchment.loc[catchment_id]
                        geodata.at[cell_idx, "breachedburnedDTM_5m"] = min_dtm - 0.3

            if mtype == "houthaksel":
                idxs = geodata[geodata.geometry.within(buffer)].index
                if len(idxs) > 0:
                    min_slope = geodata.loc[idxs, "D8slope"].min()
                    geodata.loc[idxs, "D8slope"] = min_slope
                    max_manning = geodata.loc[idxs, "manning_n"].max()
                    geodata.loc[idxs, "manning_n"] = max_manning

            if mtype == "houtkant":
                idxs = geodata[geodata.geometry.within(buffer)].index
                if len(idxs) > 0:
                    min_slope = geodata.loc[idxs, "D8slope"].min()
                    geodata.loc[idxs, "D8slope"] = min_slope
                    geodata.loc[idxs, "manning_n"] = geodata.loc[idxs, "manning_n"] * 2

            if mtype == "infiltratiestraat":
                idxs = geodata[geodata.geometry.within(buffer)].index
                if len(idxs) > 0:
                    geodata.loc[idxs, "runoff_ori_clipped"] = 0.0
                    geodata.loc[idxs, "manning_n"] = geodata.loc[idxs, "manning_n"] * 2

            if mtype == "swale":
                idxs = geodata[geodata.geometry.within(buffer)].index
                if len(idxs) > 0:
                    geodata.loc[idxs, "runoff_ori_clipped"] = 0.0
                    for cell_idx in idxs:
                        catchment_id = geodata.loc[cell_idx, "catchment_id"]
                        min_dtm = min_dtm_per_catchment.loc[catchment_id]
                        geodata.at[cell_idx, "breachedburnedDTM_5m"] = min_dtm - 0.2

        # --------------------------------------------------
        # POLYGOON-MAATREGELEN
        # --------------------------------------------------
        if geom_type in ("Polygon", "MultiPolygon"):
            buffer = geom

            if mtype == "bufferbekken":
                idxs = geodata[geodata.geometry.within(buffer)].index
                if len(idxs) > 0:
                    geodata.loc[idxs, "runoff_ori_clipped"] = 0.0

                    if hasattr(maatregel, "volume") and maatregel.volume is not None:
                        totale_oppervlakte = len(idxs) * (5 * 5)  # 5m x 5m
                        volume_m3 = float(maatregel.volume)
                        depth_lowering = volume_m3 / totale_oppervlakte
                        for cell_idx in idxs:
                            catchment_id = geodata.loc[cell_idx, "catchment_id"]
                            min_dtm = min_dtm_per_catchment.loc[catchment_id]
                            geodata.at[cell_idx, "breachedburnedDTM_5m"] = (
                                min_dtm - depth_lowering
                            )
                    else:
                        for cell_idx in idxs:
                            catchment_id = geodata.loc[cell_idx, "catchment_id"]
                            min_dtm = min_dtm_per_catchment.loc[catchment_id]
                            geodata.at[cell_idx, "breachedburnedDTM_5m"] = min_dtm - 0.5

            if mtype == "grasbufferstrook":
                idxs = geodata[geodata.geometry.within(buffer)].index
                if len(idxs) > 0:
                    geodata.loc[idxs, "runoff_ori_clipped"] = 0.0
                    geodata.loc[idxs, "D8slope"] = geodata.loc[idxs, "D8slope"] / 2.0
                    max_manning = geodata.loc[idxs, "manning_n"].max()
                    geodata.loc[idxs, "manning_n"] = max_manning

            if mtype == "ontharding":
                idxs = geodata[geodata.geometry.within(buffer)].index
                for cell_idx in idxs:
                    ro_val = geodata.at[cell_idx, "runoff_ori_clipped"]
                    if ro_val > 50.0:
                        nieuw_ro = 50.0 + (ro_val - 50.0) / 2.0
                        geodata.at[cell_idx, "runoff_ori_clipped"] = nieuw_ro

            if mtype in ("sponsakker", "sponstuin"):
                idxs = geodata[geodata.geometry.within(buffer)].index
                if len(idxs) > 0:
                    geodata.loc[idxs, "runoff_ori_clipped"] = 0.0
                    geodata.loc[idxs, "manning_n"] = geodata.loc[idxs, "manning_n"] * 2

    return geodata


def points_to_array(
    gdf: gpd.GeoDataFrame,
    variable_names: List[str],
    return_transform: bool = False,
):
    """
    Zet punt-gebaseerde cellen met attributen om naar 2D rasters op een regelmatig grid.
    Rij 0 ligt aan de noordrand (max Y), zoals gebruikelijk bij rasters.
    """
    xs = np.sort(gdf["x"].unique())
    ys = np.sort(gdf["y"].unique())
    nx = len(xs)
    ny = len(ys)

    x_to_col = {x: i for i, x in enumerate(xs)}
    y_to_row = {y: i for i, y in enumerate(ys[::-1])}

    template = np.full((ny, nx), np.nan, dtype=float)
    arr_dict = {}

    for var_name in variable_names:
        arr = template.copy()
        vals = gdf[["x", "y", var_name]].to_numpy()
        for x, y, v in vals:
            r = y_to_row[y]
            c = x_to_col[x]
            arr[r, c] = v
        arr_dict[var_name] = arr

    if not return_transform:
        return arr_dict

    if nx > 1:
        dx = float(np.median(np.diff(xs)))
    else:
        dx = 5.0
    if ny > 1:
        dy = float(np.median(np.diff(ys)))
    else:
        dy = 5.0

    x_min = float(xs.min())
    y_max = float(ys.max())

    transform = from_origin(x_min - dx / 2.0, y_max + dy / 2.0, dx, dy)
    return arr_dict, transform, dx


def coordinate_to_index(gdf: gpd.GeoDataFrame, px: float, py: float) -> Tuple[int, int]:
    """Zet wereldcoördinaat (px, py) om naar rij/kolom in het grid."""
    xs = np.sort(gdf["x"].unique())
    ys = np.sort(gdf["y"].unique())

    col = int(np.abs(xs - px).argmin())
    row = int(np.abs(ys - py).argmin())

    row = len(ys) - 1 - row
    return row, col


def preprocess_geodata(
    geodata: gpd.GeoDataFrame,
    catchments: gpd.GeoDataFrame,
    inlets: gpd.GeoDataFrame,
    maatregelen: Optional[gpd.GeoDataFrame],
    slope_factor: float = 1.0,
    manning_factor: float = 1.0,
    runoff_factor: float = 1.0,
):
    """
    Maak per-stroomgebied 2D-arrays voor S, n, ro, fd, fa, dtm, en inlet/outlet-indices.

    Belangrijk: we behandelen **alle waarden < 0 als nodata** in alle rasters.
    """
    geodata = geodata.to_crs(catchments.crs)
    inlets = inlets.to_crs(catchments.crs)
    if maatregelen is not None:
        maatregelen = maatregelen.to_crs(catchments.crs)

    joined = gpd.sjoin(
        geodata,
        catchments[["uitstroompunt_nummer", "geometry"]],
        how="left",
        predicate="within",
    )

    geodata_with_catchment_id = (
        joined[~joined["uitstroompunt_nummer"].isna()]
        .drop(columns=["index_right"])
        .rename(columns={"uitstroompunt_nummer": "catchment_id"})
    )

    # Maatregelen toepassen
    geodata_with_catchment_id = apply_maatregelen(
        geodata_with_catchment_id, maatregelen
    )

    inputs: Dict[int, dict] = {}
    L = None

    for _, catchment in catchments.iterrows():
        catchment_id = int(catchment.uitstroompunt_nummer)
        gdf_tmp = geodata_with_catchment_id[
            geodata_with_catchment_id["catchment_id"] == catchment_id
        ].copy()

        if gdf_tmp.empty:
            continue

        gdf_tmp.loc[:, "x"] = gdf_tmp.geometry.x
        gdf_tmp.loc[:, "y"] = gdf_tmp.geometry.y

        arr_dict, transform, cellsize = points_to_array(
            gdf_tmp,
            [
                "runoff_ori_clipped",
                "D8slope",
                "breachedburnedDTM_5m",
                "D8flowaccumulation",
                "D8flowdirection",
                "manning_n",
            ],
            return_transform=True,
        )

        # Nodata: alles < 0 wordt NaN
        for key in list(arr_dict.keys()):
            a = arr_dict[key].astype(float)
            a[a < 0] = np.nan
            arr_dict[key] = a

        S   = arr_dict["D8slope"]                * slope_factor
        n   = arr_dict["manning_n"]              * manning_factor
        ro  = arr_dict["runoff_ori_clipped"]     * runoff_factor
        fd  = arr_dict["D8flowdirection"]
        fa  = arr_dict["D8flowaccumulation"]
        dtm = arr_dict["breachedburnedDTM_5m"]

        outlet_x = float(
            catchments.loc[catchments["uitstroompunt_nummer"] == catchment_id, "outlet_x"]
            .values[0]
        )
        outlet_y = float(
            catchments.loc[catchments["uitstroompunt_nummer"] == catchment_id, "outlet_y"]
            .values[0]
        )
        outlet_indices = coordinate_to_index(gdf_tmp, outlet_x, outlet_y)

        inlet_dict: Dict[int, Tuple[int, int]] = {}
        for _, inlet in inlets[inlets["target_id"] == catchment_id].iterrows():
            source_id = int(inlet.source_id)
            inlet_x = inlet.geometry.geoms[0].x
            inlet_y = inlet.geometry.geoms[0].y
            inlet_indices = coordinate_to_index(gdf_tmp, inlet_x, inlet_y)
            inlet_dict[source_id] = inlet_indices

        inputs[catchment_id] = {
            "S_catchment": S,
            "fd_catchment": fd,
            "fa_catchment": fa,
            "ro_catchment": ro,
            "dtm_catchment": dtm,
            "manning_catchment": n,
            "outlet_indices": outlet_indices,
            "inlet_dict": inlet_dict,
            "transform": transform,
        }

        if L is None:
            L = float(cellsize)

    if L is None:
        raise RuntimeError("Geen stroomgebieden gevonden in geodata.")

    log("Stap: preprocessing geodata per stroomgebied afgerond.")
    return inputs, geodata.crs, L


def waterlevel_volume_curve(
    catchment_dtm: np.ndarray, pixel_area: float, levels: np.ndarray
):
    dtm = catchment_dtm.astype(float)
    mask = np.isfinite(dtm)
    volumes = []
    for h in levels:
        depth = np.maximum(0.0, h - dtm)
        depth[~mask] = 0.0
        volumes.append(depth.sum() * pixel_area)
    return np.asarray(levels, float), np.asarray(volumes, float)


def build_level_volume_pchip(levels: np.ndarray, volumes: np.ndarray):
    levels = np.asarray(levels, float)
    volumes = np.asarray(volumes, float)

    order = np.argsort(levels)
    levels = levels[order]
    volumes = volumes[order]
    volumes = np.maximum.accumulate(volumes)

    def V_of_h(h):
        return np.interp(h, levels, volumes, left=volumes[0], right=volumes[-1])

    def h_of_V(V):
        return np.interp(V, volumes, levels, left=levels[0], right=levels[-1])

    return V_of_h, h_of_V


class QReservoir:
    def __init__(
        self,
        catchment_id: int,
        dtm_array: np.ndarray,
        pixel_area: float,
        transform,
        crs,
        A: float,
        Qmax: float,
    ):
        self.catchment_id = int(catchment_id)
        self.dtm = dtm_array.astype(float)
        self.pixel_area = float(pixel_area)
        self.transform = transform
        self.crs = crs

        self.t = 0.0
        self.S = 0.0
        self.H = 0.0

        self.A = float(A)
        self.Qmax = float(Qmax)

        self._setup_waterlevel_volume_relationship()

    def _setup_waterlevel_volume_relationship(self):
        dtm = self.dtm.copy()
        dtm[~np.isfinite(dtm)] = np.nan
        zmin = float(np.nanmin(dtm))
        zmax = float(np.nanmax(dtm))

        levels = np.linspace(zmin, zmax, 100)
        levels, volumes = waterlevel_volume_curve(dtm, self.pixel_area, levels)
        V_of_h, h_of_V = build_level_volume_pchip(levels, volumes)

        self.V_of_h = V_of_h
        self.h_of_V = h_of_V

        nodata = -9999.0
        self.dtm_meta = {
            "driver": "GTiff",
            "height": dtm.shape[0],
            "width": dtm.shape[1],
            "count": 1,
            "dtype": "float32",
            "crs": self.crs,
            "transform": self.transform,
            "nodata": nodata,
        }

    def get_waterlevel_from_volume(self, S: float) -> float:
        return float(self.h_of_V(S))

    def get_volume_from_waterlevel(self, H: float) -> float:
        return float(self.V_of_h(H))

    def update_storage(self, Vin: float, Vout: float):
        self.S += Vin - Vout

    def transfer(self, Vin: float, tres: float) -> float:
        Vin = float(Vin)
        tres = float(tres)

        Qout_potential = (
            self.A * self.S * math.exp(-self.A * tres)
            + (Vin / tres) * (1.0 - math.exp(-self.A * tres))
        )
        Qout_real = min(Qout_potential, self.Qmax * tres)

        Vout = math.floor(Qout_real * tres * 1e5) / 1e5

        self.update_storage(Vin, Vout)
        self.t += tres

        return Vout

    def export_waterdepth(self, out_fp: Path, waterlevel: Optional[float] = None) -> Path:
        dtm = self.dtm.copy()
        if waterlevel is None:
            waterlevel = self.get_waterlevel_from_volume(self.S)
        else:
            waterlevel = float(waterlevel)

        waterdepth = waterlevel - dtm
        waterdepth[~np.isfinite(dtm)] = np.nan
        waterdepth[waterdepth < 0] = 0.0

        meta = self.dtm_meta.copy()
        out_fp = Path(out_fp)
        out_fp.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_fp, "w", **meta) as dest:
            arr = waterdepth.astype("float32")
            nodata = meta.get("nodata", -9999.0)
            arr[~np.isfinite(dtm)] = nodata
            dest.write(arr, 1)
        return out_fp


class HReservoir:
    def __init__(
        self,
        catchment_id: int,
        dtm_array: np.ndarray,
        pixel_area: float,
        transform,
        crs,
        Hmax: float,
    ):
        self.catchment_id = int(catchment_id)
        self.dtm = dtm_array.astype(float)
        self.pixel_area = float(pixel_area)
        self.transform = transform
        self.crs = crs

        self.t = 0.0
        self.S = 0.0
        self.H = 0.0

        self.Hmax = float(Hmax)

        self._setup_waterlevel_volume_relationship()
        self.Smax = self.get_volume_from_waterlevel(self.Hmax)

    def _setup_waterlevel_volume_relationship(self):
        dtm = self.dtm.copy()
        dtm[~np.isfinite(dtm)] = np.nan
        zmin = float(np.nanmin(dtm))
        zmax = float(np.nanmax(dtm))

        levels = np.linspace(zmin, zmax, 100)
        levels, volumes = waterlevel_volume_curve(dtm, self.pixel_area, levels)
        V_of_h, h_of_V = build_level_volume_pchip(levels, volumes)

        self.V_of_h = V_of_h
        self.h_of_V = h_of_V

        nodata = -9999.0
        self.dtm_meta = {
            "driver": "GTiff",
            "height": dtm.shape[0],
            "width": dtm.shape[1],
            "count": 1,
            "dtype": "float32",
            "crs": self.crs,
            "transform": self.transform,
            "nodata": nodata,
        }

    def get_waterlevel_from_volume(self, S: float) -> float:
        return float(self.h_of_V(S))

    def get_volume_from_waterlevel(self, H: float) -> float:
        return float(self.V_of_h(H))

    def update_storage(self, Vin: float, Vout: float):
        self.S += Vin - Vout

    def transfer(self, Vin: float, tres: float) -> float:
        Vin = float(Vin)
        tres = float(tres)

        if self.S + Vin > self.Smax:
            Vout = (self.S + Vin) - self.Smax
        else:
            Vout = 0.0

        self.update_storage(Vin, Vout)
        self.t += tres
        return Vout

    def export_waterdepth(self, out_fp: Path, waterlevel: Optional[float] = None) -> Path:
        dtm = self.dtm.copy()
        if waterlevel is None:
            waterlevel = self.get_waterlevel_from_volume(self.S)
        else:
            waterlevel = float(waterlevel)

        waterdepth = waterlevel - dtm
        waterdepth[~np.isfinite(dtm)] = np.nan
        waterdepth[waterdepth < 0] = 0.0

        meta = self.dtm_meta.copy()
        out_fp = Path(out_fp)
        out_fp.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_fp, "w", **meta) as dest:
            arr = waterdepth.astype("float32")
            nodata = meta.get("nodata", -9999.0)
            arr[~np.isfinite(dtm)] = nodata
            dest.write(arr, 1)
        return out_fp


def build_reservoirs(
    catchments: gpd.GeoDataFrame,
    inputs: Dict[int, dict],
    L: float,
    crs,
):
    reservoirs = {}
    pixel_area = L ** 2

    for _, catchment in catchments.iterrows():
        cid = int(catchment.uitstroompunt_nummer)
        if cid not in inputs:
            continue

        dtm = inputs[cid]["dtm_catchment"]
        transform = inputs[cid]["transform"]

        rtype = str(catchment.uitstroompunt_type)
        if rtype == "Q":
            A = 1.0 / float(catchment.K_s)
            Qmax = float(catchment.Q_cap_ms)
            res = QReservoir(
                cid,
                dtm_array=dtm,
                pixel_area=pixel_area,
                transform=transform,
                crs=crs,
                A=A,
                Qmax=Qmax,
            )
        else:
            Hmax = float(catchment.outlet_mtaw)
            res = HReservoir(
                cid,
                dtm_array=dtm,
                pixel_area=pixel_area,
                transform=transform,
                crs=crs,
                Hmax=Hmax,
            )

        reservoirs[cid] = res

    log("Stap: reservoirs opgebouwd voor alle stroomgebieden.")
    return reservoirs


def run_model(
    catchments: gpd.GeoDataFrame,
    inputs: Dict[int, dict],
    L: float,
    reservoirs: Dict[int, object],
    rf_timeseries: pd.DataFrame,
    A_threshold: float,
    update_progress=None,
):
    """
    Draai het model voor de opgegeven neerslagreeks.
    Geen extra padding; max. 3 dagen is eerder al afgedwongen.
    """
    rf_df = rf_timeseries.copy()
    rf_df["datum"] = pd.to_datetime(rf_df["datum"])
    rf_df = rf_df.sort_values("datum")

    times = rf_df["datum"].to_numpy()
    P_event = rf_df["rf"].to_numpy(dtype=float)

    if len(times) >= 2:
        dt = pd.to_timedelta(
            np.median(np.diff(times.astype("datetime64[ns]")))
        )
    else:
        dt = pd.to_timedelta("3600s")

    T = float(dt.total_seconds())
    n_steps = len(P_event)

    catchment_ids = [int(c) for c in catchments.uitstroompunt_nummer.values]
    catchment_discharges: Dict[int, np.ndarray] = {
        cid: np.zeros(n_steps, dtype=float) for cid in catchment_ids
    }
    catchment_waterlevels: Dict[int, np.ndarray] = {}

    for cid in catchment_ids:
        base_level = reservoirs[cid].get_waterlevel_from_volume(0.0)
        catchment_waterlevels[cid] = np.ones(n_steps, dtype=float) * base_level

    PUs: Dict[int, np.ndarray] = {}

    log("Stap: modelrun gestart.")

    for timestep in range(1, n_steps):
        if update_progress is not None:
            update_progress(timestep, n_steps, times[timestep])

        P_current = float(P_event[timestep])

        for _, catchment in catchments.iterrows():
            cid = int(catchment.uitstroompunt_nummer)
            if cid not in inputs:
                continue

            inp = inputs[cid]
            ro_catchment = inp["ro_catchment"]
            inlet_dict = inp["inlet_dict"]
            inlet_ids = list(inlet_dict.keys())

            if inlet_ids:
                discharge_in_array = np.array(
                    [catchment_discharges[inlet_id][timestep - 1] for inlet_id in inlet_ids]
                )
                discharge_in_dict = {
                    inlet_id: incoming
                    for inlet_id, incoming in zip(inlet_ids, discharge_in_array)
                }
            else:
                discharge_in_dict = {}

            S_catchment = inp["S_catchment"]
            fd_catchment = inp["fd_catchment"].astype(float)
            fa_catchment = inp["fa_catchment"]
            n_catchment = inp["manning_catchment"]
            dtm_catchment = inp["dtm_catchment"]
            outlet_indices = inp["outlet_indices"]

            channel_mask = fa_catchment >= float(A_threshold)

            for inlet_indices in inlet_dict.values():
                if not channel_mask[inlet_indices]:
                    raise Exception("A_threshold te hoog, inlaat niet verbonden met kanaalcel(len).")

            effective_rainfall = compute_effective_recharge(P_current, ro_catchment)

            fd_c = fd_catchment.astype(float)
            fd_c[fd_c == -9999] = np.nan

            Qs = route_Q_channel(
                fd_c,
                dtm_catchment,
                channel_mask,
                discharge_in_dict,
                inlet_dict,
                effective_rainfall,
                outlet_indices,
                L,
            )

            effective_Q = np.zeros_like(fd_c, dtype=float)
            for inlet_id, rc in inlet_dict.items():
                effective_Q[tuple(rc)] = discharge_in_dict.get(inlet_id, 0.0)

            catchment_mask = ~np.isnan(fd_c)
            travel_time = np.ones_like(fd_c, dtype=float) * np.inf
            if P_current != 0.0:
                travel_time[catchment_mask] = (
                    L**0.6 * n_catchment[catchment_mask] ** 0.6
                ) / (
                    effective_rainfall[catchment_mask] ** 0.4
                    * S_catchment[catchment_mask] ** 0.3
                )

            Qs_flow = Qs / T
            B = L / 2.0
            if not np.all(Qs_flow[channel_mask] == 0.0):
                channel_mask2 = Qs_flow != 0.0
                travel_time[channel_mask2] = L / (
                    (S_catchment[channel_mask2] ** 0.5 / n_catchment[channel_mask2])
                    * (Qs_flow[channel_mask2] / B) ** (2.0 / 3.0)
                ) ** (3.0 / 5.0)

            accumulated_travel_time = accumulate_travel_time(
                travel_time, fd_c, tuple(outlet_indices)
            )

            valid = accumulated_travel_time != np.inf
            if not np.any(valid):
                continue

            pixel_area = L**2
            t_max = float(np.nanmax(accumulated_travel_time[valid]))
            # Beperk lengte van de unit-respons om geheugen te sparen
            bins_full = np.arange(0.0, t_max + T, T)
            max_lags = 200  # eventueel lager/hoger zetten
            if len(bins_full) - 1 > max_lags:
                lags = max_lags
                bins = np.linspace(0.0, t_max, lags + 1)
            else:
                bins = bins_full
                lags = len(bins) - 1

            PU_current = np.zeros((lags, 1), dtype=float)
            mm_to_m = 1e-3

            for lag in range(lags):
                t_start, t_end = bins[lag], bins[lag + 1]
                mask = (accumulated_travel_time >= t_start) & (
                    accumulated_travel_time < t_end
                )
                if not np.any(mask):
                    continue

                iso_vol = effective_Q[mask].sum() + (
                    effective_rainfall[mask] * mm_to_m * pixel_area
                ).sum()
                PU_current[lag, 0] = iso_vol


            if timestep == 1 or cid not in PUs:
                PUs[cid] = PU_current
                PU_total = PU_current
            else:
                PU_prev = PUs[cid]
                if len(PU_current) < len(PU_prev):
                    PU_current = np.pad(
                        PU_current,
                        [(0, len(PU_prev) - len(PU_current)), (0, 0)],
                    )
                elif len(PU_current) > len(PU_prev):
                    PU_prev = np.pad(
                        PU_prev,
                        [(0, len(PU_current) - len(PU_prev)), (0, 0)],
                    )
                PU_total = np.concatenate((PU_prev, PU_current), axis=1)
                PUs[cid] = PU_total

            PU_total_padded = np.pad(
                PU_total, [(0, max(0, timestep - lags)), (0, 0)]
            )
            catchment_current_Q = tv_convolve_next(PU_total_padded, timestep)

            Vout = reservoirs[cid].transfer(catchment_current_Q, T)
            catchment_discharges[cid][timestep] = Vout
            catchment_waterlevels[cid][timestep] = reservoirs[cid].get_waterlevel_from_volume(
                reservoirs[cid].S
            )

    log("Stap: modelrun afgerond.")
    return catchment_discharges, catchment_waterlevels, times, T


# ------------------------------------------------------------
# Helpers voor shapefiles (maatregelen)
# ------------------------------------------------------------

def read_maatregelen_from_uploads(files: List, label: str) -> Optional[gpd.GeoDataFrame]:
    """
    Schrijf alle geüploade shapefile-componenten voor maatregelen naar een temp-map,
    lees ALLE .shp-bestanden en concateneer tot één GeoDataFrame.
    """
    if not files:
        return None

    tmp_dir = Path(tempfile.mkdtemp())
    for f in files:
        out_fp = tmp_dir / Path(f.name).name
        with open(out_fp, "wb") as out:
            out.write(f.getbuffer())

    shp_files = list(tmp_dir.glob("*.shp"))
    if not shp_files:
        st.error(f"Geen .shp-bestand gevonden in geüploade {label}-bestanden.")
        st.stop()

    gdfs = []
    for shp in shp_files:
        gdf = gpd.read_file(shp)
        gdfs.append(gdf)

    if not gdfs:
        return None

    crs = gdfs[0].crs
    merged = gpd.GeoDataFrame(
        pd.concat(gdfs, ignore_index=True),
        geometry="geometry",
        crs=crs,
    )
    return merged


# ------------------------------------------------------------
# RUN KNOP
# ------------------------------------------------------------

if run_button:
    try:
        if geodata_file is None or catchments_file is None or inlets_file is None:
            st.error("Upload eerst geodata, catchments en `inlets_pts.gpkg`.")
        elif not HAS_WATERINFO:
            st.error(
                "`pywaterinfo` is niet geïnstalleerd. "
                "Installeer met `pip install pywaterinfo` en start de app opnieuw."
            )
        else:
            log("Stap: inlezen geodata en stroomgebieden...")
            geodata = gpd.read_parquet(geodata_file)

            catchments_fp = Path(tempfile.mkdtemp()) / "catchments.gpkg"
            with open(catchments_fp, "wb") as f:
                f.write(catchments_file.getbuffer())
            catchments = gpd.read_file(catchments_fp)

            # Inlets (geopackage)
            inlets_fp = Path(tempfile.mkdtemp()) / "inlets_pts.gpkg"
            with open(inlets_fp, "wb") as f:
                f.write(inlets_file.getbuffer())
            inlets = gpd.read_file(inlets_fp)

            # Maatregelen (optioneel, meerdere shapefiles)
            maatregelen = None
            if maatregelen_files:
                log("Stap: maatregelen inlezen en samenvoegen...")
                maatregelen = read_maatregelen_from_uploads(maatregelen_files, "maatregelen")

            # Preprocessing
            log("Stap: preprocessing geodata (rasters per stroomgebied opbouwen)...")
            inputs, crs, L = preprocess_geodata(
                geodata,
                catchments,
                inlets,
                maatregelen,
                slope_factor=slope_factor,
                manning_factor=manning_factor,
                runoff_factor=runoff_factor,
            )

            # Neerslag ophalen
            log("Stap: neerslag downloaden van waterinfo.be (VMM)...")
            vmm = Waterinfo("vmm")
            df_raw = vmm.get_timeseries_values(
                ts_id=str(ts_id),
                start=start_date,
                end=end_date,
            )

            # Tijd- en waarde-kolommen bepalen
            time_col = "Timestamp" if "Timestamp" in df_raw.columns else "timestamp"
            if time_col not in df_raw.columns:
                time_col = df_raw.columns[0]
            value_col = "Value" if "Value" in df_raw.columns else df_raw.columns[-1]

            df_raw[time_col] = pd.to_datetime(df_raw[time_col])
            df_raw = df_raw.sort_values(time_col)

            freq_str = f"{int(timestep_minutes)}min"
            log(f"Stap: neerslag her-samplen naar totalen per {timestep_minutes} min...")
            rf_timeseries = (
                df_raw
                .set_index(time_col)[[value_col]]
                .resample(freq_str)
                .sum()
                .reset_index()
            )
            rf_timeseries.columns = ["datum", "rf"]

            # Maximaal 3 dagen
            max_steps = int((3 * 24 * 60) // int(timestep_minutes))
            if len(rf_timeseries) > max_steps:
                log(
                    f"Stap: neerslag afkappen op eerste {max_steps} stappen "
                    f"(3 dagen, Δt={timestep_minutes} min)."
                )
                rf_timeseries = rf_timeseries.iloc[:max_steps].copy()

            log(
                f"Stap: neerslagreeks klaar – {len(rf_timeseries)} tijdstappen "
                f"(Δt={timestep_minutes} min, ≤ {max_steps} stappen)."
            )

            # Reservoirs
            log("Stap: reservoirs opbouwen...")
            reservoirs = build_reservoirs(catchments, inputs, L, crs)

            # Progress callback
            def update_progress(timestep: int, n_steps: int, current_time):
                frac = timestep / max(1, n_steps - 1)
                progress_bar.progress(min(1.0, frac))
                ts_str = pd.to_datetime(current_time).strftime("%Y-%m-%d %H:%M")
                timestep_text.write(
                    f"Tijdstap {timestep}/{n_steps - 1} – {ts_str} "
                    f"(Δt={timestep_minutes} min)"
                )

            # Modelrun
            log(f"Stap: modelrun starten (Δt={timestep_minutes} min, max. 3 dagen)...")
            catchment_discharges, catchment_waterlevels, times, T = run_model(
                catchments,
                inputs,
                L,
                reservoirs,
                rf_timeseries,
                A_threshold=A_threshold,
                update_progress=update_progress,
            )

            log("Stap: simulatie klaar – outputs voorbereiden...")

            # Outputtabellen
            catchment_ids_sorted = sorted(int(c) for c in catchments.uitstroompunt_nummer.values)

            df_Q = pd.DataFrame({"datum": times})
            for cid in catchment_ids_sorted:
                df_Q[f"totaal_afvoer_uitlaat{cid}"] = catchment_discharges[cid]

            df_H = pd.DataFrame({"datum": times})
            for cid in catchment_ids_sorted:
                df_H[f"waterpeil_c{cid}"] = catchment_waterlevels[cid]

            df_rf = rf_timeseries.copy()

            # Eenvoudige plot
            with plot_container:
                st.markdown("#### Voorbeeld-hydrogram (eerste stroomgebied)")
                if catchment_ids_sorted:
                    first_cid = catchment_ids_sorted[0]
                    df_plot = pd.DataFrame({
                        "datum": times,
                        "Q_m3": catchment_discharges[first_cid],
                    })
                    df_plot = df_plot.set_index("datum")
                    st.line_chart(df_plot)

                    st.markdown(f"Neerslag [mm per {timestep_minutes} min]")
                    st.bar_chart(df_rf.set_index("datum")["rf"])
                else:
                    st.info("Geen stroomgebieden gevonden in de inputs.")

            # Exports
            outputs_zip = None
            with tempfile.TemporaryDirectory() as tmpd:
                tmp_dir = Path(tmpd)
                df_Q.to_csv(tmp_dir / "catchment_discharges.csv", index=False)
                df_H.to_csv(tmp_dir / "catchment_waterlevels.csv", index=False)
                rf_fname = f"rainfall_waterinfo_dt{int(timestep_minutes)}min.csv"
                df_rf.to_csv(tmp_dir / rf_fname, index=False)

                depth_files: List[Path] = []

                if export_depths:
                    depth_dir = tmp_dir / "max_waterdepth"
                    depth_dir.mkdir(parents=True, exist_ok=True)
                    for cid in catchment_ids_sorted:
                        Hmax = float(np.nanmax(catchment_waterlevels[cid]))
                        if not np.isfinite(Hmax):
                            continue
                        fp = depth_dir / f"max_waterdepth_catchment_{cid:02d}.tif"
                        reservoirs[cid].export_waterdepth(fp, Hmax)
                        depth_files.append(fp)

                zip_fp = tmp_dir / f"hogebeek_outputs_waterinfo_dt{int(timestep_minutes)}min_max3days.zip"
                with zipfile.ZipFile(zip_fp, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.write(tmp_dir / "catchment_discharges.csv", "catchment_discharges.csv")
                    zf.write(tmp_dir / "catchment_waterlevels.csv", "catchment_waterlevels.csv")
                    zf.write(tmp_dir / rf_fname, rf_fname)
                    if export_depths:
                        for fp in depth_files:
                            zf.write(fp, f"max_waterdepth/{fp.name}")

                with open(zip_fp, "rb") as f:
                    outputs_zip = f.read()

            with download_container:
                st.markdown("#### Alle resultaten downloaden")
                st.download_button(
                    "Download ZIP met resultaten",
                    data=outputs_zip,
                    file_name=zip_fp.name,
                    mime="application/zip",
                )

            log("Stap: run volledig afgerond. Resultaten beschikbaar voor download.")
    except Exception as e:
        st.exception(e)
        log("Fout tijdens de run – zie traceback hierboven.")
        progress_bar.progress(0)
        timestep_text.empty()
