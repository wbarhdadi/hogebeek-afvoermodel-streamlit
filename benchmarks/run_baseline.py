"""Run the reproducible pre-refactor core-model baseline.

Usage: ``python benchmarks/run_baseline.py``.  The fixture is intentionally
small: it is a numerical-regression guard and an allocation probe, not a claim
about performance on the Hoge Beek project data.
"""

from __future__ import annotations

import gc
import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The baseline intentionally calls the current core entry point.  Importing it
# also imports Streamlit because the core has not yet been separated from app.py.
from app import QReservoir, run_model  # noqa: E402


REFERENCE_PATH = ROOT / "benchmarks" / "core_model_reference.json"


def fixture():
    """Return one deterministic, three-cell Q-outlet subcatchment."""
    catchments = pd.DataFrame([{"uitstroompunt_nummer": 1}])
    inputs = {
        1: {
            "ro_catchment": np.array([[100.0, 100.0, 100.0]]),
            "inlet_dict": {},
            "S_catchment": np.array([[0.1, 0.1, 0.1]]),
            "fd_catchment": np.array([[2.0, 2.0, 2.0]]),
            "fa_catchment": np.array([[1.0, 2.0, 3.0]]),
            "manning_catchment": np.array([[0.03, 0.03, 0.03]]),
            "dtm_catchment": np.array([[3.0, 2.0, 1.0]]),
            "outlet_indices": (0, 2),
        }
    }
    rainfall = pd.DataFrame(
        {
            "datum": pd.date_range("2025-01-01", periods=5, freq="h"),
            "rf": [0.0, 5.0, 0.0, 0.0, 0.0],
        }
    )
    return catchments, inputs, rainfall


def run_fixture() -> dict[str, object]:
    """Run a fresh fixture and return only stable numerical results."""
    catchments, inputs, rainfall = fixture()
    reservoirs = {
        1: QReservoir(
            1, inputs[1]["dtm_catchment"], 100.0, None, None, 0.001, 1.0
        )
    }
    outflows, waterlevels, _, timestep_seconds = run_model(
        catchments, inputs, 10.0, reservoirs, rainfall, 1.0
    )
    return {
        "fixture": "one_q_outlet_three_cell_subcatchment",
        "timestep_seconds": timestep_seconds,
        "outflow_volume_m3": outflows[1].tolist(),
        "water_level_m_taw": waterlevels[1].tolist(),
        "final_outlet_storage_m3": reservoirs[1].S,
    }


def measure(repetitions: int = 15) -> dict[str, object]:
    """Measure repeatable elapsed-time and traced Python allocation evidence."""
    run_fixture()  # warm imports and one-time NumPy/Pandas setup
    gc.collect()
    tracemalloc.start()
    before_current, _ = tracemalloc.get_traced_memory()
    elapsed_seconds = []
    for _ in range(repetitions):
        started = time.perf_counter()
        run_fixture()
        elapsed_seconds.append(time.perf_counter() - started)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "repetitions": repetitions,
        "elapsed_seconds": {
            "minimum": min(elapsed_seconds),
            "median": statistics.median(elapsed_seconds),
        },
        "tracemalloc_bytes": {
            "current_growth": current - before_current,
            "peak": peak,
        },
    }


def main() -> None:
    report = {
        "numerical_results": run_fixture(),
        "performance_evidence": measure(),
        "limitations": [
            "No representative Hoge Beek input data is versioned in this repository.",
            "This measures Python allocations reported by tracemalloc, not total process RSS.",
            "This synthetic fixture is a regression guard; it is not a 5x speed target baseline.",
        ],
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
