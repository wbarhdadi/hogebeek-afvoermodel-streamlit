import unittest
from pathlib import Path

from scenario import ScenarioSetup, save_scenario_setup, saved_scenario_setup
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


if __name__ == "__main__":
    unittest.main()
