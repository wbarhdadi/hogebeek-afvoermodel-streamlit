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


if __name__ == "__main__":
    unittest.main()
