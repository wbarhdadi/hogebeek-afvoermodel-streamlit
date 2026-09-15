# Architecture and model flow

The accepted hydrological rules, timestep semantics, state transitions, and
mass-conservation boundaries are defined in the
[conceptual hydrological model](conceptual-hydrological-model.md).

The Streamlit page is deliberately a thin orchestration layer. It reads files and user choices, invokes the model workflow, and renders results. The numerical routing implementation remains in `app.py` for now; moving it wholesale would make this quick improvement riskier than useful.

```text
Waterinfo or CSV -> rainfall.prepare_rainfall -> mm per model timestep
geodata + catchments + measures -> preprocess_geodata -> per-subcatchment rasters
rainfall + rasters -> run_model -> hydrology routing helpers -> outflow volume [m3], water level [m TAW]
outflow volume / timestep -> reporting.build_output_tables -> discharge [m3/s]
tables -> charts, CSV exports, GeoTIFF maximum water depths
```

## Modules

- `app.py`: Streamlit UI, geospatial preprocessing, routing, reservoirs, and workflow orchestration.
- `rainfall.py`: the rainfall-input seam. It validates input columns, regular timestamps, units, and compatible timestep aggregation.
- `reporting.py`: the result-output seam. It converts model outflow volumes to discharge and gives exported fields explicit units.
- `hydrology.py`: dependency-free numerical routing helpers used by the simulation. Their rainfall, D8 routing, and travel-time behaviour is covered without importing Streamlit.

## CSV rainfall contract

Upload a CSV with a `datetime` column and exactly one selected value type:

- Depth: `rainfall_mm`, the depth accumulated during each source interval.
- Intensity: `rainfall_mmh`, the average intensity during each source interval.

Timestamps must be regular, unique and gap-free. Choose the matching value type in the app. The model timestep must be an integer multiple of the source interval; the app intentionally rejects ambiguous upsampling.

## Unit conventions

| Quantity | Internal / output unit |
| --- | --- |
| Rainfall supplied to the model | mm per model timestep |
| Routed and reservoir outflow | m3 per model timestep |
| Reported discharge | m3/s |
| Water level | m TAW |
| Maximum water-depth GeoTIFF | m |

## Result semantics

The outlet CSV contains hydrographs only for terminal outlets: subcatchments that do not feed an inlet of another modelled subcatchment. This avoids presenting the same routed water at an upstream outlet and again downstream. The summary CSV contains one row per reported subcatchment plus a `whole_catchment` row. Its depth-class fields are the direct sum of the per-subcatchment class areas, rather than a merged-raster calculation. Depth classes are mutually exclusive: lower bound inclusive and upper bound exclusive, with the last class at least 2 m. All flooded-depth-class area fields are hectares.

## Important model limitation

The travel-time response is recomputed each timestep using current rainfall and channel flow. This is a rapid scenario model, not a calibrated hydrodynamic model. The revised UI exposes scale diagnostics, but realism still needs validation against observed rainfall and discharge before decisions are based on absolute values.
