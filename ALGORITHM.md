# How a channel gets called bad

How to install and run the code is in [README.md](README.md).

We have one number per wire per run: the ADC integral, normalized to the trigger count.
A wire is bad if that number is wrong — but "wrong" depends on the layer, on how bright
the run was, and on what that wire delivers when working.

Every quantity below is a ratio taken **inside a single run**, so anything moving the whole
detector together — beam current, gas, thresholds — cancels. No run-level correction is
applied because none is needed.

---

## Two references

**A. Against its neighbours**

```
lay_med      = median value over the wires of that layer, in that run
rel_to_layer = value / lay_med
```

Per layer, because the median layer-1 wire delivers about three times the median layer-7
wire. Uses no history, so it sees a wire that was already broken before the first run.

**B. Against itself**

```
own_norm = median of rel_to_layer over the runs where the wire reads like its layer
cv       = rel_to_layer / own_norm
```

`own_norm` is the wire's usual standing in its layer. `cv = 1` means it is where it
usually sits.

**Why both.** A alone would set the same threshold for every wire, which is fine for the
90 % that sit between 0.87 and 1.10 of their layer, and wrong for the rest — L6 W61
normally reads 1.40× its layer, so in run 22603 it can fall to `cv` 0.41, having lost
nearly 60 % of its output, while `rel_to_layer` is still 0.57 and clears the cut. B alone
would be blind to a wire that is always weak, since that wire reads `cv ≈ 1`.

`own_norm` is estimated only from the wire's healthy-looking runs. Using its whole history
instead puts the norm of a mostly-broken wire between its dead and healthy levels, and its
*good* runs then read about twice the norm and get flagged hot.

---

## Five cuts

| verdict | rule |
|---|---|
| `low/dead` | `cv < 0.5` |
| `low vs layer` | `rel_to_layer < 0.5` |
| `hot` | `cv > 2.0` |
| `hot vs layer` | `rel_to_layer > 2.0` |
| `outlier` | `\|robust_z\| > 5` |

`robust_z` is `(cv − local median) / scale` — a rolling median over 11 runs, and a robust
standard deviation floored at 0.05. It catches a change that stays inside both bands.
L1 W26 dips for exactly one run:

```
run    23053  23054  23055  23056  23057
cv      1.010  1.003  0.597  1.026  1.025
```

No absolute cut fires at 0.597, but the wire reproduces to a fraction of a percent, so
`robust_z = −8.5`.

**Terms in that cut.** `local_median` is a centered rolling median of `cv` over `--window`
runs — the level expected for this run given its neighbours, taken as a median so a few
bad runs in the window do not drag it. `MAD` is the median absolute deviation of the
residuals; a standard deviation would be inflated by a single dead run, and the inflated
spread would then hide the very anomaly that caused it. `scale` is
`max(1.4826 × MAD, --min-scale)` — the factor 1.4826 converts MAD to the equivalent of a
standard deviation on clean data, and the floor exists because a wire reproduces to about
0.4 %, so without it a 3 % wiggle would be a 7σ excursion.

---

## Run quality

`brightness` is a run's overall level relative to the campaign, taken from the layer
medians. It takes no part in the cuts. It marks runs where the detector was effectively
off — 109 of 1111 at the default `--min-gain 0.1` — whose values are noise rather than
measurements. Those runs are kept, marked `run_ok = False`, shaded in the summary plot and
excluded when building run ranges.

---

## One wire, start to finish: L4 W39

Broken early in the campaign, healthy afterwards.

| run | `value` | `lay_med` | `rel_to_layer` | `cv` | verdict |
|---|---|---|---|---|---|
| 21551 | 0.021 | 1.103 | 0.02 | 0.02 | `low/dead` |
| 22247 | 1.437 | 1.408 | 1.02 | 0.99 | — |
| 22638 | 1.398 | 1.338 | 1.04 | 1.01 | — |

Its `own_norm` is 1.03, from the 854 runs where it reads like its layer. It is flagged in
the 23 % of runs where it is dead, and left alone in the rest.

---

## Five runs

| run | brightness | bad | near cut | |
|---|---|---|---|---|
| 21697 | 0.63 | 95 | 35 | a step in the campaign |
| 22249 | 1.09 | 4 | 3 | quiet plateau |
| 22603 | 0.99 | 13 | 7 | typical run |
| 22897 | **0.26** | **3** | 0 | detector at a quarter power |
| 23055 | 0.14 | 56 | 18 | many wires dip together |

Run 22897 is the useful check: every wire read low in absolute terms, and 3 of 576 were
flagged. L1 W1 delivered 0.623 there against 2.095 in run 22603, yet reads `rel_to_layer`
0.99 and `cv` 1.00 in both.

Run 23055 is the opposite — 53 wires change sharply while 520 read normally, so it is a
real detector event. Its brightness of 0.14 makes the statistics thin; `--min-gain 0.3`
would exclude such runs.

Reports for all five are under `examples/`.

---

## Run 22603 in detail

| channel | `rel_to_layer` | `own_norm` | `cv` | verdict |
|---|---|---|---|---|
| L1 W1 | 0.97 | 0.99 | 0.98 | — |
| L4 W39 | 1.05 | 1.03 | 1.01 | — recovered by this run |
| L1 W19 | **0.26** | 1.03 | **0.26** | `low/dead` |
| L1 W46 | **0.23** | 0.96 | **0.24** | `low/dead` |
| L6 W61 | 0.57 | **1.40** | **0.41** | `low/dead` — only B sees it |
| L4 W67 | 0.52 | 0.78 | 0.66 | — near-threshold |

13 bad channels of 576.

```bash
python analyze_alert_adc.py all.csv --run 22603
```

`--dead-frac` (0.5) and `--hot-frac` (2.0) move both references together. Channels within
30 % of a cut are listed separately; adjust with `--margin`.
