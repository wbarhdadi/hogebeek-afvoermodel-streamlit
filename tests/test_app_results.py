import unittest
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest


class ResultsViewTests(unittest.TestCase):
    def test_persisted_results_show_map_free_overview_and_terminal_hydrographs(self):
        times = pd.date_range("2025-01-01", periods=2, freq="h")
        app = AppTest.from_file(Path(__file__).parents[1] / "app.py")
        app.session_state["simulation_results"] = {
            "catchment_ids": [1, 2],
            "discharges": pd.DataFrame({
                "datetime": times,
                "discharge_catchment_1_m3s": [0.0, 1.0],
                "discharge_catchment_2_m3s": [0.0, 2.0],
            }),
            "waterlevels": pd.DataFrame({"datetime": times}),
            "summary": pd.DataFrame({
                "catchment_id": [1, 2, "whole_catchment"],
                "summary_scope": ["subcatchment", "subcatchment", "sum_of_subcatchments"],
                "peak_discharge_m3s": [1.0, 2.0, None],
                "flooded_area_0_01_to_0_25m_ha": [0.01, 0.02, 0.03],
                "flooded_area_0_25_to_0_50m_ha": [0.0, 0.01, 0.01],
                "flooded_area_0_50_to_1m_ha": [0.0, 0.0, 0.0],
                "flooded_area_1_to_2m_ha": [0.0, 0.0, 0.0],
                "flooded_area_over_2m_ha": [0.0, 0.0, 0.0],
            }),
            "rainfall": pd.DataFrame({"datetime": times, "rainfall_depth_mm": [1.0, 0.0]}),
            "rainfall_diagnostics": type("Diagnostics", (), {"total_depth_mm": 1.0})(),
            "timestep_minutes": 60,
        }

        app.run()

        self.assertEqual(len(app.get("vega_lite_chart")), 2)
        self.assertIn(
            "Totaal overstroomd areaal (>= 0,01 m; som van subcatchments)",
            [metric.label for metric in app.metric],
        )
        markdown_values = [markdown.value for markdown in app.markdown]
        self.assertTrue(any("Hydrograaf - terminale uitlaat 1" in value for value in markdown_values))
        self.assertTrue(any("Hydrograaf - terminale uitlaat 2" in value for value in markdown_values))
        self.assertEqual(len(app.get("map")), 0)
        self.assertIn("modelschattingen", " ".join(caption.value for caption in app.caption))


if __name__ == "__main__":
    unittest.main()
