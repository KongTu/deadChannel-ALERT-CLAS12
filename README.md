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
run, layer_number, layer_code, wire, value, lay_med, rel_to_layer,
own_norm, cv, local_median, robust_z, status
```

`bad_per_run.csv`:

```
run, n_bad, n_low, n_low_layer, n_hot, n_hot_layer, n_outlier, brightness, run_ok, n_wires
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
| `--dead-frac F` | 0.5 | flag `cv` below this, and `rel_to_layer` below this |
| `--hot-frac F` | 2.0 | flag `cv` above this, and `rel_to_layer` above this |
| `--threshold X` | 5.0 | robust-z cutoff for an `outlier` |
| `--window N` | 11 | rolling-median window (runs) used as the local baseline |
| `--min-scale F` | 0.05 | floor on the robust sigma, in `cv` units |
| `--min-healthy N` | 20 | runs needed to estimate `own_norm`; below this `cv` is undefined |
| `--margin F` | 1.3 | also list channels within this factor of a cut |
| `--min-gain F` | 0.1 | runs dimmer than this are marked `run_ok = False` |
| `--max-gain F` | 10 | runs brighter than this are marked `run_ok = False` |

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

Every quantity below is a ratio taken **inside a single run**, so anything that moves the
whole detector together — beam current, gas, high voltage, thresholds, trigger composition
— cancels. The overall level varies by more than an order of magnitude across the campaign
and 399 of 1111 runs read below half normal, and none of it needs correcting.

See [ALGORITHM.md](ALGORITHM.md) for worked examples.

### The two references

```
lay_med      = median value over the wires of that layer, in that run
rel_to_layer = value / lay_med                      <- against its neighbours

own_norm     = median of rel_to_layer over the runs where the wire reads like its layer
cv           = rel_to_layer / own_norm              <- against itself
```

`rel_to_layer` is taken per layer because the absolute level differs by a factor of about
3 between layer 1 and layer 7. It uses no history, so it sees a wire that was already
broken before the first run — which `cv`, normalized to the wire's own behaviour, cannot.

`cv` is needed because a single threshold on `rel_to_layer` asks every wire to fall to the
same fraction of the layer median. That suits the 90 % of wires sitting between 0.87 and
1.10 of their layer, but not the rest: a wire normally reading 1.4× its layer can lose
most of its output and still clear the cut.

`own_norm` is estimated only from the wire's healthy-looking runs. Using its whole history
would put the norm of a mostly-broken wire between its dead and healthy levels, and that
wire's *good* runs would then read about twice the norm and be flagged hot. A wire with
fewer than `--min-healthy` (default 20) such runs gets no `own_norm`; `cv` is undefined
and it is judged on `rel_to_layer` alone.

### The five cuts

An entry is flagged if any cut fires; `status` records which, most specific first.

| verdict | rule |
|---|---|
| `low/dead` | `cv < dead_frac` (0.5) |
| `low vs layer` | `rel_to_layer < dead_frac` |
| `hot` | `cv > hot_frac` (2.0) |
| `hot vs layer` | `rel_to_layer > hot_frac` |
| `outlier` | `\|robust_z\| > threshold` (5) |

`robust_z = (cv − local_median) / scale` catches a sharp change relative to the same wire
in adjacent runs, even when it stays inside both absolute bands. `local_median` is a
centered rolling median over `--window` runs; `scale` is `1.4826 × MAD` (median absolute
deviation, the robust equivalent of a standard deviation) floored at `--min-scale`,
because a wire reproduces to about 0.4 % and a 3 % wiggle should not count as anomalous.

The per-run report also lists channels within `--margin` (default 1.3) of a cut without
firing — 7 of them in run 22603.

### Run quality

`brightness` is a run's overall level relative to the campaign, from the layer medians. It
takes no part in the cuts. It only marks runs where the detector was effectively off — 109
of 1111 at the default `--min-gain 0.1` — whose values are noise rather than measurements.
Those runs are kept but marked `run_ok = False`, shaded in the summary plot, and excluded
when building run ranges.

---

## Reading the figures

**`run<N>_map.png`** — layer (vertical) × wire (horizontal), grey where the wire does not
exist. Top: the raw value on a log colour scale, matching what is posted online; the
horizontal banding is the real difference between layers. Bottom: `cv`, white at 1, with
magenta rings on channels bad against their own norm and black dashed rings on channels
bad against their layer.

**`run<N>_panels.png`** — the same run, one panel per layer. Two series, because the two
kinds of bad channel are judged on different quantities and each marker sits on the curve
it came from: blue dots are `cv` and carry the red rings, grey squares are `rel_to_layer`
and carry the black dashed rings. Shaded bands mark the dead and hot regions.

**`bad_per_run.png`** — bad channels per run across the campaign. Red points are the
total; blue and magenta count channels judged against their own norm, the black dashed
line those judged against their layer. Grey vertical bands mark runs whose overall level
is far from normal, whose counts should not be trusted. The lower panel is the run
brightness on a log axis. Flat stretches are stable periods; the steps between them are
the runs worth looking up in the logbook.

**`segments_hist.png`** — how fragmented the dataset is. Left: how many consecutive runs
a wire stays bad. Right: how many separate bad stretches each affected wire has.

---

## Storing the result

The dead channels are destined for a database. CLAS12 keeps calibration constants in
CCDB, the Calibration Constant Database, which holds a given set of constants against a
**range of runs**, with alternative sets available as named variations. That model fits
if a wire's status is constant over long stretches, and fits badly if channels die one at
a time at random runs, since each event then needs its own range.

`--segments` measures this directly. Over the reliable runs the dataset gives 1015 bad
segments across 298 wires. Just under half of the segments are a single run, but those
single-run segments carry only **2 %** of all bad (run, wire) entries: the content is
dominated by long stable stretches. Run-range tables are therefore a reasonable fit,
with the short segments either dropped by a minimum-length cut or held in a small
per-run exception list.
