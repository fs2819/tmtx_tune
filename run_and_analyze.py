#!/usr/bin/env python3
"""
Run the ITER rampdown notebook and analyze outputs for convergence.
Used by Claude Code routine for autonomous parameter tuning.
"""

import json
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime

NOTEBOOK_PATH = "/Users/fsheehan/github/fs2819-TokTox/ITER_rampdown/ITER_TokaMaker_TORAX_rampdown.ipynb"
LOG_PATH = "/Users/fsheehan/github/fs2819-TokTox/ITER_rampdown/TokaMaker_TORAX_log_tmp.log"
STATE_PATH = "/Users/fsheehan/github/fs2819-TokTox/ITER_rampdown/tune_state.json"

def load_notebook():
    """Load the notebook as dict."""
    with open(NOTEBOOK_PATH) as f:
        return json.load(f)

def save_notebook(nb):
    """Save notebook back."""
    with open(NOTEBOOK_PATH, 'w') as f:
        json.dump(nb, f, indent=1)

def run_notebook():
    """Execute the notebook via papermill and return success/failure."""
    try:
        result = subprocess.run(
            ["papermill", NOTEBOOK_PATH, "/tmp/out.ipynb", "-k", "python3"],
            capture_output=True,
            timeout=3600,
            text=True
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Notebook execution timeout (1 hour)"
    except Exception as e:
        return False, "", str(e)

def parse_log_for_errors():
    """Parse TokaMaker log for failure modes."""
    if not os.path.exists(LOG_PATH):
        return None, None

    with open(LOG_PATH) as f:
        log = f.read()

    errors = {
        'torax_low_temp': 'LOW_TEMPERATURE_COLLAPSE' in log,
        'tokamaker_failed': 'FAILED' in log and 'TX:' in log,
        'converged': 'converged' in log.lower(),
        'completed': 'Loop 1' in log and 'FAILED' not in log.split('Loop 1')[-1],
    }

    # Extract failure time if available
    if 'Diverted window: t=' in log:
        try:
            import re
            m = re.search(r'Diverted window: t=\[([^,]+),\s*([^\]]+)\]', log)
            if m:
                failure_time = float(m.group(2))
                return errors, failure_time
        except:
            pass

    return errors, None

def get_tune_state():
    """Load or initialize tuning state."""
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {
        'iteration': 0,
        'n_rho': 25,
        'last_failure_time': 0,
        'phase': 'converge',  # 'converge' or 'refine'
        'history': []
    }

def save_tune_state(state):
    """Save tuning state."""
    with open(STATE_PATH, 'w') as f:
        json.dump(state, f, indent=2)

def suggest_parameter_updates(nb, state, errors, failure_time):
    """
    Analyze failures and suggest parameter changes.
    Returns dict of {cell_index: old_code, new_code} updates.
    """
    updates = {}

    # If TORAX hits LOW_TEMPERATURE_COLLAPSE, we already fixed the edge Te right_bc
    # Next step: increase intermediate ECRH or fueling, slow ramp rate
    if errors['torax_low_temp']:
        # Slower ramp, more heating
        nb_dict = load_notebook()
        cell2_src = ''.join(nb_dict['cells'][2]['source'])

        # Try slower ramp: increase RAMPDOWN_DURATION
        if 'RAMPDOWN_DURATION = 150' in cell2_src:
            old = 'RAMPDOWN_DURATION = 150'
            new = 'RAMPDOWN_DURATION = 160'
            updates[2] = (old, new)

        # Increase ECRH taper (cell 10)
        cell10_src = ''.join(nb_dict['cells'][10]['source'])
        if 'T_LIMIT_FIRST: 5.0e6' in cell10_src:
            old = 'ecrh_powers = {\n    T_FLAT_START: 20.0e6,\n    T_RAMP_START: 20.0e6,\n    T_DIV_MID: 10.0e6,\n    T_LIMIT_FIRST: 5.0e6,\n    T_LIMIT_ROUND: 2.0e6,\n    T_FINAL: 0.0,\n}'
            new = 'ecrh_powers = {\n    T_FLAT_START: 20.0e6,\n    T_RAMP_START: 20.0e6,\n    T_DIV_MID: 12.0e6,\n    T_LIMIT_FIRST: 7.0e6,\n    T_LIMIT_ROUND: 3.0e6,\n    T_FINAL: 0.0,\n}'
            updates[10] = (old, new)

    # If TokaMaker failed early, adjust pax_targets lower or add intermediate eqdsk
    if errors['tokamaker_failed'] and failure_time:
        if failure_time < 100:
            # Add intermediate equilibrium or lower pax targets
            cell6_src = ''.join(nb_dict['cells'][6]['source'])
            if 'pax_flattop*0.5' in cell6_src:
                # Gradually lower pax targets
                old = 'pax_targets = [\n    pax_flattop,\n    pax_flattop,\n    pax_flattop*0.5,\n    pax_flattop*0.25,\n    pax_flattop*0.08,\n    pax_end,\n]'
                new = 'pax_targets = [\n    pax_flattop,\n    pax_flattop,\n    pax_flattop*0.6,\n    pax_flattop*0.35,\n    pax_flattop*0.12,\n    pax_end,\n]'
                updates[6] = (old, new)

    return updates

def apply_updates(nb, updates):
    """Apply cell source code updates to notebook."""
    for cell_idx, (old, new) in updates.items():
        c = nb['cells'][cell_idx]
        src = ''.join(c['source']) if isinstance(c['source'], list) else c['source']
        if old in src:
            new_src = src.replace(old, new)
            c['source'] = new_src
            print(f"Updated cell {cell_idx}")
        else:
            print(f"WARNING: Could not find old string in cell {cell_idx}")
    return nb

def main():
    print(f"\n{'='*60}")
    print(f"ITER Rampdown Auto-Tuner: {datetime.now().isoformat()}")
    print(f"{'='*60}\n")

    state = get_tune_state()
    state['iteration'] += 1

    print(f"Iteration {state['iteration']}, Phase: {state['phase']}, n_rho: {state['n_rho']}")

    # Run notebook
    print("\nRunning notebook...")
    success, stdout, stderr = run_notebook()

    if success:
        print("✓ Notebook executed successfully")
    else:
        print("✗ Notebook failed")
        print(f"Error: {stderr[:500]}")

    # Parse results
    errors, failure_time = parse_log_for_errors()
    print(f"\nLog Analysis:")
    print(f"  TORAX low temp collapse: {errors['torax_low_temp']}")
    print(f"  TokaMaker failed: {errors['tokamaker_failed']}")
    print(f"  Completed: {errors['completed']}")
    if failure_time:
        print(f"  Failure time: {failure_time:.1f} s")

    # Record history
    state['history'].append({
        'iteration': state['iteration'],
        'success': success and errors['completed'] and not errors['torax_low_temp'],
        'errors': errors,
        'failure_time': failure_time,
        'timestamp': datetime.now().isoformat()
    })

    # Check convergence
    converged = (success and errors['completed'] and
                 not errors['torax_low_temp'] and
                 not errors['tokamaker_failed'])

    if converged:
        print(f"\n✓ CONVERGED at n_rho={state['n_rho']}")
        if state['n_rho'] < 125:
            state['n_rho'] = 125
            state['phase'] = 'high_res'
            print(f"  Advancing to n_rho=125 for 30 minute run...")
        else:
            print(f"  High-res run complete!")
            state['phase'] = 'done'
    else:
        print(f"\n✗ Not converged yet. Updating parameters...")
        nb = load_notebook()
        updates = suggest_parameter_updates(nb, state, errors, failure_time)

        if updates:
            print(f"  Applying {len(updates)} parameter updates...")
            nb = apply_updates(nb, updates)
            save_notebook(nb)
            print(f"  Notebook updated, ready for next iteration")
        else:
            print(f"  No clear update path found. Manual inspection needed.")

    save_tune_state(state)
    print(f"\nState saved: {len(state['history'])} iterations logged\n")

    return 0 if converged else 1

if __name__ == '__main__':
    sys.exit(main())