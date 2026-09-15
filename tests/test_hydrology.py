import unittest

import numpy as np

from hydrology import accumulate_travel_time, compute_effective_recharge, route_Q_channel


class HydrologyTests(unittest.TestCase):
    def test_effective_recharge_preserves_missing_cells(self):
        result = compute_effective_recharge(10.0, np.array([[50.0, -9999.0]]))
        np.testing.assert_allclose(result[0, 0], 5.0)
        self.assertTrue(np.isnan(result[0, 1]))

    def test_d8_channel_routing_collects_lateral_rainfall_at_outlet(self):
        flow_direction = np.array([[2.0, 8.0], [np.nan, np.nan]])
        routed = route_Q_channel(
            flow_direction, np.array([[2.0, 1.0], [np.nan, np.nan]]),
            np.array([[True, True], [False, False]]), {}, {},
            np.array([[10.0, 0.0], [np.nan, np.nan]]), (0, 1), 5.0,
        )
        np.testing.assert_allclose(routed[0, 1], 0.25)

    def test_accumulates_travel_time_to_outlet(self):
        travel = np.array([[3.0, 2.0, 1.0]])
        directions = np.array([[2.0, 2.0, 2.0]])
        result = accumulate_travel_time(travel, directions, (0, 2))
        np.testing.assert_allclose(result, [[5.0, 2.0, 0.0]])


if __name__ == "__main__":
    unittest.main()
