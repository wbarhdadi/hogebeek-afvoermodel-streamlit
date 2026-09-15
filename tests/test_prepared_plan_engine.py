"""Scientific acceptance gates for the prepared-plan hydrology seam."""

from __future__ import annotations

import unittest

import numpy as np

from hydrology import (
    HOutlet,
    QOutlet,
    SubcatchmentInput,
    prepare,
    run,
)


def q_catchment(
    catchment_id: int,
    *,
    directions: np.ndarray | None = None,
    inlets: dict[int, tuple[int, int]] | None = None,
    outlet: QOutlet | None = None,
    runoff_percent: np.ndarray | None = None,
) -> SubcatchmentInput:
    """A one-row, fully connected prepared-input fixture."""
    directions = np.array([[2.0, 2.0]]) if directions is None else directions
    return SubcatchmentInput(
        catchment_id=catchment_id,
        runoff_percent=np.full(directions.shape, 100.0) if runoff_percent is None else runoff_percent,
        slope=np.full(directions.shape, 1.0),
        manning_n=np.full(directions.shape, 0.03),
        flow_direction=directions,
        accumulated_area=np.full(directions.shape, 10.0),
        outlet=(0, directions.shape[1] - 1),
        inlets=inlets or {},
        outlet_rule=outlet or QOutlet(recession_coefficient_s_inv=1.0, max_discharge_m3s=1e9),
    )


class PreparedPlanEngineTests(unittest.TestCase):
    def test_first_interval_pulse_is_processed_and_balanced(self):
        plan = prepare([q_catchment(1)], cell_width_m=10.0, timestep_seconds=60.0, channel_threshold=1.0)

        result = run(plan, [10.0], max_drain_steps=3)

        self.assertGreater(result.generated_effective_volume_m3, 0.0)
        self.assertAlmostEqual(result.generated_effective_volume_m3, result.terminal_outflow_volume_m3 + result.final_retained_volume_m3)
        self.assertLessEqual(abs(result.whole_system_balance_residual_m3), 1e-9)
        self.assertLessEqual(abs(result.per_subcatchment_balance_residual_m3[1]), 1e-9)

    def test_dry_empty_system_stays_dry_and_empty(self):
        result = run(prepare([q_catchment(1)], 10.0, 60.0, 1.0), [0.0])

        np.testing.assert_array_equal(result.outflow_volume_m3[1], [0.0])
        self.assertEqual(result.final_retained_volume_m3, 0.0)
        self.assertEqual(result.drain_steps, 0)

    def test_lag_boundary_pulse_is_not_lost(self):
        # A channel travel time of exactly one interval must occupy lag one.
        plan = prepare([q_catchment(1, runoff_percent=np.array([[100.0, 0.0]]))], cell_width_m=1.0, timestep_seconds=1.0, channel_threshold=1.0)
        result = run(plan, [1.0], max_drain_steps=10)

        self.assertGreater(result.outflow_volume_m3[1][1], 0.0)
        self.assertEqual(result.outflow_volume_m3[1][0], 0.0)

    def test_same_timestep_topological_coupling_is_independent_of_input_order(self):
        upstream = q_catchment(1)
        downstream = q_catchment(2, inlets={1: (0, 0)})
        first = run(prepare([downstream, upstream], 10.0, 60.0, 1.0), [1.0], max_drain_steps=1)
        second = run(prepare([upstream, downstream], 10.0, 60.0, 1.0), [1.0], max_drain_steps=1)

        np.testing.assert_allclose(first.outflow_volume_m3[2], second.outflow_volume_m3[2])
        self.assertGreater(first.outflow_volume_m3[2][0], 0.0)

    def test_multiple_upstreams_at_one_inlet_are_summed(self):
        one = q_catchment(1)
        two = q_catchment(2)
        three = q_catchment(3, inlets={1: (0, 0), 2: (0, 0)})
        combined = run(prepare([one, two, three], 10.0, 60.0, 1.0), [1.0], max_drain_steps=1)
        single = run(prepare([one, q_catchment(3, inlets={1: (0, 0)})], 10.0, 60.0, 1.0), [1.0], max_drain_steps=1)

        self.assertGreater(combined.outflow_volume_m3[3][0], single.outflow_volume_m3[3][0])

    def test_q_outlet_limit_and_dry_drain_preserve_water(self):
        limited = q_catchment(1, outlet=QOutlet(1.0, 0.001))
        result = run(prepare([limited], 10.0, 60.0, 1.0), [10.0], max_drain_steps=2)

        self.assertTrue(np.all(result.outflow_volume_m3[1] <= 6.0 + 1e-12))
        self.assertGreater(result.final_retained_volume_m3, 0.0)
        self.assertTrue(result.drain_limit_reached)
        self.assertLessEqual(abs(result.whole_system_balance_residual_m3), 1e-9)

    def test_h_outlet_spills_only_above_its_storage_capacity(self):
        outlet = HOutlet(max_water_level_m_taw=2.0, levels_m_taw=np.array([0.0, 2.0]), volumes_m3=np.array([0.0, 5.0]))
        result = run(prepare([q_catchment(1, outlet=outlet)], 10.0, 60.0, 1.0), [100.0], max_drain_steps=1)

        self.assertGreater(result.outflow_volume_m3[1][0], 0.0)
        self.assertLessEqual(result.final_outlet_storage_m3[1], 5.0)

    def test_integrated_q_outlet_matches_the_accepted_numerical_transition(self):
        catchment = q_catchment(1, directions=np.array([[2.0]]), outlet=QOutlet(0.01, 1e9))
        result = run(prepare([catchment], 10.0, 60.0, 1.0), [1.0], max_drain_steps=0)

        np.testing.assert_allclose(result.outflow_volume_m3[1], [0.024801939349004404], rtol=1e-9, atol=1e-9)
        self.assertAlmostEqual(result.final_outlet_storage_m3[1], 0.0751980606509956)

    def test_invalid_or_cyclic_topology_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown upstream"):
            prepare([q_catchment(1, inlets={9: (0, 0)})], 10.0, 60.0, 1.0)
        with self.assertRaisesRegex(ValueError, "cycle"):
            prepare([q_catchment(1, inlets={2: (0, 0)}), q_catchment(2, inlets={1: (0, 0)})], 10.0, 60.0, 1.0)

    def test_q_level_curve_never_silently_clamps_reachable_storage(self):
        outlet = QOutlet(1.0, 0.0, np.array([0.0, 1.0]), np.array([0.0, 0.01]))
        with self.assertRaisesRegex(ValueError, "does not cover"):
            run(prepare([q_catchment(1, outlet=outlet)], 10.0, 60.0, 1.0), [1.0], max_drain_steps=0)


if __name__ == "__main__":
    unittest.main()
