"""Minimal non-UI caller for the prepared-plan hydrology engine.

Run with ``python benchmarks/run_prepared_plan.py``.  The intentionally small
fixture is also useful when inspecting the engine without importing Streamlit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hydrology import QOutlet, SubcatchmentInput, prepare, run  # noqa: E402


def main() -> None:
    catchment = SubcatchmentInput(
        catchment_id=1,
        runoff_percent=np.array([[100.0, 100.0]]),
        slope=np.array([[1.0, 1.0]]),
        manning_n=np.array([[0.03, 0.03]]),
        flow_direction=np.array([[2.0, 2.0]]),
        accumulated_area=np.array([[10.0, 10.0]]),
        outlet=(0, 1),
        inlets={},
        outlet_rule=QOutlet(recession_coefficient_s_inv=0.01, max_discharge_m3s=1.0),
    )
    plan = prepare([catchment], cell_width_m=10.0, timestep_seconds=60.0, channel_threshold=1.0)
    result = run(plan, [1.0, 0.0], max_drain_steps=10)
    print(json.dumps({
        "outflow_volume_m3": result.outflow_volume_m3[1].tolist(),
        "generated_effective_volume_m3": result.generated_effective_volume_m3,
        "whole_system_balance_residual_m3": result.whole_system_balance_residual_m3,
        "drain_limit_reached": result.drain_limit_reached,
    }, indent=2))


if __name__ == "__main__":
    main()
