import unittest

import pandas as pd

from rainfall import prepare_rainfall, waterinfo_value_kind


class PrepareRainfallTests(unittest.TestCase):
    def test_reads_waterinfo_unit_from_metadata(self):
        self.assertEqual(waterinfo_value_kind(pd.DataFrame({"ts_unitsymbol": ["mm/h"]})), ("intensity", "mm/h"))
        self.assertEqual(waterinfo_value_kind(pd.DataFrame({"ts_unitsymbol": ["mm"]})), ("depth", "mm"))
    def test_aggregates_depths_to_model_timestep(self):
        source = pd.DataFrame(
            {
                "datetime": pd.date_range("2025-01-01", periods=4, freq="15min"),
                "rainfall_mm": [1.0, 2.0, 3.0, 4.0],
            }
        )

        result = prepare_rainfall(source, value_kind="depth", timestep_minutes=60)

        self.assertEqual(result["rf"].tolist(), [10.0])

    def test_converts_average_intensity_to_depth(self):
        source = pd.DataFrame(
            {
                "datetime": pd.date_range("2025-01-01", periods=4, freq="15min"),
                "rainfall_mmh": [12.0, 12.0, 12.0, 12.0],
            }
        )

        result = prepare_rainfall(source, value_kind="intensity", timestep_minutes=60)

        self.assertEqual(result["rf"].tolist(), [12.0])

    def test_rejects_ambiguous_upsampling(self):
        source = pd.DataFrame(
            {
                "datetime": pd.date_range("2025-01-01", periods=3, freq="60min"),
                "rainfall_mm": [1.0, 2.0, 3.0],
            }
        )

        with self.assertRaisesRegex(ValueError, "upsampling"):
            prepare_rainfall(source, value_kind="depth", timestep_minutes=15)


if __name__ == "__main__":
    unittest.main()
