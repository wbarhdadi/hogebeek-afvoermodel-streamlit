import unittest
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest


class ResultsViewTests(unittest.TestCase):
    def test_persisted_results_show_hydrograph_and_water_level_chart(self):
        times = pd.date_range("2025-01-01", periods=2, freq="h")
        app = AppTest.from_file(Path(__file__).parents[1] / "app.py")
        app.session_state["simulation_results"] = {
            "catchment_ids": [1],
            "discharges": pd.DataFrame({"datetime": times, "discharge_catchment_1_m3s": [0.0, 1.0]}),
            "waterlevels": pd.DataFrame({"datetime": times, "water_level_catchment_1_m_taw": [10.0, 10.1]}),
            "summary": pd.DataFrame({"catchment_id": [1], "peak_discharge_m3s": [1.0], "max_water_level_m_taw": [10.1]}),
            "rainfall": pd.DataFrame({"datetime": times, "rainfall_depth_mm": [1.0, 0.0]}),
            "rainfall_diagnostics": type("Diagnostics", (), {"total_depth_mm": 1.0})(),
            "timestep_minutes": 60,
        }

        app.run()

        self.assertEqual(len(app.get("vega_lite_chart")), 2)
        self.assertIn("Piekafvoer", [metric.label for metric in app.metric])
        self.assertIn("Maximale waterdiepte", [metric.label for metric in app.metric])
        self.assertIn("Tijd tot piek", [metric.label for metric in app.metric])
        self.assertIn("modelschattingen", " ".join(caption.value for caption in app.caption))


if __name__ == "__main__":
    unittest.main()
