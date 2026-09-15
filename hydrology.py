"""Numerical building blocks for the Hoge Beek travel-time model.

This module deliberately has no Streamlit or geospatial-file dependencies, so
the routing calculation can be exercised independently from the page.
"""

from __future__ import annotations

from typing import Dict, Tuple

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
