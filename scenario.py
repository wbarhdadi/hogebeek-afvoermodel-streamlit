"""Session-scoped setup state for named Hoge Beek scenarios."""

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, MutableMapping

import numpy as np
import pandas as pd

from reporting import FLOODED_AREA_COLUMNS


@dataclass
class ScenarioSetup:
    name: str
    rainfall_source: str = "Waterinfo (VMM)"
    timestep_minutes: int = 60
    a_threshold_m2: float = 100000.0
    uploaded_inputs: dict[str, Any] = field(default_factory=dict)


def save_scenario_setup(session_state: MutableMapping[str, Any], setup: ScenarioSetup) -> str | None:
    """Retain a valid setup for the current browser session."""
    if not setup.name.strip():
        return "Geef het scenario een naam voordat je het uitvoert."
    session_state["scenario_setup"] = setup
    return None


def saved_scenario_setup(session_state: MutableMapping[str, Any]) -> ScenarioSetup | None:
    """Return the scenario retained for the current browser session, if any."""
    return session_state.get("scenario_setup")


def save_baseline(session_state: MutableMapping[str, Any], scenario: dict[str, Any]) -> None:
    """Retain the measure-free reference simulation for this browser session."""
    session_state["baseline"] = scenario


def save_comparison(session_state: MutableMapping[str, Any], scenario: dict[str, Any]) -> None:
    """Retain the one named measure scenario for this browser session."""
    session_state["comparison"] = scenario


def input_differences(baseline: dict[str, Any], comparison: dict[str, Any]) -> list[str]:
    """Return changed spatial or rainfall inputs, excluding selected measures."""
    baseline_inputs = baseline["inputs"]
    comparison_inputs = comparison["inputs"]
    keys = sorted(set(baseline_inputs) | set(comparison_inputs))
    return [
        key for key in keys
        if key != "measures" and baseline_inputs.get(key) != comparison_inputs.get(key)
    ]


def snapshot_inputs(inputs: dict[str, Any]) -> dict[str, str | None]:
    """Create stable session-only identities for uploaded spatial and rainfall inputs."""
    snapshot: dict[str, str | None] = {}
    for key, value in inputs.items():
        if key == "measures":
            continue
        if value is None:
            snapshot[key] = None
        elif hasattr(value, "getbuffer"):
            snapshot[key] = sha256(bytes(value.getbuffer())).hexdigest()
        else:
            snapshot[key] = str(value)
    return snapshot


def _percentage_change(change: float, baseline_value: float) -> float | None:
    if baseline_value == 0:
        return None
    return change / baseline_value * 100


def build_scenario_comparison(
    baseline: dict[str, Any], comparison: dict[str, Any]
) -> dict[str, Any]:
    """Calculate overview differences between compatible retained simulations."""
    baseline_results = baseline["results"]
    comparison_results = comparison["results"]
    baseline_peaks = baseline_results["discharges"].drop(columns="datetime", errors="ignore").max()
    comparison_peaks = comparison_results["discharges"].drop(columns="datetime", errors="ignore").max()
    terminal_peaks = pd.DataFrame({"baseline_peak_m3s": baseline_peaks, "comparison_peak_m3s": comparison_peaks})
    terminal_peaks["change_m3s"] = terminal_peaks["comparison_peak_m3s"] - terminal_peaks["baseline_peak_m3s"]
    terminal_peaks["change_percent"] = [
        _percentage_change(change, baseline_value)
        for change, baseline_value in zip(terminal_peaks["change_m3s"], terminal_peaks["baseline_peak_m3s"])
    ]

    baseline_summary = baseline_results["summary"].query("summary_scope == 'subcatchment'").set_index("catchment_id")
    comparison_summary = comparison_results["summary"].query("summary_scope == 'subcatchment'").set_index("catchment_id")
    shared_ids = baseline_summary.index.intersection(comparison_summary.index)
    rows: list[dict[str, Any]] = []
    for catchment_id in shared_ids:
        row: dict[str, Any] = {"catchment_id": catchment_id}
        for column in FLOODED_AREA_COLUMNS:
            baseline_value = float(baseline_summary.at[catchment_id, column])
            change = float(comparison_summary.at[catchment_id, column]) - baseline_value
            row[f"{column}_change"] = change
            row[f"{column}_change_percent"] = _percentage_change(change, baseline_value)
        rows.append(row)

    subcatchments = pd.DataFrame(rows).set_index("catchment_id") if rows else pd.DataFrame()
    return {
        "input_differences": input_differences(baseline, comparison),
        "terminal_peaks": terminal_peaks,
        "subcatchments": subcatchments.replace({np.nan: None}),
    }
