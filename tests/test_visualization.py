import unittest

import pandas as pd
import numpy as np

from visualization import build_detail_charts, classify_waterdepth, build_waterdepth_map


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

    def test_classifies_maximum_water_depth_in_the_six_agreed_classes(self):
        depths = np.array([[0.0, 0.01, 0.25], [0.5, 1.0, 2.1]])

        classes = classify_waterdepth(depths)

        self.assertEqual(
            classes.tolist(),
            [["<0.01 m", "0.01-0.25 m", "0.25-0.50 m"],
             ["0.50-1 m", "1-2 m", ">2 m"]],
        )

    def test_builds_a_raster_cell_map_with_all_six_depth_classes(self):
        chart = build_waterdepth_map(
            np.array([[0.0, 0.01, 0.25], [0.5, 1.0, 2.1]]),
            x_origin=0.0,
            y_origin=2.0,
            pixel_size=1.0,
        )

        spec = chart.to_dict()
        self.assertEqual(spec["mark"]["type"], "rect")
        self.assertEqual(spec["encoding"]["color"]["scale"]["domain"], [
            "<0.01 m", "0.01-0.25 m", "0.25-0.50 m", "0.50-1 m", "1-2 m", ">2 m",
        ])


if __name__ == "__main__":
    unittest.main()
