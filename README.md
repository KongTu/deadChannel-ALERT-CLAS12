# deadChannel-ALERT-CLAS12

Service task for CLAS12: find **dead / bad AHDC wires** in the ALERT detector by looking
at each wire's ADC value as a function of run number, and flagging runs where a wire
behaves abnormally relative to its neighboring runs.

The AHDC (ALERT Hyper Drift Chamber) has **8 layers** with wire counts
`{47, 56, 56, 72, 72, 87, 87, 99}` = **576 wires** total. For every run, the CLAS12
monitoring/timeline system produces one ADC value per wire. This project pulls those
values into a flat CSV and analyzes them.

---

## Where the numbers come from

```
coatjava reconstruction        clas12-timeline                this repo
   (AHDC::adc bank)   ─────►  per-run, per-wire ADC   ─────►  CSV  ─►  plots + flagged runs
                              timelines (HIPO files)
```

The per-wire ADC values shown on the CLAS12 monitoring timeline
(e.g. `https://clas12mon.jlab.org/rgl/pass0_v10.3_alert/alert/timeline/`)
are stored as `GraphErrors` (one point per run) inside HIPO files. `dump_alert_adc_csv.groovy`
dumps them to CSV; `analyze_alert_adc.py` (or the notebook) analyzes the CSV.

> **Note on the quantity.** The timeline value is the per-wire ADC integral
> *normalized to the trigger count*, not a raw average ADC. It is the right quantity for
> tracking a wire's relative health across runs.

---

## Repository contents

| File | What it is |
|------|------------|
| `dump_alert_adc_csv.groovy` | Reads the deployed ALERT ADC timeline HIPO files (input: clas12mon URL or a directory of timeline `.hipo` files) and writes the per-wire CSV. Run on the JLab `ifarm`. |
| `analyze_alert_adc.py` | Command-line tool: plot one wire vs run, and/or scan all wires and flag abnormal runs. |
| `analyze_alert_adc.ipynb` | Same analysis as a Jupyter notebook (plots render inline). |
| `all.csv` | Full dataset — 576 wires × 1112 runs (runs 21317–23061). |
| `test.csv` | Smaller subset (layers 1–2 only) for quick tests. |
| `flagged.csv` | Example scan output: the flagged (run, wire) entries. |

### CSV formats

Input (`all.csv`, `test.csv`):

```
run, layer_number, layer_code, wire, value, graph_name
```

- `layer_number` — 1–8
- `layer_code`   — bank encoding `superlayer*10 + layer` (`11,21,22,31,32,41,42,51`)
- `wire`         — wire number within the layer
- `value`        — trigger-normalized ADC for that wire in that run

Output (`flagged.csv`) adds the analysis columns:

```
run, layer_number, layer_code, wire, value, local_median, robust_z, reason
```

---

## Requirements

**Producing the CSV** (`dump_alert_adc_csv.groovy`) runs on the JLab `ifarm` and needs
**coatjava** installed (it provides the `run-groovy` launcher with the HIPO/GROOT
libraries). The timeline HIPO files live on the JLab filesystem, so this step runs there.
The CSVs are already committed here, so you can skip this step unless you want to refresh
the data.

**Analysis** runs anywhere with Python 3 and:

```bash
pip install pandas numpy matplotlib
# for the notebook:
pip install jupyterlab
```

---

## Quick start (analysis only)

Scan every wire and write the flagged runs + print a summary of the worst wires:

```bash
python analyze_alert_adc.py all.csv --scan flagged.csv
```

Plot a single wire and list its flagged runs:

```bash
python analyze_alert_adc.py all.csv --layer 1 --wire 1 --plot l1_w1.png
```

Use `test.csv` instead of `all.csv` for a fast first run.

### Options

| Option | Default | Meaning |
|--------|---------|---------|
| `--layer N --wire M` | – | which wire to plot |
| `--plot FILE.png` | auto | output plot path |
| `--scan [FILE.csv]` | `alert_adc_flagged.csv` | scan all wires, write flagged runs |
| `--window N` | 11 | rolling-median window (runs) used as the local baseline |
| `--threshold X` | 5.0 | robust-z cutoff for an outlier |
| `--dead-frac F` | 0.2 | flag a value below `F × (wire median)` |

### Or use the notebook

Open `analyze_alert_adc.ipynb` in `jupyter lab`, set `CSV_PATH` in the first cell
(`all.csv` or `test.csv`), and run top to bottom. Plots render inline. The cells let you
plot a chosen wire, scan all wires, save `flagged.csv`, and auto-plot the worst offenders.

---

## Re-generating the CSV (optional, on ifarm)

```bash
~/coatjava/bin/run-groovy dump_alert_adc_csv.groovy \
  https://clas12mon.jlab.org/rgl/pass0_v10.3_alert/alert/timeline/ all.csv
```

The input is either the **clas12mon timeline URL** (as above) or a **directory** of
deployed timeline `.hipo` files — not a single HIPO file. It keeps only AHDC ADC wire
graphs (`ahdc_adc_layer<L>_wire_number<WW>`) and skips ATOF / time / residual graphs.
Sanity check:

```bash
cut -d, -f6 all.csv | sort -u    # should list only ahdc_adc_... graph names
```

---

## How a wire gets flagged

Each wire is judged **against itself in nearby runs**, because ADC levels drift slowly
over a run period (gas conditions, thresholds, calibration). For one wire, sorted by run,
two cuts are applied and a run is flagged if **either** fires; the `reason` column
records which one (`low/dead` takes precedence if both fire).

**Cut 1 — `outlier` (local):** `|robust_z| > threshold` (default 5).
Catches a run whose value departs sharply from the neighboring runs (spike or dropout).

**Cut 2 — `low/dead` (global to the wire):** `value < dead_frac × (wire median)`
(default 0.2). Catches a value that has collapsed relative to the wire's own typical
level, even if the collapse is gradual or sustained.

**Why two cuts.** `robust_z` catches sharp local changes, but if a wire is dead for many
runs in a row, the local median inside that stretch also goes to zero, so `robust_z`
stops seeing anything unusual — the dead runs look normal *relative to their (also-dead)
neighbors*. Cut 2 compares against the wire's overall median instead, and catches the
sustained death.

### Glossary of the variables

**`value`** — the per-wire ADC quantity for that run (trigger-normalized integral).

**`local_median`** — centered rolling median of `value` over `--window` runs: the level
you would *expect* for this run given its neighbors. A median is used (not a mean) so
that a few dead runs inside the window don't drag the baseline down.

**`detrended`** — `value − local_median`: the residual after removing the slow drift,
i.e. how far this run is from local normal.

**`MAD`** — *median absolute deviation* of the residuals:
`MAD = median( |detrended − median(detrended)| )`. A robust measure of the normal
run-to-run scatter. The usual standard deviation is unusable here because it *squares*
deviations, so a single dead run inflates it — and the inflated spread then hides the
very anomaly that caused it. A median ignores extreme values by construction: up to half
the points can be anomalous before MAD is misled.

**`1.4826`** — a unit-conversion constant, nothing more. For Gaussian data, MAD
converges to `0.6745 σ` (0.6745 is the z-value of the 75th percentile — the median
absolute deviation spans the middle 50% of a normal distribution). Dividing by 0.6745,
i.e. multiplying by `1/0.6745 = 1.4826`, rescales MAD so that on clean Gaussian data it
equals the standard deviation.

**`scale`** — `1.4826 × MAD`: the *robust standard deviation* — the estimate of this
wire's normal scatter, immune to the anomalies being hunted. (Worked example: for
residuals `0, ±1, ±0.5, 0, ±1, 0, 20`, the classical SD is ≈ 6.0 — inflated 5× by the
single outlier — while `scale` ≈ 1.1, the honest scatter of the healthy points. The
outlier is 3σ under the classical SD but ~18 robust sigmas under `scale`.)

**`robust_z`** — `detrended / scale`: how many robust sigmas this run sits from its
local baseline. Read exactly like an ordinary z-score ("7σ below expectation"), but
built from medians throughout so it stays honest when part of the series is bad.
Edge case: a perfectly flat series has `MAD = 0`, so `scale = 0`; Cut 1 is then disabled
(`robust_z` set to 0) and only Cut 2 can fire.

**`dead_floor`** — `dead_frac × (wire median over all runs)`: the threshold for Cut 2.
Note a wire that is dead in *every* run has a median ≈ 0, so its `dead_floor` ≈ 0 and
Cut 2 never fires — that case is caught by `permanently_low` below.

**`flag` / `reason`** — `flag` is the OR of the two cuts; `reason` is `outlier` or
`low/dead`.

### The scan summary (per wire)

**`frac_flagged`** — `n_flagged / n_runs`: fraction of this wire's runs that were
flagged. Used for ranking suspects; no automatic cut is applied to it.

**`permanently_low`** — `(wire median) < dead_frac × global_typical`, where
`global_typical` is the median across all 576 wires of each wire's median value.
Catches wires that are essentially dead in every run, which the per-run cuts
structurally cannot flag.

Note that the tool ranks suspects but does not by itself declare a wire dead — the
final per-wire verdict (e.g. a cut on `frac_flagged`, or requiring a contiguous run
range of flags) is left to the analyst.

### Tuning

- `--window`: widen for long, stable run periods; narrow if the baseline drifts fast.
- `--threshold`: lower it to catch subtler dropouts (more sensitive, more false flags).
- `--dead-frac`: raise toward 0.5 if "dead" should mean "clearly below normal" rather
  than "near zero".

When run on real data, expect a few wires flagged for a single isolated run (statistical
noise). The wires that matter have a high `frac_flagged` or `permanently_low = True`.

---

## Typical workflow

```bash
# scan for bad wires
python analyze_alert_adc.py all.csv --scan flagged.csv

# inspect a suspect wire
python analyze_alert_adc.py all.csv --layer 1 --wire 1 --plot l1_w1.png
```

`flagged.csv` is the per-wire, per-run list of bad runs — the basis for recording dead
channels to a database.
