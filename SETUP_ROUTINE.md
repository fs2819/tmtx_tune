# Quick Start: Set Up Auto-Tuning Routine

## Step 1: Install papermill (one-time)
```bash
pip install papermill
```

## Step 2: Create the routine in Claude Code

You have two options:

### Option A: Using `/schedule` skill (Recommended)

In Claude Code, type:
```
/schedule
```

Then follow the prompts. When asked:
- **Type**: Recurring remote agent
- **Name**: `iter-rampdown-tune`
- **Cron expression**: `*/45 * * * *` (every 45 minutes)
- **Script**: Copy-paste the content below into the script field

```python
#!/usr/bin/env python3
import subprocess
import os

os.chdir('/Users/fsheehan/github/fs2819-TokTox/ITER_rampdown')
result = subprocess.run(['python', 'run_and_analyze.py'], capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)
exit(result.returncode)
```

### Option B: Manual cron (alternative)

```bash
(crontab -l 2>/dev/null; echo "*/45 * * * * cd /Users/fsheehan/github/fs2819-TokTox/ITER_rampdown && python run_and_analyze.py >> auto_tune.log 2>&1") | crontab -
```

## Step 3: Verify setup

Check the routine is created:
```bash
# If using /schedule skill, view via:
/schedule list

# If using cron, view via:
crontab -l
```

## Step 4: Monitor progress

Watch the tuning loop:
```bash
cd /Users/fsheehan/github/fs2819-TokTox/ITER_rampdown

# In one terminal, tail the state:
watch -n 10 'cat tune_state.json | jq .'

# In another, tail the notebook log:
tail -f TokaMaker_TORAX_log_tmp.log | grep -E "FAILED|LOW_TEMP|completed"
```

## What happens next

1. **Routine starts** (at next 45-min interval or manually triggered)
2. **Runs notebook** via papermill (30–40 min)
3. **Parses log** for TORAX/TokaMaker status
4. **Updates parameters** if not converged:
   - Too much ohmic heating? → Increase ECRH, slow ramp
   - TokaMaker won't solve? → Reduce pax, add intermediates
5. **Checks convergence**:
   - ✓ All complete + smooth profiles? → Advance to n_rho=125
   - ✗ Still failing? → Loop, iterate again in 45 min

## Manual override if stuck

If the routine doesn't converge after many iterations:

1. **Check state**:
   ```bash
   cat tune_state.json | jq '.history | .[-5:]'  # Last 5 iterations
   ```

2. **Edit notebook directly**:
   - Open `/Users/fsheehan/github/fs2819-TokTox/ITER_rampdown/ITER_TokaMaker_TORAX_rampdown.ipynb` in IDE
   - Manually adjust cells 2 (timing), 6 (pax), 10 (heating/fueling), 12 (Te/ne BCs)
   - Save

3. **Reset iteration counter**:
   ```bash
   python -c "
   import json
   s = json.load(open('tune_state.json'))
   s['iteration'] = 0
   json.dump(s, open('tune_state.json', 'w'), indent=2)
   "
   ```

4. **Continue routine** (wait for next cycle or trigger manually)

## Stopping the routine

If you want to pause or stop:

```bash
# If using /schedule:
/schedule delete iter-rampdown-tune

# If using cron:
crontab -e
# Find and delete the line with "ITER_rampdown"
```

## High-resolution phase

When `tune_state.json` shows `"phase": "high_res"`, the routine:
- Increases to n_rho=125
- Runs the full notebook (up to 30 min allowed)
- Logs results but doesn't auto-iterate anymore

Once high-res completes, check results:
```bash
cat tune_state.json | jq '.phase, .n_rho'
```

If good: save the notebook as a checkpoint. If not: reset to n_rho=25 and continue tuning.
