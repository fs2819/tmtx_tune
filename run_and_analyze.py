#!/usr/bin/env python3
"""
Autonomous TokaMaker/TORAX rampdown tuner.

── HOW TO SWAP IN A DIFFERENT SIMULATION ───────────────────────────────────────
1. Add your new .ipynb or .py file to this repo.
2. Update SIM_TARGET to its filename (e.g. "my_new_rampdown.ipynb" or "run_sim.py").
3. Update LOG_FILE to match the log filename your simulation writes.
4. If the failure modes or tunable parameters differ from the ITER notebook,
   update suggest_and_apply_updates() to match the new cell layout / variable names.
5. Push to git — the remote agent will pick up the new config on the next run.
────────────────────────────────────────────────────────────────────────────────
"""

import json
import subprocess
import sys
import os
import re
from pathlib import Path
from datetime import datetime

# ── CONFIGURATION ────────────────────────────────────────────────────────────
# .ipynb  → executed via papermill
# .py     → executed directly with python
SIM_TARGET = "ITER_TokaMaker_TORAX_rampdown.ipynb"   # change this to .py or .ipynb of sim name
LOG_FILE   = "TokaMaker_TORAX_log_tmp.log"
# ─────────────────────────────────────────────────────────────────────────────

WORK_DIR      = Path(__file__).parent.resolve()
SIM_PATH      = WORK_DIR / SIM_TARGET
LOG_PATH      = WORK_DIR / LOG_FILE
STATE_PATH    = WORK_DIR / "tune_state.json"


# ── Simulation execution ──────────────────────────────────────────────────────

def load_notebook():
    with open(SIM_PATH) as f:
        return json.load(f)

def save_notebook(nb):
    with open(SIM_PATH, "w") as f:
        json.dump(nb, f, indent=1)

def run_simulation():
    """Run SIM_TARGET — papermill for .ipynb, python for .py."""
    try:
        if SIM_PATH.suffix == ".ipynb":
            cmd = ["papermill", str(SIM_PATH), "/tmp/out.ipynb", "-k", "python3"]
        else:
            cmd = [sys.executable, str(SIM_PATH)]
        result = subprocess.run(
            cmd, capture_output=True, timeout=3600, text=True, cwd=str(WORK_DIR)
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Simulation timeout (1 hour)"
    except Exception as e:
        return False, "", str(e)


# ── Log parsing ───────────────────────────────────────────────────────────────

def parse_log_for_errors():
    """Parse simulation log for failure modes and timing."""
    if not LOG_PATH.exists():
        return {}, None

    with open(LOG_PATH) as f:
        log = f.read()

    errors = {
        "torax_low_temp":   "LOW_TEMPERATURE_COLLAPSE" in log,
        "tokamaker_failed": "FAILED" in log,
        "completed": (
            "Loop 1" in log and "FAILED" not in log.split("Loop 1")[-1]
            if "Loop 1" in log else False
        ),
    }

    failure_time = None
    if "Diverted window: t=" in log:
        try:
            m = re.search(r"Diverted window: t=\[([^,]+),\s*([^\]]+)\]", log)
            if m:
                failure_time = float(m.group(2))
        except Exception:
            pass

    return errors, failure_time


# ── Tune state ────────────────────────────────────────────────────────────────

def get_tune_state():
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return {
        "iteration":           0,
        "n_rho":               25,
        "phase":               "converge",
        "rampdown_duration":   150.0,
        "ecrh_multiplier":     1.0,
        "gas_puff_multiplier": 1.0,
        "pax_multiplier":      1.0,
        "history":             [],
    }

def save_tune_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)

def commit_progress(iteration):
    """Stage and commit state/notebook changes. The CCR runtime pushes via outcomes."""
    try:
        subprocess.run(["git", "config", "user.email", "tuner@tmtx-tune"],
                       cwd=str(WORK_DIR), capture_output=True)
        subprocess.run(["git", "config", "user.name", "tmtx-tuner"],
                       cwd=str(WORK_DIR), capture_output=True)
        subprocess.run(["git", "add", str(STATE_PATH), str(SIM_PATH)],
                       cwd=str(WORK_DIR), capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m",
             f"tune: iteration {iteration} [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"],
            cwd=str(WORK_DIR), capture_output=True, check=True
        )
        print(f"Progress committed (iteration {iteration}) — CCR will push on session end")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else str(e)
        print(f"Warning: git commit failed — {stderr}")


# ── Parameter updates (ITER notebook–specific) ────────────────────────────────
# If you swap SIM_TARGET to a different notebook/script, update the cell indices
# and variable names in this function to match the new simulation's structure.

def suggest_and_apply_updates(nb, state, errors, failure_time):
    """Analyze failures and update notebook parameters. Returns True if any changes made."""
    updates_applied = False

    # ── TORAX LOW_TEMPERATURE_COLLAPSE ────────────────────────────────────────
    if errors["torax_low_temp"]:
        print("  → TORAX hit LOW_TEMPERATURE_COLLAPSE")

        cell10 = nb["cells"][10]
        src10 = "".join(cell10["source"])

        old_ecrh_lim_first = state.get("ecrh_limit_first", 5.0)
        new_ecrh_lim_first = old_ecrh_lim_first + 1.0
        if f"T_LIMIT_FIRST: {old_ecrh_lim_first}e6," in src10:
            src10 = src10.replace(
                f"T_LIMIT_FIRST: {old_ecrh_lim_first}e6,",
                f"T_LIMIT_FIRST: {new_ecrh_lim_first}e6,",
            )
            print(f"    ECRH T_LIMIT_FIRST: {old_ecrh_lim_first} → {new_ecrh_lim_first} MW")
            state["ecrh_limit_first"] = new_ecrh_lim_first
            updates_applied = True

        old_ecrh_div = state.get("ecrh_div_mid", 10.0)
        new_ecrh_div = old_ecrh_div + 1.5
        if f"T_DIV_MID: {old_ecrh_div}e6," in src10:
            src10 = src10.replace(
                f"T_DIV_MID: {old_ecrh_div}e6,",
                f"T_DIV_MID: {new_ecrh_div}e6,",
            )
            print(f"    ECRH T_DIV_MID: {old_ecrh_div} → {new_ecrh_div} MW")
            state["ecrh_div_mid"] = new_ecrh_div
            updates_applied = True

        cell10["source"] = src10

        cell2 = nb["cells"][2]
        src2 = "".join(cell2["source"])
        old_dur = state.get("rampdown_duration", 150.0)
        new_dur = old_dur + 10.0
        if f"RAMPDOWN_DURATION = {old_dur}" in src2:
            src2 = src2.replace(
                f"RAMPDOWN_DURATION = {old_dur}",
                f"RAMPDOWN_DURATION = {new_dur}",
            )
            print(f"    Ramp duration: {old_dur} → {new_dur} s")
            state["rampdown_duration"] = new_dur
            updates_applied = True
        cell2["source"] = src2

        if "T_LIMIT_FIRST: 2.0e22" in src10:
            src10 = src10.replace("T_LIMIT_FIRST: 2.0e22", "T_LIMIT_FIRST: 2.5e22")
            print("    Gas puff T_LIMIT_FIRST: 2.0e22 → 2.5e22")
            updates_applied = True
        cell10["source"] = src10

    # ── TOKAMAKER FAILED ──────────────────────────────────────────────────────
    if errors["tokamaker_failed"] and failure_time:
        print(f"  → TokaMaker FAILED at t={failure_time:.1f} s")

        cell6 = nb["cells"][6]
        src6 = "".join(cell6["source"])

        old_mul = state.get("pax_multiplier", 1.0)
        new_mul = old_mul * (0.85 if failure_time < 80 else 0.90)
        if failure_time < 80:
            print("    Early failure (t<80s), reducing pax aggressively")

        for factor_str in ["0.5", "0.6"]:
            if f"pax_flattop*{factor_str}" in src6:
                new_factor = float(factor_str) * new_mul
                src6 = src6.replace(
                    f"pax_flattop*{factor_str}",
                    f"pax_flattop*{new_factor:.2f}",
                )
                print(f"    pax_targets: *{factor_str} → *{new_factor:.2f}")
                updates_applied = True

        cell6["source"] = src6
        state["pax_multiplier"] = new_mul

    # ── Very early failure: relax shape transitions ───────────────────────────
    if failure_time and failure_time < 70:
        print("  → Very early failure — relaxing shape transitions (cell 6)")
        cell6 = nb["cells"][6]
        src6 = "".join(cell6["source"])
        if "delta = [0.0, 0.0, 0.0, 0.40, 0.0, 0.0]" in src6:
            src6 = src6.replace(
                "delta = [0.0, 0.0, 0.0, 0.40, 0.0, 0.0]",
                "delta = [0.0, 0.0, 0.0, 0.30, 0.0, 0.0]",
            )
            print("    delta: 0.40 → 0.30")
            updates_applied = True
        cell6["source"] = src6

    return updates_applied


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.chdir(WORK_DIR)

    print(f"\n{'='*70}")
    print(f"TokaMaker/TORAX Auto-Tuner  {datetime.utcnow().isoformat()} UTC")
    print(f"Simulation: {SIM_TARGET}")
    print(f"{'='*70}\n")

    state = get_tune_state()
    state["iteration"] += 1

    print(f"Iteration {state['iteration']} | Phase: {state['phase']:10s} | n_rho: {state['n_rho']}")
    print(f"Params: rampdown_dur={state['rampdown_duration']:.0f}s  pax_mul={state['pax_multiplier']:.2f}\n")

    # ── Run simulation ────────────────────────────────────────────────────────
    print(f"Running {SIM_TARGET} ...")
    success, stdout, stderr = run_simulation()
    if success:
        print("✓ Simulation completed")
    else:
        print(f"✗ Simulation failed: {stderr[:300]}")

    # ── Parse log ─────────────────────────────────────────────────────────────
    errors, failure_time = parse_log_for_errors()
    print(f"\nLog analysis:")
    print(f"  TORAX low temp:   {errors.get('torax_low_temp')}")
    print(f"  TokaMaker failed: {errors.get('tokamaker_failed')}")
    print(f"  Completed:        {errors.get('completed')}")
    if failure_time:
        print(f"  Failure time:     {failure_time:.1f} s")

    # ── Record history ────────────────────────────────────────────────────────
    state["history"].append({
        "iteration":    state["iteration"],
        "phase":        state["phase"],
        "n_rho":        state["n_rho"],
        "success":      success and errors.get("completed") and not errors.get("torax_low_temp"),
        "errors":       errors,
        "failure_time": failure_time,
        "timestamp":    datetime.utcnow().isoformat(),
    })

    # ── Check convergence ─────────────────────────────────────────────────────
    converged = (
        success
        and errors.get("completed")
        and not errors.get("torax_low_temp")
        and not errors.get("tokamaker_failed")
    )

    if converged:
        print(f"\n✓✓✓ CONVERGED at n_rho={state['n_rho']} ✓✓✓")
        if state["n_rho"] == 25:
            state["n_rho"] = 125
            state["phase"] = "high_res"
            print("Advancing to n_rho=125 for full-resolution run\n")
        else:
            state["phase"] = "done"
            print("High-resolution run complete — tuning finished\n")
    else:
        print("\n✗ Not converged. Updating parameters...\n")
        if SIM_PATH.suffix == ".ipynb":
            nb = load_notebook()
            if suggest_and_apply_updates(nb, state, errors, failure_time):
                save_notebook(nb)
                print("\nNotebook updated — ready for next hourly run\n")
            else:
                print("\nNo automatic fix matched. Claude agent should inspect manually.\n")
        else:
            print("Script-mode: automatic parameter patching not implemented — Claude agent should inspect manually.\n")

    save_tune_state(state)
    print(f"State saved. {len(state['history'])} iterations total.\n")

    commit_progress(state["iteration"])

    return 0 if converged else 1


if __name__ == "__main__":
    sys.exit(main())
