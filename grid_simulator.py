"""
Grid Dynamics and State Simulator
Evaluates electrical power grid operational state (NOMINAL, STRESSED, CRITICAL)
based on real-time grid frequency (Hz) and voltage (per-unit / p.u.).

If frequency or voltage reaches a collapse limit, or the grid stays CRITICAL
for longer than the allowed time span, the simulator declares
COMPLETE GRID FAILURE and stops the telemetry.
"""

import time
import json
import argparse
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Dict, List, Optional


class GridState(str, Enum):
    NOMINAL = "NOMINAL"
    STRESSED = "STRESSED"
    CRITICAL = "CRITICAL"
    FAILED = "COMPLETE GRID FAILURE"


@dataclass
class GridThresholds:
    """
    Standard operational thresholds for 50 Hz grid system.
    Adjustable for 60 Hz grids or regional utility codes.
    """
    nominal_frequency: float = 50.0  # Hz
    nominal_voltage_pu: float = 1.0  # Per-unit (1.0 pu = nominal voltage)

    # Frequency Limits (Hz)
    # Nominal: [49.85, 50.15]
    # Stressed: [49.50, 49.85) or (50.15, 50.50]
    # Critical: < 49.50 (UFLS zone) or > 50.50 (generator trip zone)
    freq_nominal_min: float = 49.85
    freq_nominal_max: float = 50.15
    freq_stressed_min: float = 49.50
    freq_stressed_max: float = 50.50

    # Voltage Limits (Per-Unit)
    # Nominal: [0.95, 1.05] (within +/- 5%)
    # Stressed: [0.90, 0.95) or (1.05, 1.10] (+/- 10%)
    # Critical: < 0.90 (voltage collapse risk) or > 1.10 (dielectric breakdown risk)
    voltage_nominal_min: float = 0.95
    voltage_nominal_max: float = 1.05
    voltage_stressed_min: float = 0.90
    voltage_stressed_max: float = 1.10

    # Complete grid failure (blackout) limits
    freq_collapse_min: float = 47.50    # Hz, generators trip on under-frequency
    freq_collapse_max: float = 51.50    # Hz, generators trip on over-speed
    voltage_collapse_min: float = 0.70  # pu, voltage collapse
    voltage_collapse_max: float = 1.20  # pu, insulation breakdown
    critical_duration_limit_s: float = 5.0  # max continuous seconds allowed in CRITICAL


@dataclass
class GridEvaluation:
    grid_state: GridState
    frequency_state: GridState
    voltage_state: GridState
    frequency_hz: float
    voltage_pu: float
    reasons: List[str]

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["grid_state"] = self.grid_state.value
        data["frequency_state"] = self.frequency_state.value
        data["voltage_state"] = self.voltage_state.value
        return data


def check_collapse(
    frequency_hz: float,
    voltage_pu: float,
    thresholds: Optional[GridThresholds] = None,
) -> str:
    """Returns a failure reason if a hard collapse limit is reached, else ''."""
    th = thresholds or GridThresholds()
    if frequency_hz <= th.freq_collapse_min or frequency_hz >= th.freq_collapse_max:
        return f"Frequency reached collapse limit ({frequency_hz:.3f} Hz)"
    if voltage_pu <= th.voltage_collapse_min or voltage_pu >= th.voltage_collapse_max:
        return f"Voltage reached collapse limit ({voltage_pu:.3f} pu)"
    return ""


def evaluate_grid_state(
    frequency_hz: float,
    voltage_pu: float,
    thresholds: Optional[GridThresholds] = None,
) -> GridEvaluation:
    """
    Determines the operational state of the power grid (NOMINAL, STRESSED, CRITICAL)
    based on frequency and voltage.

    Priority hierarchy:
      1. CRITICAL if either frequency OR voltage is in critical condition.
      2. STRESSED if neither is critical, but either is in stressed condition.
      3. NOMINAL if both are within normal operating bounds.
    """
    if thresholds is None:
        thresholds = GridThresholds()

    reasons: List[str] = []

    # 1. Frequency Evaluation
    if thresholds.freq_nominal_min <= frequency_hz <= thresholds.freq_nominal_max:
        freq_state = GridState.NOMINAL
    elif thresholds.freq_stressed_min <= frequency_hz < thresholds.freq_nominal_min:
        freq_state = GridState.STRESSED
        reasons.append(
            f"Under-frequency warning: {frequency_hz:.3f} Hz is below nominal ({thresholds.freq_nominal_min:.2f} Hz)"
        )
    elif thresholds.freq_nominal_max < frequency_hz <= thresholds.freq_stressed_max:
        freq_state = GridState.STRESSED
        reasons.append(
            f"Over-frequency warning: {frequency_hz:.3f} Hz is above nominal ({thresholds.freq_nominal_max:.2f} Hz)"
        )
    elif frequency_hz < thresholds.freq_stressed_min:
        freq_state = GridState.CRITICAL
        reasons.append(
            f"CRITICAL Under-frequency: {frequency_hz:.3f} Hz violates emergency limit ({thresholds.freq_stressed_min:.2f} Hz). Risk of Under-Frequency Load Shedding (UFLS)!"
        )
    else:  # frequency_hz > thresholds.freq_stressed_max
        freq_state = GridState.CRITICAL
        reasons.append(
            f"CRITICAL Over-frequency: {frequency_hz:.3f} Hz violates emergency limit ({thresholds.freq_stressed_max:.2f} Hz). Risk of generator overspeed trip!"
        )

    # 2. Voltage Evaluation
    if thresholds.voltage_nominal_min <= voltage_pu <= thresholds.voltage_nominal_max:
        volt_state = GridState.NOMINAL
    elif thresholds.voltage_stressed_min <= voltage_pu < thresholds.voltage_nominal_min:
        volt_state = GridState.STRESSED
        reasons.append(
            f"Under-voltage warning: {voltage_pu:.3f} pu is below nominal ({thresholds.voltage_nominal_min:.2f} pu)"
        )
    elif thresholds.voltage_nominal_max < voltage_pu <= thresholds.voltage_stressed_max:
        volt_state = GridState.STRESSED
        reasons.append(
            f"Over-voltage warning: {voltage_pu:.3f} pu is above nominal ({thresholds.voltage_nominal_max:.2f} pu)"
        )
    elif voltage_pu < thresholds.voltage_stressed_min:
        volt_state = GridState.CRITICAL
        reasons.append(
            f"CRITICAL Under-voltage: {voltage_pu:.3f} pu violates emergency lower limit ({thresholds.voltage_stressed_min:.2f} pu). Severe risk of voltage collapse!"
        )
    else:  # voltage_pu > thresholds.voltage_stressed_max
        volt_state = GridState.CRITICAL
        reasons.append(
            f"CRITICAL Over-voltage: {voltage_pu:.3f} pu violates emergency upper limit ({thresholds.voltage_stressed_max:.2f} pu). Severe risk of insulation breakdown!"
        )

    # 3. Overall Grid State Synthesis (worst-case priority rule)
    if freq_state == GridState.CRITICAL or volt_state == GridState.CRITICAL:
        overall_state = GridState.CRITICAL
    elif freq_state == GridState.STRESSED or volt_state == GridState.STRESSED:
        overall_state = GridState.STRESSED
    else:
        overall_state = GridState.NOMINAL
        reasons.append("Frequency and voltage are both within nominal operational boundaries.")

    return GridEvaluation(
        grid_state=overall_state,
        frequency_state=freq_state,
        voltage_state=volt_state,
        frequency_hz=frequency_hz,
        voltage_pu=voltage_pu,
        reasons=reasons,
    )


class GridSimulator:
    """
    Dynamic Power Grid Physics Simulator.
    Models:
      - Active power (MW) balance & frequency dynamics via the Swing Equation.
      - Reactive power (MVAr) balance & voltage dynamics via Automatic Voltage Regulator (AVR) sensitivity.
      - Battery Energy Storage System (BESS) fast frequency & voltage droop response.
      - Complete grid failure (blackout) on collapse limits or sustained CRITICAL state.
    """

    def __init__(
        self,
        nominal_frequency: float = 50.0,
        nominal_voltage_pu: float = 1.0,
        inertia_h: float = 5.0,  # System inertia constant H (seconds)
        damping_d: float = 1.0,  # Load damping factor D (MW/Hz)
        voltage_tau: float = 1.2,  # AVR / voltage restoration time constant (seconds)
        voltage_kq: float = 0.003,  # dV/dQ reactive power sensitivity (pu / MVAr)
        base_power_mw: float = 100.0,
        base_reactive_mvar: float = 30.0,
        bess_capacity_mwh: float = 5.0,
        bess_initial_soc: float = 0.90,
        bess_max_power_mw: float = 15.0,
        thresholds: Optional[GridThresholds] = None,
    ):
        self.nominal_frequency = nominal_frequency
        self.nominal_voltage_pu = nominal_voltage_pu
        self.thresholds = thresholds or GridThresholds(
            nominal_frequency=nominal_frequency,
            nominal_voltage_pu=nominal_voltage_pu,
        )

        # Dynamic physics parameters
        self.inertia_h = inertia_h
        self.damping_d = damping_d
        self.voltage_tau = voltage_tau
        self.voltage_kq = voltage_kq

        # Power conditions
        self.base_power_mw = base_power_mw
        self.generation_mw = base_power_mw
        self.load_mw = base_power_mw

        self.base_reactive_mvar = base_reactive_mvar
        self.generation_mvar = base_reactive_mvar
        self.load_mvar = base_reactive_mvar

        # Current state
        self.frequency_hz = nominal_frequency
        self.voltage_pu = nominal_voltage_pu
        self.rocof_hz_per_s = 0.0
        self.dvoltage_dt = 0.0
        self.current_time = 0.0

        # Failure tracking
        self.critical_time_s = 0.0
        self.grid_failed = False
        self.failure_reason = ""
        self.last_telemetry: Dict = {}

        # BESS (Battery Energy Storage System)
        self.bess_capacity_mwh = bess_capacity_mwh
        self.bess_soc = bess_initial_soc
        self.bess_max_power_mw = bess_max_power_mw
        self.bess_active_mw = 0.0
        self.bess_reactive_mvar = 0.0

    def step(
        self,
        dt: float = 0.1,
        generation_mw: Optional[float] = None,
        load_mw: Optional[float] = None,
        generation_mvar: Optional[float] = None,
        load_mvar: Optional[float] = None,
        enable_bess_control: bool = True,
    ) -> Dict:
        """
        Advances the power grid simulation by dt seconds.
        Once the grid has failed, the simulation is frozen and the final
        telemetry is returned unchanged.
        """
        if self.grid_failed:
            return self.last_telemetry

        if generation_mw is not None:
            self.generation_mw = generation_mw
        if load_mw is not None:
            self.load_mw = load_mw
        if generation_mvar is not None:
            self.generation_mvar = generation_mvar
        if load_mvar is not None:
            self.load_mvar = load_mvar

        # -------------------------------------------------------------
        # 1. BESS Response (Fast Frequency & Voltage Support)
        # -------------------------------------------------------------
        if enable_bess_control and self.bess_soc > 0.15:
            # Active power support for frequency deviation
            if self.frequency_hz < 49.90:  # Underfrequency injection
                deficit = (self.nominal_frequency - self.frequency_hz) * 30.0
                self.bess_active_mw = min(self.bess_max_power_mw, deficit)
            elif self.frequency_hz > 50.10:  # Overfrequency absorption
                surplus = (self.frequency_hz - self.nominal_frequency) * 30.0
                self.bess_active_mw = -min(self.bess_max_power_mw, surplus)
            else:
                self.bess_active_mw = 0.0

            # Reactive power support for voltage deviation
            if self.voltage_pu < 0.97:  # Undervoltage capacitive boost
                v_err = 0.97 - self.voltage_pu
                self.bess_reactive_mvar = min(10.0, v_err * 80.0)
            elif self.voltage_pu > 1.03:  # Overvoltage inductive absorption
                v_err = self.voltage_pu - 1.03
                self.bess_reactive_mvar = -min(10.0, v_err * 80.0)
            else:
                self.bess_reactive_mvar = 0.0
        else:
            self.bess_active_mw = 0.0
            self.bess_reactive_mvar = 0.0

        # Update BESS State of Charge (SoC)
        if self.bess_capacity_mwh > 0:
            # Energy (MWh) = MW * (dt / 3600)
            energy_delta_mwh = (self.bess_active_mw * (dt / 3600.0))
            self.bess_soc -= energy_delta_mwh / self.bess_capacity_mwh
            self.bess_soc = max(0.0, min(1.0, self.bess_soc))

        # -------------------------------------------------------------
        # 2. Active Power & Frequency Dynamics (Swing Equation)
        # -------------------------------------------------------------
        # Power balance: Generation + BESS - Load
        power_balance_mw = self.generation_mw + self.bess_active_mw - self.load_mw
        freq_error = self.frequency_hz - self.nominal_frequency

        # df/dt = (P_balance - D * delta_f) / (2 * H)
        self.rocof_hz_per_s = (
            power_balance_mw - (self.damping_d * freq_error)
        ) / (2.0 * self.inertia_h)

        self.frequency_hz += self.rocof_hz_per_s * dt

        # -------------------------------------------------------------
        # 3. Reactive Power & Voltage Dynamics (AVR & Sensitivity Model)
        # -------------------------------------------------------------
        # Reactive power balance: Q_gen + Q_bess - Q_load
        reactive_balance_mvar = self.generation_mvar + self.bess_reactive_mvar - self.load_mvar
        voltage_error = self.nominal_voltage_pu - self.voltage_pu

        # dV/dt = [(V_nominal - V) + Kq * Q_balance] / tau_v
        self.dvoltage_dt = (
            voltage_error + (self.voltage_kq * reactive_balance_mvar)
        ) / self.voltage_tau

        self.voltage_pu += self.dvoltage_dt * dt

        # Keep voltage within physical boundaries
        self.voltage_pu = max(0.40, min(1.40, self.voltage_pu))

        self.current_time += dt

        # -------------------------------------------------------------
        # 4. State Evaluation
        # -------------------------------------------------------------
        evaluation = evaluate_grid_state(
            frequency_hz=self.frequency_hz,
            voltage_pu=self.voltage_pu,
            thresholds=self.thresholds,
        )
        overall_state = evaluation.grid_state.value

        # -------------------------------------------------------------
        # 5. Complete Grid Failure Detection
        # -------------------------------------------------------------
        # Track continuous time spent in CRITICAL
        if evaluation.grid_state == GridState.CRITICAL:
            self.critical_time_s += dt
        else:
            self.critical_time_s = 0.0

        th = self.thresholds
        failure_reason = check_collapse(self.frequency_hz, self.voltage_pu, th)
        if not failure_reason and self.critical_time_s >= th.critical_duration_limit_s:
            failure_reason = (
                f"Grid remained CRITICAL for {self.critical_time_s:.1f} s "
                f"(limit {th.critical_duration_limit_s:.1f} s)"
            )

        if failure_reason:
            self.failure_reason = failure_reason
            self.grid_failed = True
            overall_state = GridState.FAILED.value
            evaluation.reasons.append(f"COMPLETE GRID FAILURE: {failure_reason}")

        telemetry = {
            "timestamp": round(self.current_time, 2),
            "grid_state": overall_state,
            "frequency_state": evaluation.frequency_state.value,
            "voltage_state": evaluation.voltage_state.value,
            "frequency_hz": round(self.frequency_hz, 4),
            "rocof_hz_per_s": round(self.rocof_hz_per_s, 4),
            "voltage_pu": round(self.voltage_pu, 4),
            "dvoltage_dt": round(self.dvoltage_dt, 4),
            "generation_mw": round(self.generation_mw, 2),
            "load_mw": round(self.load_mw, 2),
            "power_balance_mw": round(power_balance_mw, 2),
            "generation_mvar": round(self.generation_mvar, 2),
            "load_mvar": round(self.load_mvar, 2),
            "reactive_balance_mvar": round(reactive_balance_mvar, 2),
            "bess_active_mw": round(self.bess_active_mw, 2),
            "bess_reactive_mvar": round(self.bess_reactive_mvar, 2),
            "bess_soc_percent": round(self.bess_soc * 100.0, 1),
            "critical_time_s": round(self.critical_time_s, 2),
            "grid_failed": self.grid_failed,
            "failure_reason": self.failure_reason,
            "reasons": evaluation.reasons,
        }

        self.last_telemetry = telemetry
        return telemetry


def get_state_color_badge(state: str) -> str:
    """Returns ANSI colored badge for terminal representation."""
    if state == "NOMINAL":
        return "\033[92m[ NOMINAL  ]\033[0m"  # Green
    elif state == "STRESSED":
        return "\033[93m[ STRESSED ]\033[0m"  # Yellow
    elif state == "CRITICAL":
        return "\033[91m[ CRITICAL ]\033[0m"  # Red
    elif state == "COMPLETE GRID FAILURE":
        return "\033[97;41m[ BLACKOUT ]\033[0m"  # White on red
    return f"[{state}]"


def run_simulation_scenario(
    duration: float = 28.0,
    dt: float = 0.2,
    enable_realtime_delay: bool = True,
    output_json: bool = False,
):
    """
    Executes a scenario demonstrating:
      Phase 1 (0s - 3s)   : NOMINAL - Baseline equilibrium
      Phase 2 (3s - 7s)   : STRESSED - Single generator trip (-12 MW)
      Phase 3 (7s - 13s)  : CRITICAL - Second generator trip (-18 MW) & reactive surge (+35 MVAr)
      Phase 4 (13s - 18s) : STRESSED - BESS & Fast Peaker (+20 MW, +10 MVAr) arrest collapse
      Phase 5 (18s - 28s) : NOMINAL - Full reserve restoration & capacitor banks online

    If the grid collapses (hard limits or too long in CRITICAL), the run stops
    immediately and COMPLETE GRID FAILURE is shown.
    """
    sim = GridSimulator()
    total_steps = int(duration / dt)

    if not output_json:
        print("=" * 105)
        print(" POWER GRID REAL-TIME DYNAMICS & HEALTH STATE SIMULATOR")
        print(" Evaluating States: [ NOMINAL | STRESSED | CRITICAL | COMPLETE GRID FAILURE ]")
        print("=" * 105)
        print(
            f"{'Time':^6} | {'Freq(Hz)':^9} | {'Volt(pu)':^9} | {'P-Bal(MW)':^10} | {'Q-Bal(MVar)':^10} | {'BESS SoC':^8} | {'Overall State':^14} | {'Operational Diagnostics / Actions'}"
        )
        print("-" * 105)

    last_state = None

    for step in range(total_steps):
        t = round(step * dt, 2)
        event_note = ""

        # Event Timeline
        if abs(t - 3.0) < (dt / 2):
            sim.generation_mw = 88.0
            event_note = "EVENT: Thermal Unit #1 Tripped (-12 MW Loss)"
        elif abs(t - 7.0) < (dt / 2):
            sim.generation_mw = 70.0  # -30 MW total
            sim.load_mvar = 65.0       # +35 MVAr load jump
            event_note = "EVENT: Thermal Unit #2 Tripped (-18 MW) & Inductive Load Surge (+35 MVAr)"
        elif abs(t - 13.0) < (dt / 2):
            sim.generation_mw = 90.0  # Peaker synchronizes
            event_note = "ACTION: Fast-Start Peaker Plant Online (+20 MW Support)"
        elif abs(t - 18.0) < (dt / 2):
            sim.generation_mw = 100.0   # Secondary AGC restoration
            sim.generation_mvar = 65.0  # Shunt capacitor bank online
            event_note = "ACTION: Spinning Reserve Dispatched (+10 MW) & Capacitor Bank Energized (+35 MVAr)"

        telemetry = sim.step(dt=dt)

        if output_json:
            print(json.dumps(telemetry))
        else:
            current_state = telemetry["grid_state"]
            state_badge = get_state_color_badge(current_state)
            reasons_str = "; ".join(telemetry["reasons"])
            display_note = event_note if event_note else reasons_str

            # Print state transition banner if state changed
            if last_state is not None and current_state != last_state:
                print(f"       >>> STATE TRANSITION: {last_state} ---> {current_state} <<<")
            last_state = current_state

            print(
                f"{telemetry['timestamp']:>5.1f}s | "
                f"{telemetry['frequency_hz']:>8.3f} | "
                f"{telemetry['voltage_pu']:>8.3f} | "
                f"{telemetry['power_balance_mw']:>9.1f} | "
                f"{telemetry['reactive_balance_mvar']:>9.1f} | "
                f"{telemetry['bess_soc_percent']:>6.1f}% | "
                f"{state_badge} | "
                f"{display_note}"
            )

        # Stop telemetry on complete grid failure
        if telemetry["grid_failed"]:
            if output_json:
                print(json.dumps({
                    "event": "COMPLETE_GRID_FAILURE",
                    "timestamp": telemetry["timestamp"],
                    "reason": telemetry["failure_reason"],
                }))
            else:
                print("\n" + "!" * 105)
                print(f"{'*** COMPLETE GRID FAILURE ***':^105}")
                print(f"{'Telemetry halted at t = ' + str(telemetry['timestamp']) + ' s':^105}")
                print(f"{telemetry['failure_reason']:^105}")
                print("!" * 105)
            break

        if enable_realtime_delay:
            time.sleep(dt)


def main():
    parser = argparse.ArgumentParser(
        description="Grid State Simulator (Nominal, Stressed, Critical, Complete Grid Failure based on Frequency and Voltage)"
    )
    parser.add_argument(
        "--eval",
        action="store_true",
        help="Evaluate a single static frequency and voltage reading",
    )
    parser.add_argument(
        "--freq",
        type=float,
        default=50.0,
        help="Grid frequency in Hz for evaluation (default: 50.0)",
    )
    parser.add_argument(
        "--voltage",
        type=float,
        default=1.0,
        help="Grid voltage in per-unit (pu) for evaluation (default: 1.0)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Simulation run duration in seconds (default: 30.0)",
    )
    parser.add_argument(
        "--dt",
        type=float,
        default=0.2,
        help="Time step in seconds (default: 0.2)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Run simulation as fast as possible without real-time delay",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON formatted stream",
    )

    args = parser.parse_args()

    if args.eval:
        failure = check_collapse(args.freq, args.voltage)
        if failure:
            print("\n" + "!" * 60)
            print(f"{'*** COMPLETE GRID FAILURE ***':^60}")
            print(f"{failure:^60}")
            print("!" * 60 + "\n")
            return

        result = evaluate_grid_state(args.freq, args.voltage)
        print("\n" + "=" * 60)
        print(" GRID STATE EVALUATION RESULT")
        print("=" * 60)
        print(f" Frequency:        {result.frequency_hz:.3f} Hz")
        print(f" Frequency State:  {get_state_color_badge(result.frequency_state.value)}")
        print(f" Voltage:          {result.voltage_pu:.3f} p.u.")
        print(f" Voltage State:    {get_state_color_badge(result.voltage_state.value)}")
        print("-" * 60)
        print(f" OVERALL STATE:    {get_state_color_badge(result.grid_state.value)}")
        print(" Diagnostics:")
        for r in result.reasons:
            print(f"   * {r}")
        print("=" * 60 + "\n")
    else:
        run_simulation_scenario(
            duration=args.duration,
            dt=args.dt,
            enable_realtime_delay=not args.fast,
            output_json=args.json,
        )


if __name__ == "__main__":
    main()