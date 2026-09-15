# Architecture and model flow

The accepted hydrological rules, timestep semantics, state transitions, and
mass-conservation boundaries are defined in the
[conceptual hydrological model](conceptual-hydrological-model.md).

```text
raw rainfall + validated spatial source data
  -> workflow.run_scenario(ScenarioRequest)
  -> rainfall.prepare_rainfall + immutable PreparedPlan cache
  -> hydrology.run(PreparedPlan, rainfall depths)
  -> reporting.build_output_tables
  -> ScenarioResult
  -> Streamlit controller / exports / visualizations
```

## Dependency direction

Domain modules do not import Streamlit. `app.py` is the outer controller: it
collects uploads and choices, adapts them to a `ScenarioRequest`, invokes the
workflow, and renders the returned records. It owns browser-session and
presentation state only.

- `rainfall.py` validates Waterinfo or upload values and converts them to
  rainfall depth in mm per model timestep.
- Spatial ingestion/preparation adapts source geometry and measures into
  `SubcatchmentInput` records. `hydrology.prepare` validates those records and
  produces the immutable `PreparedPlan` used by the numerical engine.
- `hydrology.py` has no file, geometry-library, or UI dependency. It owns
  runtime travel-time queues, outlet storage, routing, and mass balance.
- `workflow.py` is the controller-facing domain facade. It validates,
  normalizes rainfall, reuses deterministic prepared plans, executes the
  engine, and assembles typed scenario results.
- `reporting.py` converts outflow volumes to stakeholder-facing tables and
  exports. `visualization.py` converts result data to presentation objects.
- `scenario.py` owns browser-session scenario retention and comparison rules;
  it does not own engine execution.

## Public workflow contract

`run_scenario(request, progress_callback=None) -> ScenarioResult` is the
non-UI seam for a full scenario run. `ScenarioRequest` carries the named
scenario, raw rainfall input and its explicit unit kind, prepared-source
subcatchments, timestep/configuration, and optional terrain data. A successful
`ScenarioResult` contains normalized rainfall, rainfall diagnostics, an
immutable prepared plan, engine result, output tables, and optional typed
spatial maximum-depth results.

Expected input, topology, and simulation configuration failures are returned
as structured `Diagnostic` records. Unexpected programming or infrastructure
errors propagate so the controller can expose its collapsed technical
diagnostic. A `ProgressEvent` has a stable domain kind:
`validating_inputs`, `preparing_subcatchment`, `simulating_interval`,
`draining`, or `assembling_results`. The controller decides how those events
look; they are never Streamlit messages.

`PreparationCache` caches only a `PreparedPlan`, keyed by a fingerprint of the
spatial source and its relevant settings. The plan freezes its arrays during
preparation. Runtime state, callbacks/events, scenario session data,
visualizations, and exports are deliberately not cached.

## Unit and result semantics

| Quantity | Internal / output unit |
| --- | --- |
| Rainfall supplied to the model | mm per model timestep |
| Routed and reservoir outflow | m3 per model timestep |
| Reported discharge | m3/s |
| Water level | m TAW |
| Maximum water depth | m |
| Flooded depth-class area | ha |

The outlet table contains hydrographs only for terminal outlets, avoiding a
double count of water routed from an upstream subcatchment into another one.
The summary contains every subcatchment plus a `whole_catchment` row. Its
flooded-depth-class fields are the direct sum of mutually exclusive
subcatchment areas, not a merged-raster calculation.
