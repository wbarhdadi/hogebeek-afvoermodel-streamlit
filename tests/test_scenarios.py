import unittest
from pathlib import Path

import pandas as pd

from scenario import (
    ScenarioSetup,
    build_scenario_comparison,
    input_differences,
    save_baseline,
    save_comparison,
    save_scenario_setup,
    saved_scenario_setup,
)
from streamlit.testing.v1 import AppTest


class ScenarioSetupTests(unittest.TestCase):
    def test_requires_a_name_before_a_setup_can_be_saved(self):
        state = {}

        result = save_scenario_setup(state, ScenarioSetup(name="  "))

        self.assertEqual(result, "Geef het scenario een naam voordat je het uitvoert.")
        self.assertNotIn("scenario_setup", state)

    def test_retains_named_setup_and_uploaded_inputs_for_editing(self):
        state = {}
        setup = ScenarioSetup(
            name="Voorjaarsbui",
            rainfall_source="CSV upload",
            timestep_minutes=30,
            a_threshold_m2=125000,
            uploaded_inputs={"geodata": b"geodata", "measures": [b"measure"]},
        )

        result = save_scenario_setup(state, setup)

        self.assertIsNone(result)
        retained = state["scenario_setup"]
        self.assertEqual(retained.name, "Voorjaarsbui")
        self.assertEqual(retained.timestep_minutes, 30)
        self.assertEqual(retained.uploaded_inputs["geodata"], b"geodata")
        self.assertEqual(retained.uploaded_inputs["measures"], [b"measure"])
        self.assertIs(saved_scenario_setup(state), retained)

    def test_setup_ui_requires_a_name_and_hides_raw_model_factors(self):
        app = AppTest.from_file(Path(__file__).parents[1] / "app.py")
        app.run()

        labels = [element.label for element in app.number_input]
        self.assertIn("Modeltijdstap [minuten]", labels)
        self.assertIn("Drempel stroomopwaarts gebied A_threshold [m²] (kanaalcel)", labels)
        self.assertNotIn("Factor helling (D8slope)", labels)
        self.assertNotIn("Factor Manning n", labels)
        self.assertNotIn("Factor runoff (%)", labels)
        subheaders = [
            subheader.value
            for subheader in app.subheader
            if subheader.value[:1] in {"1", "2", "3", "4"}
        ]
        self.assertEqual(
            subheaders,
            [
                "1. Ruimtelijke invoer",
                "2. Neerslag",
                "3. Maatregelen en modelinstelling",
                "4. Controleren en uitvoeren",
            ],
        )
        self.assertEqual(len(app.table), 0)

        app.button[0].click().run()

        self.assertIn(
            "Geef het scenario een naam voordat je het uitvoert.",
            [error.value for error in app.error],
        )

    def test_setup_ui_uses_the_saved_scenario_name(self):
        app = AppTest.from_file(Path(__file__).parents[1] / "app.py")
        app.session_state["scenario_setup"] = ScenarioSetup(name="Voorjaarsbui")

        app.run()

        self.assertEqual(app.text_input[0].value, "Voorjaarsbui")
        self.assertIn(
            "Opgeslagen sessiescenario: 'Voorjaarsbui'",
            " ".join(caption.value for caption in app.caption),
        )


class ScenarioComparisonTests(unittest.TestCase):
    def setUp(self):
        self.baseline = {
            "name": "Referentie",
            "inputs": {"geodata": "a", "catchments": "b", "rainfall": "c"},
            "results": self._results([1.0, 2.0], [0.2, 0.4]),
        }
        self.comparison = {
            "name": "Bufferbekken",
            "inputs": {"geodata": "a", "catchments": "b", "rainfall": "c"},
            "results": self._results([1.5, 3.0], [0.3, 0.6]),
        }

    @staticmethod
    def _results(discharge, areas):
        times = pd.date_range("2025-01-01", periods=2, freq="h")
        return {
            "discharges": pd.DataFrame({
                "datetime": times,
                "discharge_catchment_2_m3s": discharge,
            }),
            "detail_discharges": pd.DataFrame({
                "datetime": times,
                "discharge_catchment_1_m3s": discharge,
            }),
            "summary": pd.DataFrame({
                "catchment_id": [1, 2, "whole_catchment"],
                "summary_scope": ["subcatchment", "subcatchment", "sum_of_subcatchments"],
                "peak_discharge_m3s": [max(discharge), max(discharge), None],
                "flooded_area_0_01_to_0_25m_ha": [areas[0], areas[1], sum(areas)],
                "flooded_area_0_25_to_0_50m_ha": [0.0, 0.0, 0.0],
                "flooded_area_0_50_to_1m_ha": [0.0, 0.0, 0.0],
                "flooded_area_1_to_2m_ha": [0.0, 0.0, 0.0],
                "flooded_area_over_2m_ha": [0.0, 0.0, 0.0],
            }),
        }

    def test_retains_one_baseline_and_one_named_comparison_in_the_session(self):
        state = {}

        save_baseline(state, self.baseline)
        save_comparison(state, self.comparison)

        self.assertEqual(state["baseline"]["name"], "Referentie")
        self.assertEqual(state["comparison"]["name"], "Bufferbekken")

    def test_reports_inputs_that_differ_other_than_selected_measures(self):
        changed = {**self.comparison, "inputs": {**self.comparison["inputs"], "rainfall": "other"}}

        self.assertEqual(input_differences(self.baseline, changed), ["rainfall"])

    def test_reports_a_changed_rainfall_interpretation(self):
        baseline = {**self.baseline, "inputs": {**self.baseline["inputs"], "rainfall_value_kind": "depth"}}
        comparison = {**self.comparison, "inputs": {**self.comparison["inputs"], "rainfall_value_kind": "intensity"}}

        self.assertEqual(input_differences(baseline, comparison), ["rainfall_value_kind"])

    def test_calculates_absolute_and_non_zero_baseline_percentage_changes(self):
        overview = build_scenario_comparison(self.baseline, self.comparison)

        terminal = overview["terminal_peaks"].iloc[0]
        self.assertEqual(terminal["change_m3s"], 1.0)
        self.assertEqual(terminal["change_percent"], 50.0)
        self.assertAlmostEqual(
            overview["subcatchments"].loc[1, "flooded_area_0_01_to_0_25m_ha_change"], 0.1
        )

    def test_omits_percentage_when_the_baseline_value_is_zero(self):
        self.baseline["results"]["summary"].loc[0, "flooded_area_0_25_to_0_50m_ha"] = 0.0
        self.comparison["results"]["summary"].loc[0, "flooded_area_0_25_to_0_50m_ha"] = 1.0

        overview = build_scenario_comparison(self.baseline, self.comparison)

        self.assertIsNone(
            overview["subcatchments"].loc[1, "flooded_area_0_25_to_0_50m_ha_change_percent"]
        )


if __name__ == "__main__":
    unittest.main()
