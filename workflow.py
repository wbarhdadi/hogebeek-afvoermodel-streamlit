"""Typed, Streamlit-independent scenario orchestration for Hoge Beek."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Callable, Mapping

import numpy as np
import pandas as pd

from hydrology import HOutlet, PreparedPlan, QOutlet, SimulationResult, SubcatchmentInput, prepare, run
from rainfall import RainfallDiagnostics, prepare_rainfall, rainfall_diagnostics
from reporting import build_output_tables


@dataclass(frozen=True)
class Diagnostic:
    """A user-correctable workflow failure, independent of presentation."""

    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True)
class ProgressEvent:
    """A stable domain progress event; controllers choose how to render it."""

    kind: str
    completed: int | None = None
    total: int | None = None


@dataclass(frozen=True)
class ScenarioRequest:
    """All deterministic input required for one named scenario run.

    Rainfall is raw, validated input at the ingestion boundary.  Raster source
    arrays are converted to an immutable ``PreparedPlan`` before simulation.
    """

    name: str
    rainfall: pd.DataFrame
    rainfall_value_kind: str
    subcatchments: tuple[SubcatchmentInput, ...]
    cell_width_m: float
    channel_threshold_m2: float
    timestep_minutes: int = 60
    terrain_by_catchment: Mapping[int, np.ndarray] | None = None
    max_drain_steps: int = 200


@dataclass(frozen=True)
class SpatialResult:
    """Spatial maximum-depth output for one subcatchment, in metres."""

    catchment_id: int
    maximum_water_depth_m: np.ndarray


@dataclass(frozen=True)
class ScenarioResult:
    """The complete non-UI result contract of a scenario workflow."""

    request: ScenarioRequest
    diagnostics: tuple[Diagnostic, ...]
    progress_events: tuple[ProgressEvent, ...]
    rainfall: pd.DataFrame | None = None
    rainfall_diagnostics: RainfallDiagnostics | None = None
    prepared_plan: PreparedPlan | None = None
    engine_result: SimulationResult | None = None
    discharges: pd.DataFrame | None = None
    waterlevels: pd.DataFrame | None = None
    summary: pd.DataFrame | None = None
    spatial_results: Mapping[int, SpatialResult] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return not self.diagnostics and self.engine_result is not None


class PreparationCache:
    """Process-local cache for immutable deterministic prepared plans only."""

    def __init__(self) -> None:
        self._plans: dict[str, PreparedPlan] = {}

    @property
    def size(self) -> int:
        return len(self._plans)

    def get_or_prepare(self, request: ScenarioRequest) -> PreparedPlan:
        key = _preparation_fingerprint(request)
        plan = self._plans.get(key)
        if plan is None:
            plan = prepare(
                request.subcatchments,
                request.cell_width_m,
                request.timestep_minutes * 60.0,
                request.channel_threshold_m2,
            )
            self._plans[key] = plan
        return plan


def _array_digest(value: np.ndarray) -> bytes:
    array = np.ascontiguousarray(np.asarray(value))
    return repr((array.dtype.str, array.shape)).encode() + array.tobytes()


def _preparation_fingerprint(request: ScenarioRequest) -> str:
    digest = sha256()
    digest.update(repr((request.cell_width_m, request.timestep_minutes, request.channel_threshold_m2)).encode())
    for source in sorted(request.subcatchments, key=lambda item: item.catchment_id):
        rule = source.outlet_rule
        digest.update(repr((source.catchment_id, source.outlet, sorted(source.inlets.items()), type(rule).__name__)).encode())
        if isinstance(rule, QOutlet):
            digest.update(repr((rule.recession_coefficient_s_inv, rule.max_discharge_m3s)).encode())
        elif isinstance(rule, HOutlet):
            digest.update(repr(rule.max_water_level_m_taw).encode())
        if rule.levels_m_taw is not None:
            digest.update(_array_digest(rule.levels_m_taw))
        if rule.volumes_m3 is not None:
            digest.update(_array_digest(rule.volumes_m3))
        for array in (source.runoff_percent, source.slope, source.manning_n, source.flow_direction, source.accumulated_area):
            digest.update(_array_digest(array))
    return digest.hexdigest()


def _result_with_diagnostic(request: ScenarioRequest, events: list[ProgressEvent], code: str, message: str, field: str) -> ScenarioResult:
    return ScenarioResult(request, (Diagnostic(code, message, field),), tuple(events))


def run_scenario(
    request: ScenarioRequest,
    progress_callback: Callable[[ProgressEvent], None] | None = None,
    *,
    preparation_cache: PreparationCache | None = None,
) -> ScenarioResult:
    """Validate, prepare, execute, and assemble one scenario without a UI.

    Known validation/topology failures become structured diagnostics. Unexpected
    programming and infrastructure failures deliberately propagate.
    """
    events: list[ProgressEvent] = []

    def emit(kind: str, completed: int | None = None, total: int | None = None) -> None:
        event = ProgressEvent(kind, completed, total)
        events.append(event)
        if progress_callback is not None:
            progress_callback(event)

    emit("validating_inputs")
    if not request.name.strip():
        return _result_with_diagnostic(request, events, "invalid_scenario_name", "Scenario name must not be empty.", "name")
    if request.timestep_minutes <= 0 or request.cell_width_m <= 0 or request.channel_threshold_m2 < 0:
        return _result_with_diagnostic(request, events, "invalid_settings", "Timestep, cell width, and channel threshold are invalid.", "settings")
    try:
        normalized = prepare_rainfall(
            request.rainfall,
            value_kind=request.rainfall_value_kind,
            timestep_minutes=request.timestep_minutes,
        )
    except (TypeError, ValueError) as error:
        return _result_with_diagnostic(request, events, "invalid_rainfall", str(error), "rainfall")

    emit("preparing_subcatchment", 0, len(request.subcatchments))
    try:
        plan = (preparation_cache or PreparationCache()).get_or_prepare(request)
    except (TypeError, ValueError) as error:
        return _result_with_diagnostic(request, events, "invalid_model_input", str(error), "subcatchments")
    emit("preparing_subcatchment", len(request.subcatchments), len(request.subcatchments))

    depths = normalized["rf"].to_numpy(dtype=float)
    try:
        engine = run(
            plan,
            depths,
            max_drain_steps=request.max_drain_steps,
            progress_callback=lambda kind, completed, total: emit(kind, completed, total),
        )
    except ValueError as error:
        return _result_with_diagnostic(request, events, "simulation_input_error", str(error), "simulation")

    emit("assembling_results")
    times = pd.date_range(
        start=pd.Timestamp(normalized["datum"].iloc[0]),
        periods=len(next(iter(engine.outflow_volume_m3.values()))),
        freq=pd.Timedelta(minutes=request.timestep_minutes),
    ).to_numpy()
    terrain = request.terrain_by_catchment
    discharges, waterlevels, summary = build_output_tables(
        times,
        dict(engine.outflow_volume_m3),
        dict(engine.water_level_m_taw),
        plan.timestep_seconds,
        rainfall_depths_mm=depths,
        terrain_by_catchment=dict(terrain) if terrain is not None else None,
        pixel_area_m2=request.cell_width_m ** 2 if terrain is not None else None,
        terminal_outlet_ids=set(plan.terminal_outlet_ids),
    )
    spatial = {}
    if terrain is not None:
        for catchment_id, ground in terrain.items():
            spatial[catchment_id] = SpatialResult(
                catchment_id,
                np.maximum(float(np.nanmax(engine.water_level_m_taw[catchment_id])) - ground, 0.0),
            )
    rainfall = normalized.rename(columns={"datum": "datetime", "rf": "rainfall_depth_mm"})
    return ScenarioResult(
        request, (), tuple(events), rainfall, rainfall_diagnostics(normalized, request.timestep_minutes),
        plan, engine, discharges, waterlevels, summary, spatial,
    )
