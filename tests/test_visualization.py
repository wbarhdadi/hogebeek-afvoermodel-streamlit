import unittest

import pandas as pd

from visualization import build_detail_charts


class DetailChartTests(unittest.TestCase):
    def test_stacks_rainfall_and_discharge_on_a_shared_time_axis(self):
        rainfall = pd.DataFrame({"datetime": pd.date_range("2025-01-01", periods=2, freq="h"), "rainfall_depth_mm": [1.0, 0.0]})
        discharge = pd.DataFrame({"datetime": rainfall["datetime"], "discharge_catchment_1_m3s": [0.0, 1.0]})
        water_level = pd.DataFrame({"datetime": rainfall["datetime"], "water_level_catchment_1_m_taw": [10.0, 10.1]})

        hydrograph, level_chart = build_detail_charts(rainfall, discharge, water_level, 1, 60)

        hydrograph_spec = hydrograph.to_dict()
        self.assertIn("vconcat", hydrograph_spec)
        self.assertEqual(hydrograph_spec["resolve"]["scale"]["x"], "shared")
        self.assertIn("water_level_catchment_1_m_taw", str(level_chart.to_dict()))


if __name__ == "__main__":
    unittest.main()
