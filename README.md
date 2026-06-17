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
| `dump_alert_adc_csv.groovy` | Reads the deployed ALERT ADC timeline HIPO files and writes the per-wire CSV. Run on the JLab `ifarm`. |
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

You can also point it at a directory of timeline `.hipo` files or a single file. It keeps
only AHDC ADC wire graphs (`ahdc_adc_layer<L>_wire_number<WW>`) and skips ATOF / time /
residual graphs. Sanity check:

```bash
cut -d, -f6 all.csv | sort -u    # should list only ahdc_adc_... graph names
```

---

## How a wire gets flagged

Each wire is judged **against itself in nearby runs**, because ADC levels drift slowly
over a run period. For one wire, sorted by run:

1. `local_median` — centered rolling median over `--window` runs = the expected level
   given the neighboring runs. (Median, so a few dead runs in the window don't skew it.)
2. `detrended = value − local_median` — the residual after removing the slow drift.
3. `scale = 1.4826 × MAD(detrended)` — a robust estimate of the normal scatter
   (MAD = median absolute deviation; `1.4826` rescales it to be comparable to a standard
   deviation).
4. `robust_z = detrended / scale` — how many robust sigmas a run sits from its local
   baseline. **Flag as `outlier`** if `|robust_z| > threshold`.
5. `dead_floor = dead_frac × (wire median)` — **flag as `low/dead`** if the value drops
   below this.

A run is flagged if **either** rule fires; `reason` records which.

**Why two rules.** `robust_z` catches sharp spikes and short dropouts. But if a wire is
dead for many runs in a row, the local median inside that stretch also goes to zero, so
`robust_z` stops seeing it as unusual — the `dead_floor` rule (comparison to the wire's
*overall* median) catches that sustained death.

**`permanently_low`** (in the scan summary): a wire whose median value is far below the
detector-wide typical level across all wires — essentially dead in *every* run, which the
per-run rules can't catch on their own.

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
