"""Numerical building blocks for the Hoge Beek travel-time model.

This module deliberately has no Streamlit or geospatial-file dependencies, so
the routing calculation can be exercised independently from the page.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Mapping, Tuple

import numpy as np


DIRECTION_MAP = {
    1: (-1, 1), 2: (0, 1), 4: (1, 1), 8: (1, 0),
    16: (1, -1), 32: (0, -1), 64: (-1, -1), 128: (-1, 0),
}


def compute_effective_recharge(P_current: float, ro_catchment: np.ndarray) -> np.ndarray:
    """Return effective rainfall depth in mm for the current model timestep."""
    ro = ro_catchment.copy().astype(float)
    ro[ro == -9999] = np.nan
    return ro / 100.0 * P_current


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
    """Route volumes (m3 per timestep) along D8 channel cells."""
    H, W = fd_catchment.shape
    candidates: Dict[Tuple[int, int], float] = {}
    Q = np.zeros_like(fd_catchment, dtype=float)
    processed = set()
    rows, cols = np.where(channel_mask)
    for idx in np.argsort(dtm_catchment[channel_mask]):
        cell = (int(rows[idx]), int(cols[idx]))
        candidates[cell] = float(dtm_catchment[cell])

    while candidates:
        current_cell = list(candidates.keys())[-1]
        candidates.pop(current_cell)
        previous_volume = 0.0
        if current_cell in processed:
            continue
        while True:
            r, c = current_cell
            if current_cell not in processed:
                external_volume = 0.0
                for inlet_id, inlet_rc in inlet_indices_dict.items():
                    if current_cell == inlet_rc:
                        external_volume = float(inlet_flow_dict.get(inlet_id, 0.0))
                lateral_volume = 0.0
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == dc == 0:
                            continue
                        nr, nc = r + dr, c + dc
                        if not (0 <= nr < H and 0 <= nc < W):
                            continue
                        direction = fd_catchment[nr, nc]
                        if np.isnan(direction):
                            continue
                        if DIRECTION_MAP.get(int(direction)) == (r - nr, c - nc):
                            depth = float(effective_rain_depth[nr, nc])
                            if depth > 0.0:
                                lateral_volume += depth * 0.001 * L**2
                Q[current_cell] = previous_volume + external_volume + lateral_volume
                previous_volume = Q[current_cell]
                processed.add(current_cell)
            else:
                Q[current_cell] += previous_volume
            if current_cell == tuple(outlet_indices):
                break
            direction = fd_catchment[current_cell]
            if np.isnan(direction) or int(direction) not in DIRECTION_MAP:
                break
            dr, dc = DIRECTION_MAP[int(direction)]
            current_cell = (r + dr, c + dc)
    return Q


def accumulate_travel_time(
    travel_time: np.ndarray, flow_dir: np.ndarray, outlet: Tuple[int, int]
) -> np.ndarray:
    """Accumulate travel time in seconds from each cell to the outlet."""
    rows, cols = travel_time.shape
    accumulated = np.full_like(travel_time, np.nan, dtype=float)
    visited = np.zeros_like(travel_time, dtype=bool)

    def follow_path(r: int, c: int) -> float:
        if np.isnan(travel_time[r, c]):
            return np.nan
        if visited[r, c]:
            return accumulated[r, c]
        direction = flow_dir[r, c]
        if np.isnan(direction) or int(direction) not in DIRECTION_MAP:
            return np.inf
        dr, dc = DIRECTION_MAP[int(direction)]
        if (r, c) == outlet:
            accumulated[r, c] = 0.0
        else:
            accumulated[r, c] = travel_time[r, c] + follow_path(r + dr, c + dc)
        visited[r, c] = True
        return accumulated[r, c]

    for r in range(rows):
        for c in range(cols):
            follow_path(r, c)
    return accumulated


def tv_convolve_next(PU: np.ndarray, timestep: int) -> float:
    """Return the current output of the time-varying unit responses."""
    return float(np.asarray(PU)[:, -1].sum())


# Prepared-plan engine -------------------------------------------------------
#
# These records form the deliberately small seam between the geospatial input
# adapter (the next migration slice) and the numerical model.  They contain
# arrays that have already been clipped/aligned to one subcatchment; this module
# neither imports Streamlit nor reads geospatial files.


@dataclass(frozen=True)
class QOutlet:
    """A linear outlet store with an integrated, rate-capped release."""

    recession_coefficient_s_inv: float
    max_discharge_m3s: float
    levels_m_taw: np.ndarray | None = None
    volumes_m3: np.ndarray | None = None


@dataclass(frozen=True)
class HOutlet:
    """A level-controlled outlet, described by a monotone level-volume curve."""

    max_water_level_m_taw: float
    levels_m_taw: np.ndarray
    volumes_m3: np.ndarray


OutletRule = QOutlet | HOutlet


@dataclass(frozen=True)
class SubcatchmentInput:
    """Preprocessed raster inputs and explicit incoming-boundary locations."""

    catchment_id: int
    runoff_percent: np.ndarray
    slope: np.ndarray
    manning_n: np.ndarray
    flow_direction: np.ndarray
    accumulated_area: np.ndarray
    outlet: Tuple[int, int]
    inlets: Mapping[int, Tuple[int, int]]
    outlet_rule: OutletRule


@dataclass(frozen=True)
class PreparedSubcatchment:
    source: SubcatchmentInput
    valid_mask: np.ndarray
    channel_mask: np.ndarray
    downstream_cell: Mapping[Tuple[int, int], Tuple[int, int] | None]
    spatial_order: tuple[Tuple[int, int], ...]


@dataclass(frozen=True)
class PreparedPlan:
    """Immutable static connectivity and metadata for one model configuration."""

    catchments: Mapping[int, PreparedSubcatchment]
    topological_order: tuple[int, ...]
    terminal_outlet_ids: frozenset[int]
    cell_width_m: float
    timestep_seconds: float
    channel_threshold: float


@dataclass(frozen=True)
class ModelState:
    """Per-run dynamic travel-time queues and outlet storage at interval start."""

    timestep: int
    # Absolute due timestep -> volume.  Sparse storage is essential: a finite
    # but extreme travel time must not make runtime memory proportional to lag.
    travel_time_queues_m3: Mapping[int, Mapping[int, float]]
    outlet_storage_m3: Mapping[int, float]


@dataclass(frozen=True)
class StepResult:
    state: ModelState
    outflow_volume_m3: Mapping[int, float]
    water_level_m_taw: Mapping[int, float | None]
    generated_effective_volume_m3: Mapping[int, float]
    received_upstream_volume_m3: Mapping[int, float]


@dataclass(frozen=True)
class SimulationResult:
    outflow_volume_m3: Mapping[int, np.ndarray]
    water_level_m_taw: Mapping[int, np.ndarray]
    generated_effective_volume_m3: float
    generated_effective_volume_by_subcatchment_m3: Mapping[int, float]
    received_upstream_volume_m3: Mapping[int, float]
    terminal_outflow_volume_m3: float
    final_outlet_storage_m3: Mapping[int, float]
    final_travel_queue_m3: Mapping[int, float]
    earliest_travel_queue_due_timestep: Mapping[int, int | None]
    maximum_travel_queue_lag: Mapping[int, int]
    final_retained_volume_m3: float
    whole_system_balance_residual_m3: float
    per_subcatchment_balance_residual_m3: Mapping[int, float]
    drain_steps: int
    drain_limit_reached: bool
    state: ModelState


def _freeze_array(value: np.ndarray, *, dtype: type = float) -> np.ndarray:
    result = np.array(value, dtype=dtype, copy=True)
    result.setflags(write=False)
    return result


def _validate_level_volume(levels: np.ndarray, volumes: np.ndarray) -> None:
    if levels.ndim != 1 or volumes.ndim != 1 or len(levels) < 2 or len(levels) != len(volumes):
        raise ValueError("level-volume curve must contain equally sized one-dimensional arrays")
    if not (np.isfinite(levels).all() and np.isfinite(volumes).all()):
        raise ValueError("level-volume curve must be finite")
    if np.any(np.diff(levels) <= 0) or np.any(np.diff(volumes) < 0):
        raise ValueError("level-volume curve must be monotone")


def _validate_outlet(rule: OutletRule) -> None:
    if isinstance(rule, QOutlet):
        if rule.recession_coefficient_s_inv <= 0 or rule.max_discharge_m3s < 0:
            raise ValueError("Q outlet parameters must be positive")
        if (rule.levels_m_taw is None) != (rule.volumes_m3 is None):
            raise ValueError("Q outlet level-volume data must be supplied together")
        if rule.levels_m_taw is not None:
            _validate_level_volume(np.asarray(rule.levels_m_taw), np.asarray(rule.volumes_m3))
    elif isinstance(rule, HOutlet):
        _validate_level_volume(np.asarray(rule.levels_m_taw), np.asarray(rule.volumes_m3))
        if not (rule.levels_m_taw[0] <= rule.max_water_level_m_taw <= rule.levels_m_taw[-1]):
            raise ValueError("H outlet maximum water level is outside its level-volume curve")
    else:
        raise TypeError("outlet_rule must be QOutlet or HOutlet")


def _spatial_connectivity(source: SubcatchmentInput, valid: np.ndarray) -> tuple[dict[Tuple[int, int], Tuple[int, int] | None], tuple[Tuple[int, int], ...]]:
    height, width = valid.shape
    outlet = tuple(source.outlet)
    if not (0 <= outlet[0] < height and 0 <= outlet[1] < width and valid[outlet]):
        raise ValueError(f"subcatchment {source.catchment_id} outlet must be a valid cell")
    successors: dict[Tuple[int, int], Tuple[int, int] | None] = {}
    for r, c in zip(*np.where(valid)):
        cell = (int(r), int(c))
        if cell == outlet:
            successors[cell] = None
            continue
        direction = int(source.flow_direction[cell])
        if direction not in DIRECTION_MAP:
            raise ValueError(f"subcatchment {source.catchment_id} has invalid D8 direction at {cell}")
        dr, dc = DIRECTION_MAP[direction]
        successor = (cell[0] + dr, cell[1] + dc)
        if not (0 <= successor[0] < height and 0 <= successor[1] < width and valid[successor]):
            raise ValueError(f"subcatchment {source.catchment_id} D8 path leaves valid cells at {cell}")
        successors[cell] = successor

    # Each valid cell must reach the stated outlet; this detects cycles too.
    visiting: set[Tuple[int, int]] = set()
    visited: set[Tuple[int, int]] = set()
    order: list[Tuple[int, int]] = []
    def visit(cell: Tuple[int, int]) -> None:
        if cell in visited:
            return
        if cell in visiting:
            raise ValueError(f"subcatchment {source.catchment_id} D8 graph contains a cycle")
        visiting.add(cell)
        successor = successors[cell]
        if successor is not None:
            visit(successor)
        visiting.remove(cell)
        visited.add(cell)
        order.append(cell)
    for cell in successors:
        visit(cell)
    # post-order is outlet-first; reverse it for upstream-to-downstream routing.
    return successors, tuple(reversed(order))


def prepare(
    subcatchments: Iterable[SubcatchmentInput],
    cell_width_m: float,
    timestep_seconds: float,
    channel_threshold: float,
) -> PreparedPlan:
    """Validate static input and build a geometry-independent execution plan."""
    if cell_width_m <= 0 or timestep_seconds <= 0:
        raise ValueError("cell width and timestep must be positive")
    entries = list(subcatchments)
    by_id = {entry.catchment_id: entry for entry in entries}
    if len(by_id) != len(entries):
        raise ValueError("subcatchment ids must be unique")
    prepared: dict[int, PreparedSubcatchment] = {}
    targets: dict[int, int] = {}
    for source in entries:
        arrays = [source.runoff_percent, source.slope, source.manning_n, source.flow_direction, source.accumulated_area]
        if not arrays or any(np.asarray(array).shape != np.asarray(arrays[0]).shape for array in arrays):
            raise ValueError(f"subcatchment {source.catchment_id} raster inputs must have the same shape")
        runoff = np.asarray(source.runoff_percent, dtype=float)
        slope = np.asarray(source.slope, dtype=float)
        manning = np.asarray(source.manning_n, dtype=float)
        area = np.asarray(source.accumulated_area, dtype=float)
        direction = np.asarray(source.flow_direction, dtype=float)
        valid = np.isfinite(direction)
        if not np.any(valid):
            raise ValueError(f"subcatchment {source.catchment_id} has no valid cells")
        if np.any(~np.isfinite(runoff[valid])) or np.any((runoff[valid] < 0) | (runoff[valid] > 100)):
            raise ValueError("runoff percentage must be finite and between 0 and 100")
        if np.any(~np.isfinite(slope[valid])) or np.any(slope[valid] <= 0) or np.any(~np.isfinite(manning[valid])) or np.any(manning[valid] <= 0):
            raise ValueError("slope and Manning roughness must be finite and positive")
        _validate_outlet(source.outlet_rule)
        channel = valid & (area >= channel_threshold)
        for upstream, inlet in source.inlets.items():
            if upstream not in by_id:
                raise ValueError(f"unknown upstream subcatchment {upstream}")
            inlet = tuple(inlet)
            if not (0 <= inlet[0] < valid.shape[0] and 0 <= inlet[1] < valid.shape[1] and channel[inlet]):
                raise ValueError(f"inlet for upstream subcatchment {upstream} must be a valid channel cell")
            if upstream in targets:
                raise ValueError(f"upstream subcatchment {upstream} has more than one downstream target")
            targets[upstream] = source.catchment_id
        successors, spatial_order = _spatial_connectivity(source, valid)
        frozen_source = SubcatchmentInput(source.catchment_id, _freeze_array(runoff), _freeze_array(slope), _freeze_array(manning), _freeze_array(direction), _freeze_array(area), tuple(source.outlet), dict(source.inlets), source.outlet_rule)
        prepared[source.catchment_id] = PreparedSubcatchment(frozen_source, _freeze_array(valid, dtype=bool), _freeze_array(channel, dtype=bool), successors, spatial_order)

    indegree = {cid: 0 for cid in by_id}
    downstream: dict[int, list[int]] = {cid: [] for cid in by_id}
    for upstream, target in targets.items():
        indegree[target] += 1
        downstream[upstream].append(target)
    ready = sorted(cid for cid, degree in indegree.items() if degree == 0)
    order: list[int] = []
    while ready:
        cid = ready.pop(0)
        order.append(cid)
        for target in sorted(downstream[cid]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    if len(order) != len(by_id):
        raise ValueError("subcatchment topology contains a cycle")
    return PreparedPlan(prepared, tuple(order), frozenset(set(by_id) - set(targets)), float(cell_width_m), float(timestep_seconds), float(channel_threshold))


def initial_state(plan: PreparedPlan) -> ModelState:
    return ModelState(0, {cid: {} for cid in plan.catchments}, {cid: 0.0 for cid in plan.catchments})


def _travel_times(prepared: PreparedSubcatchment, rainfall_depth_mm: float, incoming: Mapping[int, float], timestep_seconds: float, cell_width_m: float) -> np.ndarray:
    source = prepared.source
    effective_depth = rainfall_depth_mm * source.runoff_percent / 100.0
    local_volume = np.where(prepared.valid_mask, effective_depth * 0.001 * cell_width_m**2, 0.0)
    throughflow = local_volume.copy()
    for upstream, cell in source.inlets.items():
        throughflow[tuple(cell)] += incoming.get(upstream, 0.0)
    for cell in prepared.spatial_order:
        successor = prepared.downstream_cell[cell]
        if successor is not None:
            throughflow[successor] += throughflow[cell]
    travel = np.full(source.flow_direction.shape, np.inf, dtype=float)
    for cell in prepared.spatial_order:
        if cell == source.outlet:
            travel[cell] = 0.0
            continue
        if prepared.channel_mask[cell] and throughflow[cell] > 0:
            q = throughflow[cell] / timestep_seconds
            width = cell_width_m / 2.0
            travel[cell] = cell_width_m / ((np.sqrt(source.slope[cell]) / source.manning_n[cell]) * (q / width) ** (2.0 / 3.0)) ** (3.0 / 5.0)
        elif rainfall_depth_mm > 0:
            depth = effective_depth[cell]
            if depth > 0:
                travel[cell] = cell_width_m**0.6 * source.manning_n[cell]**0.6 / (depth**0.4 * source.slope[cell]**0.3)
    accumulated = np.full(travel.shape, np.inf, dtype=float)
    for cell in reversed(prepared.spatial_order):
        successor = prepared.downstream_cell[cell]
        if cell == source.outlet:
            accumulated[cell] = 0.0
        elif np.isfinite(travel[cell]) and successor is not None and np.isfinite(accumulated[successor]):
            accumulated[cell] = travel[cell] + accumulated[successor]
    return accumulated


def _dry_inlet_travel_times(
    prepared: PreparedSubcatchment,
    incoming: Mapping[int, float],
    timestep_seconds: float,
    cell_width_m: float,
) -> Mapping[Tuple[int, int], float]:
    """Calculate dry-weather travel times only on active inlet-to-outlet paths."""
    source = prepared.source
    inlet_volumes: dict[Tuple[int, int], float] = {}
    for upstream, volume in incoming.items():
        if volume > 0.0:
            inlet = tuple(source.inlets[upstream])
            inlet_volumes[inlet] = inlet_volumes.get(inlet, 0.0) + float(volume)
    active: set[Tuple[int, int]] = set()
    for inlet in inlet_volumes:
        cell: Tuple[int, int] | None = inlet
        while cell is not None and cell not in active:
            active.add(cell)
            cell = prepared.downstream_cell[cell]

    # This is the induced acyclic routing graph.  Its topological traversal
    # preserves confluence volumes without scanning unrelated raster cells.
    indegree = {cell: 0 for cell in active}
    for cell in active:
        successor = prepared.downstream_cell[cell]
        if successor in indegree:
            indegree[successor] += 1
    ready = [cell for cell in active if indegree[cell] == 0]
    order: list[Tuple[int, int]] = []
    throughflow = {cell: inlet_volumes.get(cell, 0.0) for cell in active}
    while ready:
        cell = ready.pop()
        order.append(cell)
        successor = prepared.downstream_cell[cell]
        if successor in indegree:
            throughflow[successor] += throughflow[cell]
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)

    travel: dict[Tuple[int, int], float] = {}
    for cell in order:
        if cell == source.outlet:
            travel[cell] = 0.0
        elif prepared.channel_mask[cell] and throughflow[cell] > 0.0:
            q = throughflow[cell] / timestep_seconds
            width = cell_width_m / 2.0
            travel[cell] = cell_width_m / ((np.sqrt(source.slope[cell]) / source.manning_n[cell]) * (q / width) ** (2.0 / 3.0)) ** (3.0 / 5.0)
        else:
            travel[cell] = np.inf
    accumulated: dict[Tuple[int, int], float] = {}
    for cell in reversed(order):
        successor = prepared.downstream_cell[cell]
        if cell == source.outlet:
            accumulated[cell] = 0.0
        elif np.isfinite(travel[cell]) and successor in accumulated and np.isfinite(accumulated[successor]):
            accumulated[cell] = travel[cell] + accumulated[successor]
        else:
            accumulated[cell] = np.inf
    return {inlet: accumulated.get(inlet, np.inf) for inlet in inlet_volumes}


def _outlet_transition(rule: OutletRule, storage: float, inflow: float, timestep_seconds: float) -> tuple[float, float, float | None]:
    available = storage + inflow
    if isinstance(rule, QOutlet):
        decay = np.exp(-rule.recession_coefficient_s_inv * timestep_seconds)
        end_uncapped = storage * decay + inflow * (1.0 - decay) / (rule.recession_coefficient_s_inv * timestep_seconds)
        outflow = min(available - end_uncapped, rule.max_discharge_m3s * timestep_seconds)
        end = available - outflow
        if rule.levels_m_taw is None:
            level = None
        else:
            if end > rule.volumes_m3[-1]:
                raise ValueError("Q outlet level-volume curve does not cover reachable storage")
            level = float(np.interp(end, rule.volumes_m3, rule.levels_m_taw))
    else:
        capacity = float(np.interp(rule.max_water_level_m_taw, rule.levels_m_taw, rule.volumes_m3))
        outflow = max(0.0, available - capacity)
        end = available - outflow
        level = float(np.interp(end, rule.volumes_m3, rule.levels_m_taw))
    return float(outflow), float(end), level


def step(plan: PreparedPlan, state: ModelState, rainfall_depth_mm: float) -> StepResult:
    """Advance every subcatchment once in deterministic topological order."""
    if not np.isfinite(rainfall_depth_mm) or rainfall_depth_mm < 0:
        raise ValueError("rainfall depth must be finite and non-negative")
    queues: dict[int, Mapping[int, float]] = {}
    storages: dict[int, float] = {}
    outflows: dict[int, float] = {}
    levels: dict[int, float | None] = {}
    generated: dict[int, float] = {}
    received: dict[int, float] = {}
    for cid in plan.topological_order:
        prepared = plan.catchments[cid]
        source = prepared.source
        incoming = {upstream: outflows[upstream] for upstream in source.inlets}
        received[cid] = float(sum(incoming.values()))
        old = state.travel_time_queues_m3[cid]
        release = float(old.get(state.timestep, 0.0))
        next_queue = {due: float(volume) for due, volume in old.items() if due > state.timestep and volume > 0.0}
        # A dry catchment only routes non-zero upstream outflow.  Avoiding its
        # unrelated cell-scale work makes long dry drains practical.
        if rainfall_depth_mm == 0.0:
            generated[cid] = 0.0
            parcels = [(tuple(source.inlets[upstream]), volume) for upstream, volume in incoming.items() if volume > 0.0]
            accumulated_by_cell = _dry_inlet_travel_times(prepared, incoming, plan.timestep_seconds, plan.cell_width_m) if parcels else {}
        else:
            effective = rainfall_depth_mm * source.runoff_percent / 100.0
            generated[cid] = float(np.sum(np.where(prepared.valid_mask, effective * 0.001 * plan.cell_width_m**2, 0.0)))
            accumulated = _travel_times(prepared, rainfall_depth_mm, incoming, plan.timestep_seconds, plan.cell_width_m)
            parcels: list[tuple[Tuple[int, int], float]] = []
            for cell in zip(*np.where(prepared.valid_mask)):
                volume = float(effective[cell] * 0.001 * plan.cell_width_m**2)
                if volume > 0:
                    parcels.append(((int(cell[0]), int(cell[1])), volume))
            parcels.extend((tuple(cell), volume) for upstream, cell in source.inlets.items() if (volume := incoming[upstream]) > 0)
            accumulated_by_cell = {cell: float(accumulated[cell]) for cell, _ in parcels}
        for cell, volume in parcels:
            travel_time = accumulated_by_cell[cell]
            if not np.isfinite(travel_time) or travel_time < 0.0:
                raise ValueError(f"subcatchment {cid} has non-finite or negative travel time at {cell}")
            lag = int(np.floor(travel_time / plan.timestep_seconds + 1e-12))
            due = state.timestep + lag
            if due == state.timestep:
                release += volume
            else:
                next_queue[due] = next_queue.get(due, 0.0) + volume
        outflow, storage, level = _outlet_transition(source.outlet_rule, float(state.outlet_storage_m3[cid]), release, plan.timestep_seconds)
        queues[cid] = next_queue
        storages[cid] = storage
        outflows[cid] = outflow
        levels[cid] = level
    return StepResult(ModelState(state.timestep + 1, queues, storages), outflows, levels, generated, received)


def run(
    plan: PreparedPlan,
    rainfall_depths_mm: Iterable[float],
    *,
    max_drain_steps: int = 200,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> SimulationResult:
    """Run all supplied rainfall intervals, then dry-drain explicit model state."""
    if max_drain_steps < 0:
        raise ValueError("max_drain_steps cannot be negative")
    state = initial_state(plan)
    outflows = {cid: [] for cid in plan.catchments}
    levels = {cid: [] for cid in plan.catchments}
    generated_total = 0.0
    generated_by_catchment = {cid: 0.0 for cid in plan.catchments}
    received_by_catchment = {cid: 0.0 for cid in plan.catchments}
    depths = tuple(float(depth) for depth in rainfall_depths_mm)
    for timestep, depth in enumerate(depths, start=1):
        if progress_callback is not None:
            progress_callback("simulating_interval", timestep, len(depths))
        result = step(plan, state, float(depth))
        state = result.state
        generated_total += sum(result.generated_effective_volume_m3.values())
        for cid in plan.catchments:
            generated_by_catchment[cid] += result.generated_effective_volume_m3[cid]
            received_by_catchment[cid] += result.received_upstream_volume_m3[cid]
        for cid in plan.catchments:
            outflows[cid].append(result.outflow_volume_m3[cid])
            levels[cid].append(np.nan if result.water_level_m_taw[cid] is None else result.water_level_m_taw[cid])
    tolerance = max(1e-9, 1e-9 * generated_total)
    drain_steps = 0
    def retained() -> float:
        return float(sum(state.outlet_storage_m3.values()) + sum(sum(queue.values()) for queue in state.travel_time_queues_m3.values()))
    while retained() > tolerance and drain_steps < max_drain_steps:
        if progress_callback is not None:
            progress_callback("draining", drain_steps + 1, max_drain_steps)
        result = step(plan, state, 0.0)
        state = result.state
        drain_steps += 1
        for cid in plan.catchments:
            received_by_catchment[cid] += result.received_upstream_volume_m3[cid]
            outflows[cid].append(result.outflow_volume_m3[cid])
            levels[cid].append(np.nan if result.water_level_m_taw[cid] is None else result.water_level_m_taw[cid])
    final_queues = {cid: float(sum(queue.values())) for cid, queue in state.travel_time_queues_m3.items()}
    earliest_due = {cid: min(queue, default=None) for cid, queue in state.travel_time_queues_m3.items()}
    maximum_lag = {
        cid: max((due - state.timestep for due in queue), default=0)
        for cid, queue in state.travel_time_queues_m3.items()
    }
    terminal_outflow = float(sum(np.sum(outflows[cid]) for cid in plan.terminal_outlet_ids))
    retained_volume = retained()
    per_catchment_residual = {
        cid: generated_by_catchment[cid] + received_by_catchment[cid] - sum(outflows[cid])
        - state.outlet_storage_m3[cid] - final_queues[cid]
        for cid in plan.catchments
    }
    return SimulationResult({cid: np.asarray(values) for cid, values in outflows.items()}, {cid: np.asarray(values) for cid, values in levels.items()}, generated_total, generated_by_catchment, received_by_catchment, terminal_outflow, dict(state.outlet_storage_m3), final_queues, earliest_due, maximum_lag, retained_volume, generated_total - terminal_outflow - retained_volume, per_catchment_residual, drain_steps, retained_volume > tolerance, state)
