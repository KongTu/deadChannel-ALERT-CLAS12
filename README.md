# deadChannel-ALERT-CLAS12

Service task for CLAS12: find **dead / bad AHDC wires** in the ALERT detector from each
wire's ADC (analogue-to-digital converter) value as a function of run number.

> **How the method works** is in [ALGORITHM.md](ALGORITHM.md), one page with worked
> numbers. This README covers installing and running the code.

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
`analyze_alert_adc.py` analyzes the CSV.

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
| `make_all_figures.py` | Writes every per-wire and per-run figure into `figures/`. Runs the analysis once and reuses it, and skips files that already exist, so it can be interrupted and rerun. |
| `plot_outlier_example.py` | Draws `outlier_example.png`, the two-wire illustration of the 25 % cut. |
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

### Every figure at once

```bash
python make_all_figures.py                 # 576 per-wire + 1111 per-run figures
python make_all_figures.py --only wire     # just one of the two sets
python make_all_figures.py --only run
```

Writes `figures/per_wire/L<layer>_W<wire>.png` and `figures/per_run/run<N>.png` — about
190 MB in total, and roughly ten minutes. The analysis runs once and is reused, so this is
far quicker than 1687 separate invocations; existing files are skipped, so an interrupted
run resumes where it stopped. `figures/` is gitignored.

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

`--dead-frac` and `--hot-frac` move both references together, so scanning them tells you
how firm the answer is:

```bash
# a channel must fall below 40 % of normal to count as dead -> fewer channels
python analyze_alert_adc.py all.csv --run 22603 --dead-frac 0.4 --run-prefix r22603_dead040

# below 60 % is enough -> more channels
python analyze_alert_adc.py all.csv --run 22603 --dead-frac 0.6 --run-prefix r22603_dead060
```

Raising `--dead-frac` flags more channels, lowering it flags fewer.

`--threshold` and `--min-scale` affect only the `outlier` category.

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

## Reading the figures

`cv` and `rel_to_layer` are defined in [ALGORITHM.md](ALGORITHM.md).

**`run<N>_map.png`** — layer (vertical) × wire (horizontal), grey where the wire does not
exist. Top: the raw value on a log colour scale, matching what is posted online; the
horizontal banding is the real difference between layers. Bottom: `cv`, white at 1, with
magenta rings on channels bad against their own norm and black dashed rings on channels
bad against their layer.

**`run<N>_panels.png`** — the same run, one panel per layer. Blue dots are `cv` and carry
the red rings; grey squares are `rel_to_layer` and carry the black dashed rings, so each
marker sits on the curve its verdict came from. Shaded bands mark the dead and hot regions.

**`bad_per_run.png`** — bad channels per run. Red points are the total; blue and magenta
count channels judged against their own norm, the black dashed line those judged against
their layer. Grey vertical bands mark runs whose overall level is far from normal, whose
counts should not be trusted. The lower panel is the run brightness on a log axis. Flat
stretches are stable periods; the steps between them are the runs worth looking up in the
logbook.

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
