"""THROWAWAY PROTOTYPE — three map-first scenario workflows.

Question: which workshop-first Streamlit interaction model makes scenario work
coherent and spacious? Run with: streamlit run prototype_map_first_workflow.py
Switch designs with ?variant=A, ?variant=B, or ?variant=C (or the bottom bar).
"""

from datetime import datetime, timedelta

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st


st.set_page_config(page_title="Prototype — Hoge Beek", layout="wide")

VARIANTS = {
    "A": "Kaart als werkblad",
    "B": "Begeleide scenario-stappen",
    "C": "Resultaten als briefing",
}
CATCHMENTS = pd.DataFrame(
    [
        {"id": "SB-01", "naam": "Bovenloop", "lat": 50.823, "lon": 3.262, "diepte": 0.18, "piek": 0.42, "vertraging": 35},
        {"id": "SB-02", "naam": "Dorpskern", "lat": 50.817, "lon": 3.286, "diepte": 0.46, "piek": 0.81, "vertraging": 50},
        {"id": "SB-03", "naam": "Benedenloop", "lat": 50.808, "lon": 3.310, "diepte": 0.72, "piek": 1.14, "vertraging": 75},
        {"id": "SB-04", "naam": "Monding", "lat": 50.800, "lon": 3.332, "diepte": 0.29, "piek": 0.63, "vertraging": 95},
    ]
)


def initialise_state():
    st.session_state.setdefault("prototype_selected", "SB-02")
    st.session_state.setdefault("prototype_stage", "klaar")
    st.session_state.setdefault("prototype_view", "Overzicht")
    st.session_state.setdefault("prototype_diagnostics", False)


def selected():
    return CATCHMENTS.set_index("id").loc[st.session_state.prototype_selected]


def select_catchment():
    labels = {row.id: f"{row.id} · {row.naam}" for row in CATCHMENTS.itertuples()}
    current = list(labels).index(st.session_state.prototype_selected)
    st.session_state.prototype_selected = st.selectbox(
        "Geselecteerd stroomgebied", list(labels), index=current,
        format_func=labels.get, key="prototype_catchment_picker",
    )


def map_view(height=420):
    frame = CATCHMENTS.copy()
    frame["kleur"] = frame.apply(
        lambda row: [225, 87, 89, 220] if row.id == st.session_state.prototype_selected else [39, 105, 144, 180], axis=1
    )
    frame["straal"] = frame.apply(lambda row: 260 if row.id == st.session_state.prototype_selected else 175, axis=1)
    deck = pdk.Deck(
        initial_view_state=pdk.ViewState(latitude=50.812, longitude=3.300, zoom=11.6, pitch=35),
        layers=[pdk.Layer("ScatterplotLayer", frame, get_position="[lon, lat]", get_fill_color="kleur", get_radius="straal", pickable=True)],
        tooltip={"text": "{id} · {naam}\nMax. waterdiepte: {diepte} m\nPiekafvoer: {piek} m³/s"},
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    )
    st.pydeck_chart(deck, height=height, on_select="ignore", selection_mode="single-object")
    st.caption("Prototypekaart — kies hieronder een stroomgebied; in de uiteindelijke app selecteert een kaartklik hetzelfde item.")


def hydrograph():
    item = selected()
    started = datetime(2025, 10, 3, 8)
    values = []
    for hour in range(18):
        peak = max(0, 1 - abs(hour - item.vertraging / 15) / 4)
        values.append({"tijd": started + timedelta(hours=hour), "Afvoer": round(item.piek * peak, 3), "Neerslag": max(0, 9 - abs(hour - 3) * 2)})
    data = pd.DataFrame(values)
    discharge = alt.Chart(data).mark_line(color="#1e5f87", strokeWidth=3).encode(
        x=alt.X("tijd:T", title=None), y=alt.Y("Afvoer:Q", title="Afvoer [m³/s]"), tooltip=["tijd:T", "Afvoer:Q"]
    )
    rain = alt.Chart(data).mark_bar(color="#9bc7e5", opacity=.7).encode(
        x="tijd:T", y=alt.Y("Neerslag:Q", title="Neerslag [mm/u]"), tooltip=["tijd:T", "Neerslag:Q"]
    )
    st.altair_chart(alt.vconcat(rain.properties(height=90), discharge.properties(height=190)).resolve_scale(x="shared"), width="stretch")


def status_line():
    stage = st.session_state.prototype_stage
    labels = {"leeg": "Wacht op invoer", "laden": "Invoer wordt gecontroleerd", "fout": "Actie nodig", "klaar": "Resultaten van Demo oktober 2025"}
    icons = {"leeg": "○", "laden": "◌", "fout": "!", "klaar": "✓"}
    st.markdown(f"<div class='run-status'><b>{icons[stage]} {labels[stage]}</b><span> · Laatst bijgewerkt: zojuist</span></div>", unsafe_allow_html=True)


def compact_diagnostics():
    with st.expander("Technische controles en logboek", expanded=st.session_state.prototype_diagnostics):
        st.success("Neerslagreeks: 72 regelmatige tijdstappen · 60 min · 31,4 mm")
        st.write("Massabalans en invoercontracten zijn in dit prototype gesimuleerd.")
        st.code("08:42  invoer gecontroleerd\n08:43  modelrun voltooid\n08:43  resultaten beschikbaar")


def result_detail():
    item = selected()
    st.subheader(f"{item.naam} · {item.id}")
    a, b, c = st.columns(3)
    a.metric("Max. waterdiepte", f"{item.diepte:.2f} m", "−0,08 m t.o.v. basis")
    b.metric("Piekafvoer", f"{item.piek:.2f} m³/s", "−12%")
    c.metric("Piekvertraging", f"{item.vertraging} min", "+10 min")
    hydrograph()


def scenario_controls(compact=False):
    if compact:
        left, right = st.columns(2)
        left.selectbox("Neerslag", ["Waterinfo · Zarren", "CSV upload"], key="rainfall_compact")
        right.selectbox("Maatregelpakket", ["Groenblauwe maatregelen", "Geen maatregelen", "Eigen pakket"], key="measure_compact")
        st.slider("Modeltijdstap [min]", 5, 180, 60, step=5, key="step_compact")
    else:
        st.text_input("Scenarionaam", "Demo oktober 2025")
        st.radio("Uitvoering", ["Basisscenario", "Vergelijkingsscenario"], horizontal=True)
        st.selectbox("Neerslagbron", ["Waterinfo · Zarren", "CSV upload"])
        st.file_uploader("Ruimtelijke invoer (prototype)", type=["parquet", "gpkg"], accept_multiple_files=True)
        st.selectbox("Maatregelpakket", ["Groenblauwe maatregelen", "Geen maatregelen", "Eigen pakket"])
        st.slider("Modeltijdstap [min]", 5, 180, 60, step=5)


def variant_a():
    """Variant A: workspace — controls are a narrow optional rail, map dominates."""
    st.title("Hoge Beek · scenarioverkenner")
    status_line()
    control, main = st.columns([1, 3], gap="large")
    with control:
        st.caption("SCENARIO INSTELLEN")
        scenario_controls(compact=True)
        st.button("Scenario uitvoeren", type="primary", width="stretch")
        st.divider()
        select_catchment()
        st.caption("De instellingen blijven bewust kort; verdere opties zitten onder Technische controles.")
    with main:
        tabs = st.tabs(["Kaart", "Hydrogram", "Vergelijking", "Export"])
        with tabs[0]:
            st.subheader("Waar verwachten we het meeste effect?")
            map_view(450)
        with tabs[1]:
            result_detail()
        with tabs[2]:
            st.info("Vergelijk hier een eerder basisscenario met dit maatregelenpakket.")
        with tabs[3]:
            st.download_button("Download resultaten (.zip)", b"prototype", "hogebeek_prototype.zip")
    compact_diagnostics()


def variant_b():
    """Variant B: wizard — task flow leads, map is confirmation at each step."""
    st.title("Maak samen een scenario")
    status_line()
    current = st.radio("Stap", ["1 · Invoer", "2 · Maatregelen", "3 · Controleren", "4 · Verkennen"], horizontal=True, label_visibility="collapsed")
    st.divider()
    if current == "1 · Invoer":
        st.header("Welke bui bekijken we?")
        st.write("Begin met een herkenbare gebeurtenis. De technische details blijven beschikbaar, maar niet in de weg.")
        scenario_controls(compact=True)
        st.button("Verder naar maatregelen", type="primary")
    elif current == "2 · Maatregelen":
        st.header("Wat willen we uitproberen?")
        st.multiselect("Maatregelen", ["Bufferbekken", "Houtkant", "Swale", "Ontharding"], default=["Swale", "Houtkant"])
        st.info("Verandering t.o.v. basis: lagere piek in Dorpskern en meer vertraging benedenstrooms.")
        st.button("Controleren", type="primary")
    elif current == "3 · Controleren":
        st.header("Klaar om uit te voeren")
        st.success("Alle verplichte invoer is aanwezig.")
        st.button("Voer scenario uit", type="primary")
        compact_diagnostics()
    else:
        st.header("Verken de uitkomst")
        first, second = st.columns([2, 1])
        with first: map_view(400)
        with second: select_catchment(); result_detail()


def variant_c():
    """Variant C: briefing — results lead; setup is a drawer-like compact section."""
    st.title("Hoge Beek · uitkomstbespreking")
    status_line()
    top, actions = st.columns([3, 1])
    with top:
        st.caption("DEMO OKTOBER 2025 · VERGELIJKING MET BASISSCENARIO")
        st.header("De piek verschuift, maar de benedenloop blijft aandacht vragen.")
    with actions:
        st.button("Nieuw scenario", type="primary", width="stretch")
        st.download_button("Exporteer", b"prototype", "hogebeek_prototype.zip", width="stretch")
    metrics = st.columns(4)
    metrics[0].metric("Totale neerslag", "31,4 mm")
    metrics[1].metric("Piek aan monding", "0,63 m³/s", "−18%")
    metrics[2].metric("Grootste diepte", "0,72 m", "SB-03")
    metrics[3].metric("Beschouwde duur", "18 uur")
    map_col, insight_col = st.columns([3, 2], gap="large")
    with map_col:
        st.subheader("Ruimtelijk overzicht")
        map_view(430)
    with insight_col:
        st.subheader("Bespreekpunt")
        st.warning("Benedenloop bereikt nog altijd een maximale waterdiepte boven 0,50 m.")
        select_catchment()
        result_detail()
    with st.expander("Scenario aanpassen", expanded=False):
        scenario_controls(compact=True)
        st.button("Opnieuw uitvoeren")
    compact_diagnostics()


def state_playground():
    st.sidebar.header("Prototype-toestanden")
    st.sidebar.caption("Simuleer lege, ladende en fouttoestanden zonder bestanden of modelrun.")
    st.session_state.prototype_stage = st.sidebar.selectbox(
        "Getoonde toestand", ["klaar", "leeg", "laden", "fout"], format_func={
            "klaar": "Resultaten klaar", "leeg": "Nog geen scenario", "laden": "Model draait", "fout": "Validatiefout",
        }.get,
    )
    if st.session_state.prototype_stage == "leeg":
        st.sidebar.info("Geen resultaten: start met een neerslagbron en ruimtelijke invoer.")
    elif st.session_state.prototype_stage == "laden":
        st.sidebar.progress(62, text="Model loopt — tijdstap 45 van 72")
    elif st.session_state.prototype_stage == "fout":
        st.sidebar.error("CSV bevat een ontbrekende tijdstap. Kies een regelmatige reeks.")
    st.sidebar.checkbox("Diagnostiek standaard openen", key="prototype_diagnostics")
    st.sidebar.markdown("**Volledige prototype-status**")
    st.sidebar.json({"variant": st.query_params.get("variant", "A"), "stage": st.session_state.prototype_stage, "selected_subcatchment": st.session_state.prototype_selected, "view": st.session_state.prototype_view})


def switcher(variant):
    keys = list(VARIANTS)
    position = keys.index(variant)
    previous, following = keys[(position - 1) % len(keys)], keys[(position + 1) % len(keys)]
    st.markdown(f"""
    <style>
    .run-status {{background:#edf5f7;padding:.65rem 1rem;border-left:4px solid #1e5f87;border-radius:.2rem;margin:.5rem 0 1.2rem}} .run-status span {{color:#54636b}}
    .prototype-switcher {{position:fixed;z-index:999;bottom:1rem;left:50%;transform:translateX(-50%);background:#172b35;color:#fff;padding:.55rem .8rem;border-radius:999px;box-shadow:0 4px 18px #0005;font-family:sans-serif}} .prototype-switcher a {{color:#fff;text-decoration:none;padding:.25rem .55rem;font-weight:bold}} .prototype-switcher small {{opacity:.8}}
    </style>
    <div class="prototype-switcher"><a aria-label="Vorige variant" href="?variant={previous}">←</a><small>{variant} · {VARIANTS[variant]}</small><a aria-label="Volgende variant" href="?variant={following}">→</a></div>
    """, unsafe_allow_html=True)


initialise_state()
variant = str(st.query_params.get("variant", "A")).upper()
variant = variant if variant in VARIANTS else "A"
state_playground()
st.caption("THROWAWAY UI-PROTOTYPE · geen echte bestanden, berekeningen of opslag")
{"A": variant_a, "B": variant_b, "C": variant_c}[variant]()
switcher(variant)
