"""Session-scoped setup state for named Hoge Beek scenarios."""

from dataclasses import dataclass, field
from typing import Any, MutableMapping


@dataclass
class ScenarioSetup:
    name: str
    rainfall_source: str = "Waterinfo (VMM)"
    timestep_minutes: int = 60
    a_threshold_m2: float = 100000.0
    uploaded_inputs: dict[str, Any] = field(default_factory=dict)


def save_scenario_setup(session_state: MutableMapping[str, Any], setup: ScenarioSetup) -> str | None:
    """Retain a valid setup for the current browser session."""
    if not setup.name.strip():
        return "Geef het scenario een naam voordat je het uitvoert."
    session_state["scenario_setup"] = setup
    return None


def saved_scenario_setup(session_state: MutableMapping[str, Any]) -> ScenarioSetup | None:
    """Return the scenario retained for the current browser session, if any."""
    return session_state.get("scenario_setup")
