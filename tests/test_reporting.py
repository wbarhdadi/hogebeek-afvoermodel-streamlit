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

    def test_adds_event_summary_from_rainfall_and_maximum_water_depth(self):
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
        self.assertAlmostEqual(event["flooded_area_0_01m_ha"], 0.02)
        self.assertAlmostEqual(event["flooded_area_0_10m_ha"], 0.02)
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

    def test_does_not_count_depths_below_a_flooded_area_threshold(self):
        _, _, summary = build_output_tables(
            pd.date_range("2025-01-01", periods=1, freq="1h").to_numpy(),
            {1: np.array([0.0])},
            {1: np.array([10.0])},
            3600.0,
            terrain_by_catchment={1: np.array([[9.9900000005]])},
            pixel_area_m2=100.0,
        )

        self.assertEqual(summary.loc[0, "flooded_area_0_01m_ha"], 0.0)


if __name__ == "__main__":
    unittest.main()
