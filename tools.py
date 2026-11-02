"""
Grid Tools for checking state and simulating single steps.
"""

from grid_simulator import get_grid_state, evaluate_grid_state


def check_grid_state_tool(frequency_hz: float, voltage_pu: float) -> dict:
    """Evaluates grid state (NOMINAL, STRESSED, CRITICAL) based on frequency and voltage."""
    return evaluate_grid_state(frequency_hz, voltage_pu)
