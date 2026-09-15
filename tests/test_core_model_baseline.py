import importlib.util
import json
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "benchmarks" / "run_baseline.py"


def load_baseline_module():
    spec = importlib.util.spec_from_file_location("core_model_baseline", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CoreModelBaselineTests(unittest.TestCase):
    def test_current_core_model_matches_committed_numerical_baseline(self):
        baseline = load_baseline_module()
        expected = json.loads((ROOT / "benchmarks" / "core_model_reference.json").read_text())

        actual = baseline.run_fixture()

        self.assertEqual(actual["fixture"], expected["fixture"])
        self.assertEqual(actual["timestep_seconds"], expected["timestep_seconds"])
        np.testing.assert_allclose(actual["outflow_volume_m3"], expected["outflow_volume_m3"])
        np.testing.assert_allclose(actual["water_level_m_taw"], expected["water_level_m_taw"])
        np.testing.assert_allclose(
            actual["final_outlet_storage_m3"], expected["final_outlet_storage_m3"]
        )
