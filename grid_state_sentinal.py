"""
Grid State Sentinel - Automated Real-Time Monitoring and Alerting.
"""

from grid_simulator import get_grid_state


class GridStateSentinel:
    """Monitors telemetry and detects transitions across NOMINAL, STRESSED, and CRITICAL."""

    def __init__(self):
        self.last_state = None

    def process_telemetry(self, telemetry: dict) -> dict:
        freq = telemetry.get("frequency_hz", 50.0)
        volt = telemetry.get("voltage_pu", 1.0)
        overall_state, freq_state, volt_state = get_grid_state(freq, volt)

        state_changed = (self.last_state != overall_state)
        self.last_state = overall_state

        advisories = []
        if overall_state == "CRITICAL":
            if freq_state == "CRITICAL":
                advisories.append("Trigger Under-Frequency Load Shedding (UFLS) & emergency BESS injection.")
            if volt_state == "CRITICAL":
                advisories.append("Engage capacitor banks/STATCOM to prevent voltage collapse.")
        elif overall_state == "STRESSED":
            advisories.append("Dispatch spinning reserve and adjust AVR excitation.")

        return {
            "timestamp": telemetry.get("timestamp", 0.0),
            "grid_state": overall_state,
            "frequency_state": freq_state,
            "voltage_state": volt_state,
            "state_changed": state_changed,
            "advisories": advisories,
        }
