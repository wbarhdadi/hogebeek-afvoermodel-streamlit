import unittest

import numpy as np
import pandas as pd

from reporting import build_output_tables


class ReportingTests(unittest.TestCase):
    def test_converts_timestep_volume_to_discharge_rate(self):
        discharges, levels, summary = build_output_tables(
            pd.date_range("2025-01-01", periods=2, freq="1h").to_numpy(),
            {1: np.array([0.0, 3600.0])},
            {1: np.array([10.0, 10.5])},
            3600.0,
        )

        self.assertEqual(discharges["discharge_catchment_1_m3s"].tolist(), [0.0, 1.0])
        self.assertEqual(levels["water_level_catchment_1_m_taw"].tolist(), [10.0, 10.5])
        self.assertEqual(summary.loc[0, "total_outflow_m3"], 3600.0)

    def test_exports_hydrographs_only_for_terminal_outlets_but_summarizes_all_subcatchments(self):
        discharges, waterlevels, summary = build_output_tables(
            pd.date_range("2025-01-01", periods=1, freq="1h").to_numpy(),
            {1: np.array([3600.0]), 2: np.array([7200.0])},
            {1: np.array([10.0]), 2: np.array([20.0])},
            3600.0,
            terminal_outlet_ids={2},
        )

        self.assertNotIn("discharge_catchment_1_m3s", discharges)
        self.assertIn("discharge_catchment_2_m3s", discharges)
        self.assertNotIn("water_level_catchment_1_m_taw", waterlevels)
        self.assertEqual(summary["catchment_id"].tolist(), [1, 2])

    def test_adds_event_summary_with_non_overlapping_flooded_depth_classes(self):
        times = pd.date_range("2025-01-01", periods=4, freq="1h").to_numpy()
        _, _, summary = build_output_tables(
            times,
            {1: np.array([0.0, 3600.0, 7200.0, 10800.0])},
            {1: np.array([10.0, 10.2, 10.6, 11.0])},
            3600.0,
            rainfall_depths_mm=np.array([0.0, 2.0, 0.0, 0.0]),
            terrain_by_catchment={1: np.array([[10.995, 10.899], [10.7, np.nan]])},
            pixel_area_m2=100.0,
        )

        event = summary.loc[0]
        self.assertAlmostEqual(event["flooded_area_0_01_to_0_25m_ha"], 0.01)
        self.assertAlmostEqual(event["flooded_area_0_25_to_0_50m_ha"], 0.01)
        self.assertAlmostEqual(event["flooded_area_0_50_to_1m_ha"], 0.0)
        self.assertAlmostEqual(event["flooded_area_1_to_2m_ha"], 0.0)
        self.assertAlmostEqual(event["flooded_area_over_2m_ha"], 0.0)
        self.assertAlmostEqual(event["max_water_depth_m"], 0.3)
        self.assertEqual(event["time_to_peak_minutes"], 120.0)

    def test_keeps_time_to_peak_unavailable_when_rainfall_never_starts(self):
        _, _, summary = build_output_tables(
            pd.date_range("2025-01-01", periods=2, freq="1h").to_numpy(),
            {1: np.array([0.0, 3600.0])},
            {1: np.array([10.0, 10.1])},
            3600.0,
            rainfall_depths_mm=np.array([0.0, 0.0]),
        )

        self.assertIn("time_to_peak_minutes", summary.columns)
        self.assertTrue(np.isnan(summary.loc[0, "time_to_peak_minutes"]))

    def test_excludes_depths_below_the_first_flooded_depth_class(self):
        _, _, summary = build_output_tables(
            pd.date_range("2025-01-01", periods=1, freq="1h").to_numpy(),
            {1: np.array([0.0])},
            {1: np.array([10.0])},
            3600.0,
            terrain_by_catchment={1: np.array([[9.9900000005]])},
            pixel_area_m2=100.0,
        )

        self.assertEqual(summary.loc[0, "flooded_area_0_01_to_0_25m_ha"], 0.0)

    def test_adds_whole_catchment_class_totals_as_sum_of_subcatchments(self):
        _, _, summary = build_output_tables(
            pd.date_range("2025-01-01", periods=1, freq="1h").to_numpy(),
            {1: np.array([0.0]), 2: np.array([0.0])},
            {1: np.array([10.3]), 2: np.array([20.6])},
            3600.0,
            terrain_by_catchment={
                1: np.array([[10.1, 9.9]]),
                2: np.array([[20.1, 19.0]]),
            },
            pixel_area_m2=100.0,
        )

        total = summary.loc[summary["catchment_id"] == "whole_catchment"].iloc[0]
        self.assertEqual(total["summary_scope"], "sum_of_subcatchments")
        self.assertAlmostEqual(total["flooded_area_0_01_to_0_25m_ha"], 0.01)
        self.assertAlmostEqual(total["flooded_area_0_50_to_1m_ha"], 0.01)


if __name__ == "__main__":
    unittest.main()
