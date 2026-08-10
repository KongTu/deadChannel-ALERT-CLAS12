# deadChannel-ALERT-CLAS12

Service task for CLAS12: find **dead / bad AHDC wires** in the ALERT detector from each
wire's ADC (analogue-to-digital converter) value as a function of run number.

> **New here?** [ALGORITHM.md](ALGORITHM.md) explains how a channel gets called bad in
> one page, with worked numbers. This README is the full reference.

The AHDC (ALERT Hyper Drift Chamber) has **8 layers** with wire counts
`{47, 56, 56, 72, 72, 87, 87, 99}` = **576 wires** total. For every run, the CLAS12
monitoring/timeline system produces one ADC value per wire. This project pulls those
values into a flat CSV and analyzes them.

---

## Where the numbers come from

```
coatjava reconstruction        clas12-timeline                this repo
   (AHDC::adc bank)   ─────►  per-run, per-wire ADC   ─────►  CSV  ─►  plots + bad channels
                              timelines (HIPO files)
```

The per-wire ADC values shown on the CLAS12 monitoring timeline
(e.g. `https://clas12mon.jlab.org/rgl/pass0_v10.3_alert/alert/timeline/`)
are stored as `GraphErrors` (one point per run) inside HIPO files — the columnar data
format used throughout CLAS12. `dump_alert_adc_csv.groovy` dumps them to CSV;
`analyze_alert_adc.py` (or the notebook) analyzes the CSV.

> **Note on the quantity.** The timeline value is the per-wire ADC integral
> *normalized to the trigger count*, not a raw average ADC. It is the right quantity for
> tracking a wire's relative health across runs. It is **not** the same quantity as
> `<adcMax>` in the online-monitoring logbook figures, so the two will not agree
> channel-for-channel.

---

## Repository contents

| File | What it is |
|------|------------|
| `dump_alert_adc_csv.groovy` | Reads the deployed ALERT ADC timeline HIPO files (input: clas12mon URL or a directory of timeline `.hipo` files) and writes the per-wire CSV. Runs on the JLab `ifarm`. |
| `analyze_alert_adc.py` | Command-line tool: per-run maps and tables, bad channels per run, run-range segmentation, single-wire plots, full scan. |
| `analyze_alert_adc.ipynb` | The same analysis as a notebook, with the method written out. It imports the module, so the two cannot disagree. |
| `ALGORITHM.md` | One-page guide to how a channel gets called bad, with worked numbers. |
| `all.csv` | Full dataset — 576 wires × 1112 runs (runs 21317–23061). |
| `test.csv` | Smaller subset (57 wires: layer 1, plus the first 10 wires of layer 2) for quick tests. |

Generated outputs:

| File | What it is |
|------|------------|
| `run<N>_map.png` | Layer-vs-wire map of one run, in the online-monitoring layout. |
| `run<N>_panels.png` | The same run as 8 per-layer panels. |
| `run<N>_bad.csv` | The bad channels of that run, one row each. |
| `bad_per_run.png` / `bad_per_run.csv` | Bad channels per run across the campaign. |
| `segments.csv` / `segments_hist.png` | Contiguous run ranges over which each wire is bad. |
| `flagged.csv` | Every bad (run, wire) entry in the dataset. |

### CSV formats

Input (`all.csv`, `test.csv`):

```
run, layer_number, layer_code, wire, value, graph_name
```

- `layer_number` — 1–8
- `layer_code`   — bank encoding `superlayer*10 + layer` (`11,21,22,31,32,41,42,51`)
- `wire`         — wire number within the layer
- `value`        — trigger-normalized ADC for that wire in that run

Output (`flagged.csv`, and `run<N>_bad.csv` without `local_median`):

```
run, layer_number, layer_code, wire, value, wire_med, gain, cv,
rel_to_layer, local_median, robust_z, status
```

`bad_per_run.csv`:

```
run, n_bad, n_low, n_low_layer, n_hot, n_hot_layer, n_outlier, gain, run_ok, n_wires
```

`segments.csv`:

```
layer_number, wire, run_start, run_end, n_runs, status
```

---

## Requirements

**Producing the CSV** (`dump_alert_adc_csv.groovy`) runs on the JLab `ifarm` and needs
**coatjava** installed (it provides the `run-groovy` launcher with the HIPO/GROOT
libraries). The CSVs are already committed here, so this step is only needed to refresh
the data.

**Analysis** runs anywhere with Python 3 and:

```bash
pip install pandas numpy matplotlib
# for the notebook:
pip install jupyterlab
```

---

## How to run it

### Bad channels in one run

The main output: the layer-vs-wire map that lines up with the online-monitoring logbook
entries, the same run as per-layer panels, and the table of bad channels.

```bash
python analyze_alert_adc.py all.csv --run 22603
```

writes `run22603_map.png`, `run22603_panels.png` and `run22603_bad.csv`. Use
`--run-prefix` to send them somewhere else:

```bash
python analyze_alert_adc.py all.csv --run 22603 --run-prefix figures/r22603
```

### The other outputs

```bash
# bad channels per run, across the campaign
python analyze_alert_adc.py all.csv --summary bad_per_run.png --summary-csv bad_per_run.csv

# contiguous bad-run ranges per wire; also writes segments_hist.png
python analyze_alert_adc.py all.csv --segments segments.csv

# one wire against run number
python analyze_alert_adc.py all.csv --layer 6 --wire 61 --plot L6W61.png

# every bad (run, wire) entry, plus the per-wire summary printed to screen
python analyze_alert_adc.py all.csv --scan flagged.csv
```

`segments_hist.png` is named automatically from the `--segments` filename.

### Everything in one pass

Each invocation re-reads and re-analyzes the 35 MB input, so combine the modes when you
want several outputs (about 4 s in total):

```bash
python analyze_alert_adc.py all.csv \
  --run 22603 \
  --summary bad_per_run.png --summary-csv bad_per_run.csv \
  --segments segments.csv \
  --scan flagged.csv
```

### Several runs at once

```bash
for r in 21563 21632 21697 21914 22498 22603; do
  python analyze_alert_adc.py all.csv --run $r --run-prefix "runs/r$r"
done
```

Good candidates are the run numbers where the bad-channel count steps in
`bad_per_run.png` — those are the ones most likely to have a logbook entry.

### Options

| Option | Default | Meaning |
|--------|---------|---------|
| `--run N` | – | per-run report: map, per-layer panels, bad-channel table |
| `--run-prefix STR` | `run<N>` | output prefix for `--run` |
| `--summary [PNG]` | `bad_per_run.png` | bad channels per run |
| `--summary-csv CSV` | – | also write the per-run counts |
| `--segments [CSV]` | `segments.csv` | contiguous bad-run ranges per wire (+ histogram) |
| `--layer N --wire M` | – | which wire to plot |
| `--plot FILE.png` | auto | output plot path |
| `--scan [FILE.csv]` | `alert_adc_flagged.csv` | scan all wires, write every bad entry |
| `--dead-frac F` | 0.5 | flag `cv` below this, and wires below this fraction of their layer |
| `--hot-frac F` | 2.0 | flag `cv` above this, and wires above this fraction of their layer |
| `--threshold X` | 5.0 | robust-z cutoff for an `outlier` |
| `--window N` | 11 | rolling-median window (runs) used as the local baseline |
| `--min-scale F` | 0.05 | floor on the robust sigma, in `cv` units |
| `--min-healthy N` | 20 | runs needed to estimate a wire's norm; below this `cv` is undefined |
| `--min-brightness F` | 0.5 | only runs at least this bright are used to estimate a norm |
| `--margin F` | 1.3 | also list channels within this factor of a cut |
| `--min-gain F` | 0.1 | runs dimmer than this are marked `run_ok = False` |
| `--max-gain F` | 10 | runs brighter than this are marked `run_ok = False` |
| `--global-gain` | off | normalize per run only, not per run *and* layer |
| `--no-run-norm` | off | cut on the raw value instead of the run-normalized `cv` |

With no mode option at all, the tool performs a full scan.

### Sensitivity

`--dead-frac` and `--hot-frac` move the per-run cut and the per-wire cut together, so
scanning them tells you how firm the answer is:

```bash
# a channel must fall below 40 % of normal to count as dead -> fewer channels
python analyze_alert_adc.py all.csv --run 22603 --dead-frac 0.4 --run-prefix r22603_dead040

# below 60 % is enough -> more channels
python analyze_alert_adc.py all.csv --run 22603 --dead-frac 0.6 --run-prefix r22603_dead060
```

Raising `--dead-frac` flags more channels, lowering it flags fewer.

`--threshold` and `--min-scale` affect only the `outlier` category.

### Or use the notebook

Open `analyze_alert_adc.ipynb` in `jupyter lab`, set `CSV_PATH` and `RUN_OF_INTEREST` in
the setup cell, and run top to bottom. It imports `analyze_alert_adc.py`, so the notebook
and the command line always do the same thing; the markdown sections explain the method
and the detection function is printed from the module so it cannot go stale.

---

## Re-generating the CSV (optional, on ifarm)

```bash
~/coatjava/bin/run-groovy dump_alert_adc_csv.groovy \
  https://clas12mon.jlab.org/rgl/pass0_v10.3_alert/alert/timeline/ all.csv
```

The input is either the **clas12mon timeline URL** (as above) or a **directory** of
deployed timeline `.hipo` files — not a single HIPO file. It keeps only AHDC ADC wire
graphs (`ahdc_adc_layer<L>_wire_number<WW>`) and skips the ATOF (ALERT Time-Of-Flight),
time and residual graphs. Sanity check:

```bash
cut -d, -f6 all.csv | sort -u    # should list only ahdc_adc_... graph names
```

---

## How a wire gets called bad

### Step 1 — put every run on a common scale

The overall ADC level of the detector breathes from run to run by large factors: beam
current, trigger composition, gas, high voltage, thresholds and the normalization all
move it. Across runs 21317–23061 the level spans more than an order of magnitude and
**366 of 1111 runs read below half the campaign-typical level**.

That coherent breathing is divided out before any per-wire statement is made. Judged
against its own neighbouring runs alone, a wire in a run that is globally 6 % low sits
many robust sigmas below its local baseline — and so does every other wire, so the whole
detector would be flagged for a property of the run.

| symbol | definition | meaning |
|---|---|---|
| `wire_med` | median of `value` over the wire's healthy runs at a normal detector level | the wire's own normal |
| `rel` | `value / wire_med` | the wire relative to its own normal |
| `gain` | median of `rel` over all wires in the same **run and layer** | how bright this run was |
| `cv` | `rel / gain` | **what the per-run cuts act on** |

`cv = 1` means the wire is at its own typical level once the run-wide and layer-wide
scale is removed. A dead wire goes to `cv → 0`, a hot one to `cv ≫ 1`, regardless of how
bright the run was. The gain is taken **per layer** so that a change affecting one
superlayer does not leak into the others.

**Estimating `wire_med`.** It has to be the wire's *healthy* level, so it is taken over the
runs where the wire reads like its layer **and** the detector was at a normal level
(`--min-brightness`, default 0.5). A plain median over a wire's whole history is wrong for
any wire broken for a large share of the campaign: the norm lands between its dead and
healthy levels, and its *good* runs then read about twice that norm and are flagged hot.
Allowing dim runs into the estimate fails the same way by another route, since a weak wire
most resembles its neighbours exactly when everything is compressed.

A wire that never shows `--min-healthy` (default 20) such runs gets no norm: `cv` is left
undefined and the wire is judged on `rel_to_layer` alone. Two wires are in that position
over 21317–23061, L1 W46 and L2 W55. If a wire's normal level was never observed, there is
no honest statement to make about it having changed from normal.

**Runs where the detector was effectively off.** Dividing by the gain rescues a run that
is uniformly 30 % low; it does not rescue a run with `gain ≈ 0.01`, where the values are
consistent with noise. Those runs — 106 of 1111 at the default `--min-gain 0.1` — are
kept but marked `run_ok = False`, shaded grey in the summary plot, and excluded when
building run ranges, so that a few such runs scattered through a stable period do not
chop one long segment into many short ones.

### Step 2 — three per-run cuts, on `cv`

An entry is flagged if any cut fires. `status` records which.

**`low/dead`:** `cv < dead_frac` (default 0.5). The wire delivers less than half its own
normal charge for this run's conditions.

**`hot`:** `cv > hot_frac` (default 2.0). More than twice normal — noisy, oscillating, or
picking up a neighbour. These show up as bright cells in the online monitoring maps and
are worth recording alongside the dead ones.

**`outlier`:** `|robust_z| > threshold` (default 5). A sharp change relative to the
**same wire in adjacent runs**, which catches a wire changing state even while it stays
inside the absolute bands.

### Step 3 — two more cuts, against the wire's neighbours

**`low vs layer` / `hot vs layer`:** `rel_to_layer` outside `[dead_frac, hot_frac]`, where

```
rel_to_layer = value / (median value of the wires of that layer, in that run)
```

`cv` is normalized to each wire's own median and is therefore blind to a wire that is
weak in *every* run: such a wire reads `cv ≈ 1`, perfectly normal for itself. Comparing it
with the other wires of its layer, in the same run, is what sees it. The comparison is
made per layer because the absolute level differs by a factor of about 3 between layer 1
and layer 7.

This cut needs no gain correction — in a dim run the wire and its layer fall together, so
the ratio is unchanged. Layer 1 wire 1 reads `rel_to_layer` 0.97 in run 22603 and 0.99 in
run 22897, where the detector was at 28 % of normal.

**Every cut is per run.** A wire is judged on the run in front of you, never by a
campaign-wide verdict stamped onto every run, so a wire that degrades partway through the
campaign is flagged in the runs where it is weak and left alone in the others. Across
21317–23061 only two wires are below half their layer in more than half of all runs:

| wire | median `rel_to_layer` | runs below 0.5 |
|---|---|---|
| L1 W46 | 0.30 | 59 % |
| L2 W55 | 0.33 | 60 % |

### Near-threshold channels

A threshold is a line through a continuum, so the per-run report also lists channels that
came within `--margin` (default 1.3, i.e. 30 %) of a cut without firing. In run 22603
that is 6 channels, among them L4 W67 at `rel_to_layer` 0.52.

### Glossary

**`local_median`** — centered rolling median of `cv` over `--window` runs: the level
expected for this run given its neighbours. A median, so a few bad runs inside the window
do not drag the baseline.

**`detrended`** — `cv − local_median`: how far this run sits from local normal.

**`MAD`** — median absolute deviation of the residuals,
`median(|detrended − median(detrended)|)`. The ordinary standard deviation *squares*
deviations, so one dead run inflates it — and the inflated spread then hides the very
anomaly that caused it. A median ignores extremes by construction.

**`1.4826`** — unit conversion, nothing more. For Gaussian data `MAD → 0.6745 σ`
(0.6745 is the z-value of the 75th percentile), so multiplying by `1/0.6745 = 1.4826`
makes the estimate equal the standard deviation on clean data.

**`scale`** — `max(1.4826 × MAD, min_scale)`: the robust sigma, with a floor. After
normalization a typical wire reproduces to about 0.4 %, so without the floor a harmless
3 % wiggle is a 7σ excursion and the `outlier` cut fires across the whole detector.
`--min-scale 0.05` says "nothing counts as anomalous unless it moves by more than about
5 % of the wire's normal level".

**`robust_z`** — `detrended / scale`: robust sigmas from the local baseline. Read like an
ordinary z-score, but built from medians so it stays honest when part of the series is bad.

**`frac_flagged`** (from `--scan`) — flagged runs / total runs, per wire. Used for
ranking suspects; no automatic cut is applied to it.

The tool ranks and reports; the final per-wire verdict is left to the analyst.

---

## Reading the figures

**`run<N>_map.png`** — two panels, both layer (vertical) × wire (horizontal), grey where
the wire does not exist. The top panel is the raw trigger-normalized integral on a log
colour scale, which is the like-for-like comparison with what is posted online; its
horizontal banding is the real level difference between layers. The bottom panel is `cv`,
white at 1, with magenta rings on channels bad against their own norm and black dashed
rings on channels bad against their layer.

**`run<N>_panels.png`** — the same run as 8 per-layer panels, with two series, because
the two kinds of bad channel are judged on two different quantities and each marker sits
on the curve it came from. Blue dots are `cv` (this run against the wire's own norm) and
carry the red `bad in this run` rings; grey squares are `rel_to_layer` (the wire's
against the median wire of its layer in that run) and carries the black dashed
`bad vs its layer` rings. Shaded bands mark the dead and hot regions.

**`bad_per_run.png`** — the campaign summary. The top panel counts bad channels per run:
red points for the total, blue and magenta for channels judged against their own norm,
and a black dashed line for channels judged against their layer. Grey vertical bands mark runs
whose overall level is far from normal, whose counts should not be trusted. The bottom
panel is the run gain on a log axis. Flat stretches are stable detector periods; the
steps between them are the runs worth looking up in the logbook.

**`segments_hist.png`** — how fragmented the dataset is. Left: how many consecutive runs
a wire stays bad. Right: how many separate bad stretches each affected wire has. This is
the input to the storage question below.

---

## Storing the result

The dead channels are destined for a database. CLAS12 keeps calibration constants in
CCDB, the Calibration Constant Database, which holds a given set of constants against a
**range of runs**, with alternative sets available as named variations. That model fits
if a wire's status is constant over long stretches, and fits badly if channels die one at
a time at random runs, since each event then needs its own range.

`--segments` measures this directly. Over the reliable runs the dataset gives 1051 bad
segments across 292 wires. Just under half of the segments are a single run, but those
single-run segments carry only **2 %** of all bad (run, wire) entries: the content is
dominated by long stable stretches. Run-range tables are therefore a reasonable fit,
with the short segments either dropped by a minimum-length cut or held in a small
per-run exception list.
