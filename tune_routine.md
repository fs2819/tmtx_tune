# ITER Rampdown Auto-Tuning Routine

## Overview
This routine autonomously iterates your rampdown parameters until TORAX + TokaMaker converge, then runs at high resolution.

## Setup Instructions

### 1. Install papermill (one-time)
```bash
pip install papermill
```

### 2. Create the Claude Code routine
```bash
cd /Users/fsheehan/github/fs2819-TokTox/ITER_rampdown
```

Then in Claude Code, run:
```
/schedule create routine-iter-rampdown \
  --interval "every 45 minutes" \
  --script "python run_and_analyze.py" \
  --cwd "/Users/fsheehan/github/fs2819-TokTox/ITER_rampdown"
```

Or use the Skill tool:
```
/schedule
```
And fill in:
- **Routine name**: `routine-iter-rampdown`
- **Interval**: Every 45 minutes (one iteration per run)
- **Command**: `python run_and_analyze.py`
- **Working directory**: `/Users/fsheehan/github/fs2819-TokTox/ITER_rampdown`

### 3. How it works

Each iteration (45 min cycle):
1. **Runs** the notebook via `papermill`
2. **Parses** the TokaMaker/TORAX log for failures:
   - `LOW_TEMPERATURE_COLLAPSE` → increase ECRH, slow ramp
   - `TokaMaker FAILED` → adjust pax_targets, add intermediates
3. **Updates** cells 2 (timing), 6 (pax_targets), 10 (heating/fueling)
4. **Saves** notebook and state
5. **Checks convergence**:
   - If all runs complete: advance to n_rho=125, run for 30 min
   - If still failing: apply next parameter tweak, loop

### 4. States and transitions

```
[Start]
  ↓
[n_rho=25, Phase='converge']  ← iterate parameters here until:
  - TORAX completes full sim
  - No LOW_TEMPERATURE_COLLAPSE
  - No TokaMaker FAILED
  ↓
[n_rho=125, Phase='high_res']  ← run for up to 30 min
  ↓
[Phase='done', inspect results]
```

### 5. Monitor progress

Check status anytime:
```bash
cat tune_state.json
tail -f TokaMaker_TORAX_log_tmp.log
```

The routine logs to `tune_state.json`:
```json
{
  "iteration": 5,
  "n_rho": 25,
  "phase": "converge",
  "history": [
    {
      "iteration": 1,
      "success": false,
      "errors": {"torax_low_temp": true, ...},
      "failure_time": 67.3
    },
    ...
  ]
}
```

### 6. Manual interventions

If the routine gets stuck:
1. Check `tune_state.json` to see what's failing
2. Edit `ITER_TokaMaker_TORAX_rampdown.ipynb` directly
3. Reset the iteration counter:
   ```bash
   python -c "import json; s=json.load(open('tune_state.json')); s['iteration']=0; json.dump(s, open('tune_state.json','w'), indent=2)"
   ```
4. Let routine continue

## Parameter Tuning Strategy

The `run_and_analyze.py` script uses this logic:

### On `LOW_TEMPERATURE_COLLAPSE`:
- **Symptom**: TORAX hits edge Te floor around T_DIV_MID or later
- **Fix**: 
  - Increase `ECRH` at limited phases (T_DIV_MID, T_LIMIT_FIRST, T_LIMIT_ROUND)
  - Slow ramp (increase `RAMPDOWN_DURATION`)
  - Increase `gas_puff_S_total` at ramp phases

### On `TokaMaker FAILED`:
- **Symptom**: Free-boundary solve doesn't converge, usually mid-ramp
- **Fix**:
  - Lower `pax_targets` (reduce pressure mismatch)
  - Add intermediate equilibrium (break a large transition into two)
  - Relax shape transitions (smaller delta, kappa steps)

### After convergence (before n_rho=125):
- Verify profiles are smooth (no kinks)
- Verify j_phi > 0 everywhere (no current reversal)
- Verify l_i reasonable (not jumping wildly)

## Expected timeline

- **Iterations to converge**: 3–8 (depending on initial config)
- **Time per iteration**: 45 min (notebook runtime ~30–40 min + overhead)
- **High-res phase**: 30 min at n_rho=125
- **Total**: 3–6 hours for full convergence + high-res

## Abort / Restart

To stop the routine:
```bash
/schedule delete routine-iter-rampdown
```

To reset and start over:
```bash
rm tune_state.json
/schedule create routine-iter-rampdown ...
```