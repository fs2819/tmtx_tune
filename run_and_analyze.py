#!/usr/bin/env python3
"""
Run the ITER rampdown notebook and autonomously tune parameters.
Claude Code routine runs this every 45 minutes.
"""

import json
import subprocess
import sys
import os
import re
from pathlib import Path
from datetime import datetime

# Paths
WORK_DIR = Path("/Users/fsheehan/github/tmtx_tune")
NOTEBOOK_PATH = WORK_DIR / "ITER_TokaMaker_TORAX_rampdown.ipynb"
LOG_PATH = WORK_DIR / "TokaMaker_TORAX_log_tmp.log"
STATE_PATH = WORK_DIR / "tune_state.json"

def load_notebook():
    """Load notebook as dict."""
    with open(NOTEBOOK_PATH) as f:
        return json.load(f)

def save_notebook(nb):
    """Save notebook."""
    with open(NOTEBOOK_PATH, 'w') as f:
        json.dump(nb, f, indent=1)

def run_notebook():
    """Execute notebook via papermill."""
    try:
        result = subprocess.run(
            ["papermill", str(NOTEBOOK_PATH), "/tmp/out.ipynb", "-k", "python3"],
            capture_output=True,
            timeout=3600,
            text=True,
            cwd=str(WORK_DIR)
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Notebook timeout (1 hour)"
    except Exception as e:
        return False, "", str(e)

def parse_log_for_errors():
    """Parse TokaMaker log for failure modes and timing."""
    if not LOG_PATH.exists():
        return {}, None

    with open(LOG_PATH) as f:
        log = f.read()

    errors = {
        'torax_low_temp': 'LOW_TEMPERATURE_COLLAPSE' in log,
        'tokamaker_failed': 'FAILED' in log,
        'completed': ('Loop 1' in log and
                     'FAILED' not in log.split('Loop 1')[-1] if 'Loop 1' in log else False),
    }

    # Extract failure time
    failure_time = None
    if 'Diverted window: t=' in log:
        try:
            m = re.search(r'Diverted window: t=\[([^,]+),\s*([^\]]+)\]', log)
            if m:
                failure_time = float(m.group(2))
        except:
            pass

    return errors, failure_time

def get_tune_state():
    """Load or init tuning state."""
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return {
        'iteration': 0,
        'n_rho': 25,
        'phase': 'converge',
        'rampdown_duration': 150.0,
        'ecrh_multiplier': 1.0,
        'gas_puff_multiplier': 1.0,
        'pax_multiplier': 1.0,
        'history': []
    }

def save_tune_state(state):
    """Save tuning state."""
    with open(STATE_PATH, 'w') as f:
        json.dump(state, f, indent=2)

def update_cell_value(src, pattern, old_val, new_val):
    """Replace a numeric value in cell source."""
    search = pattern.replace('{old}', str(old_val))
    replace = pattern.replace('{old}', str(new_val))
    if search in src:
        return src.replace(search, replace), True
    return src, False

def suggest_and_apply_updates(nb, state, errors, failure_time):
    """Analyze failures and update notebook parameters."""
    updates_applied = False

    # =========================================================================
    # TORAX LOW_TEMPERATURE_COLLAPSE
    # =========================================================================
    if errors['torax_low_temp']:
        print("  → TORAX hit LOW_TEMPERATURE_COLLAPSE")

        # Strategy 1: Increase ECRH heating in limited phases
        cell10 = nb['cells'][10]
        src10 = ''.join(cell10['source'])

        old_ecrh_lim_first = state.get('ecrh_limit_first', 5.0)
        new_ecrh_lim_first = old_ecrh_lim_first + 1.0

        if f'T_LIMIT_FIRST: {old_ecrh_lim_first}e6,' in src10:
            src10 = src10.replace(
                f'T_LIMIT_FIRST: {old_ecrh_lim_first}e6,',
                f'T_LIMIT_FIRST: {new_ecrh_lim_first}e6,'
            )
            print(f"    Updated ECRH T_LIMIT_FIRST: {old_ecrh_lim_first} → {new_ecrh_lim_first} MW")
            state['ecrh_limit_first'] = new_ecrh_lim_first
            updates_applied = True

        old_ecrh_div = state.get('ecrh_div_mid', 10.0)
        new_ecrh_div = old_ecrh_div + 1.5

        if f'T_DIV_MID: {old_ecrh_div}e6,' in src10:
            src10 = src10.replace(
                f'T_DIV_MID: {old_ecrh_div}e6,',
                f'T_DIV_MID: {new_ecrh_div}e6,'
            )
            print(f"    Updated ECRH T_DIV_MID: {old_ecrh_div} → {new_ecrh_div} MW")
            state['ecrh_div_mid'] = new_ecrh_div
            updates_applied = True

        cell10['source'] = src10

        # Strategy 2: Slow down ramp (increase RAMPDOWN_DURATION)
        cell2 = nb['cells'][2]
        src2 = ''.join(cell2['source'])

        old_dur = state.get('rampdown_duration', 150.0)
        new_dur = old_dur + 10.0

        if f'RAMPDOWN_DURATION = {old_dur}' in src2:
            src2 = src2.replace(
                f'RAMPDOWN_DURATION = {old_dur}',
                f'RAMPDOWN_DURATION = {new_dur}'
            )
            print(f"    Slowed ramp: {old_dur} → {new_dur} s ({round((-15 + 0.25) / new_dur, 3)} MA/s)")
            state['rampdown_duration'] = new_dur
            updates_applied = True

        cell2['source'] = src2

        # Strategy 3: Increase gas puffing
        if 'T_LIMIT_FIRST: 2.0e22' in src10:
            src10 = src10.replace(
                'T_LIMIT_FIRST: 2.0e22',
                'T_LIMIT_FIRST: 2.5e22'
            )
            print(f"    Increased gas puff at T_LIMIT_FIRST: 2.0e22 → 2.5e22")
            updates_applied = True

        cell10['source'] = src10

    # =========================================================================
    # TOKAMAKER FAILED
    # =========================================================================
    if errors['tokamaker_failed'] and failure_time:
        print(f"  → TokaMaker FAILED at t={failure_time:.1f} s")

        # Lower pax targets to ease pressure mismatch
        cell6 = nb['cells'][6]
        src6 = ''.join(cell6['source'])

        # Adjust multiplier on pax_targets
        old_mul = state.get('pax_multiplier', 1.0)
        new_mul = old_mul * 0.90  # Reduce by 10%

        if failure_time < 80:
            print(f"    Early failure (t<80), reducing pax aggressively")
            new_mul = old_mul * 0.85

        # Replace pax_flattop * X with lower X
        for factor_str in ['0.5', '0.6']:
            if f'pax_flattop*{factor_str}' in src6:
                new_factor = float(factor_str) * new_mul
                src6 = src6.replace(
                    f'pax_flattop*{factor_str}',
                    f'pax_flattop*{new_factor:.2f}'
                )
                print(f"    Reduced pax_targets: *{factor_str} → *{new_factor:.2f}")
                updates_applied = True

        cell6['source'] = src6
        state['pax_multiplier'] = new_mul

    # =========================================================================
    # LOW FAILURE TIME: add intermediate equilibrium or relax transitions
    # =========================================================================
    if failure_time and failure_time < 70:
        print(f"  → Very early failure, check shape transitions in cell 6")
        cell6 = nb['cells'][6]
        src6 = ''.join(cell6['source'])

        # Check if we can loosen kappa/delta transitions
        if 'delta = [0.0, 0.0, 0.0, 0.40, 0.0, 0.0]' in src6:
            # Reduce the 0.40 jump
            src6 = src6.replace(
                'delta = [0.0, 0.0, 0.0, 0.40, 0.0, 0.0]',
                'delta = [0.0, 0.0, 0.0, 0.30, 0.0, 0.0]'
            )
            print(f"    Relaxed delta: 0.40 → 0.30")
            updates_applied = True

        cell6['source'] = src6

    return updates_applied

def main():
    os.chdir(WORK_DIR)

    print(f"\n{'='*70}")
    print(f"ITER Rampdown Auto-Tuner: {datetime.now().isoformat()}")
    print(f"{'='*70}\n")

    state = get_tune_state()
    state['iteration'] += 1

    print(f"Iteration {state['iteration']} | Phase: {state['phase']:10s} | n_rho: {state['n_rho']}")
    print(f"Current params: rampdown_dur={state['rampdown_duration']:.0f}s, pax_mul={state['pax_multiplier']:.2f}\n")

    # =========================================================================
    # RUN NOTEBOOK
    # =========================================================================
    print("Running notebook via papermill...")
    success, stdout, stderr = run_notebook()

    if success:
        print("✓ Notebook executed")
    else:
        print(f"✗ Notebook failed: {stderr[:200]}")

    # =========================================================================
    # PARSE LOG
    # =========================================================================
    errors, failure_time = parse_log_for_errors()

    print(f"\nLog analysis:")
    print(f"  TORAX low temp:  {errors['torax_low_temp']}")
    print(f"  TokaMaker fail:  {errors['tokamaker_failed']}")
    print(f"  Completed:       {errors['completed']}")
    if failure_time:
        print(f"  Failure time:    {failure_time:.1f} s")

    # =========================================================================
    # RECORD HISTORY
    # =========================================================================
    state['history'].append({
        'iteration': state['iteration'],
        'phase': state['phase'],
        'n_rho': state['n_rho'],
        'success': success and errors['completed'] and not errors['torax_low_temp'],
        'errors': errors,
        'failure_time': failure_time,
        'timestamp': datetime.now().isoformat()
    })

    # =========================================================================
    # CHECK CONVERGENCE
    # =========================================================================
    converged = (success and errors['completed'] and
                 not errors['torax_low_temp'] and
                 not errors['tokamaker_failed'])

    if converged:
        print(f"\n✓✓✓ CONVERGED at n_rho={state['n_rho']} ✓✓✓")
        if state['n_rho'] == 25:
            state['n_rho'] = 125
            state['phase'] = 'high_res'
            print(f"Advancing to n_rho=125 for full-resolution 30-minute run...\n")
        else:
            state['phase'] = 'done'
            print(f"High-resolution run complete!\n")
    else:
        print(f"\n✗ Not converged. Updating parameters...\n")
        nb = load_notebook()

        if suggest_and_apply_updates(nb, state, errors, failure_time):
            save_notebook(nb)
            print(f"\nNotebook updated, ready for next iteration in 45 min\n")
        else:
            print(f"\nNo automatic fix found. Manual inspection may be needed.\n")

    save_tune_state(state)
    print(f"State saved. {len(state['history'])} iterations total.\n")

    return 0 if converged else 1

if __name__ == '__main__':
    sys.exit(main())
