"""Public-contract tests for the non-UI scenario workflow."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from hydrology import QOutlet, SubcatchmentInput
from workflow import PreparationCache, ScenarioRequest, run_scenario


def source() -> SubcatchmentInput:
    return SubcatchmentInput(
        catchment_id=1,
        runoff_percent=np.array([[100.0]]),
        slope=np.array([[1.0]]),
        manning_n=np.array([[0.03]]),
        flow_direction=np.array([[2.0]]),
        accumulated_area=np.array([[10.0]]),
        outlet=(0, 0),
        inlets={},
        outlet_rule=QOutlet(1.0, 1e9),
    )


def request(**changes) -> ScenarioRequest:
    values = {
        "name": "Voorjaarsbui",
        "rainfall": pd.DataFrame({
            "datetime": pd.date_range("2025-01-01", periods=2, freq="h"),
            "rainfall_mm": [1.0, 0.0],
        }),
        "rainfall_value_kind": "depth",
        "subcatchments": (source(),),
        "cell_width_m": 10.0,
        "channel_threshold_m2": 1.0,
    }
    values.update(changes)
    return ScenarioRequest(**values)


class ScenarioWorkflowTests(unittest.TestCase):
    def test_runs_a_named_scenario_without_streamlit_and_preserves_units(self):
        events = []

        result = run_scenario(request(), progress_callback=events.append)

        self.assertTrue(result.succeeded)
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.rainfall["rainfall_depth_mm"].tolist(), [1.0, 0.0])
        self.assertIn("discharge_catchment_1_m3s", result.discharges.columns)
        self.assertIn("water_level_catchment_1_m_taw", result.waterlevels.columns)
        self.assertGreater(result.engine_result.generated_effective_volume_m3, 0.0)
        self.assertEqual(events[0].kind, "validating_inputs")
        self.assertIn("simulating_interval", [event.kind for event in events])
        self.assertEqual(events[-1].kind, "assembling_results")

    def test_reuses_the_deterministic_prepared_plan_for_equivalent_requests(self):
        cache = PreparationCache()

        first = run_scenario(request(), preparation_cache=cache)
        second = run_scenario(request(name="Tweede run"), preparation_cache=cache)

        self.assertIs(first.prepared_plan, second.prepared_plan)
        self.assertEqual(cache.size, 1)

    def test_returns_a_structured_diagnostic_for_correctable_input_errors(self):
        invalid = request(rainfall=pd.DataFrame({"datetime": ["2025-01-01"], "rainfall_mm": [1.0]}))

        result = run_scenario(invalid)

        self.assertFalse(result.succeeded)
        self.assertEqual(result.diagnostics[0].code, "invalid_rainfall")
        self.assertIsNone(result.engine_result)


if __name__ == "__main__":
    unittest.main()
