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

**Why both are needed.** A alone applies the same threshold to every wire, so the drop
required to trigger it depends on where the wire started: at `dead_frac = 0.5`, a wire
normally reading 1.4× its layer must lose 64 % of its output, while one reading 0.7× need
only lose 29 %. That is well calibrated for the 90 % of wires sitting between 0.87 and
1.10 of their layer and poorly calibrated for the rest. B asks the same question of every
wire — has it halved relative to its own normal — but is blind to a wire that has always
been weak, since such a wire reads `cv ≈ 1`.

**Estimating `own_norm`.** Only the wire's healthy-looking runs are used. Taking the median
over its whole history puts the norm of a mostly-broken wire between its dead and healthy
levels, so its *good* runs read about twice that norm and are flagged hot. A wire with
fewer than `--min-healthy` such runs gets no `own_norm`: `cv` is undefined and it is judged
on A alone.

---

## Five cuts

An entry is flagged if any cut fires. `status` records which, most specific first.

| verdict | rule |
|---|---|
| `low/dead` | `cv < dead_frac` (0.5) |
| `low vs layer` | `rel_to_layer < dead_frac` |
| `hot` | `cv > hot_frac` (2.0) |
| `hot vs layer` | `rel_to_layer > hot_frac` |
| `outlier` | `\|robust_z\| > threshold` (5) |

The first four are absolute. The fifth catches a change that stays inside both bands:

```
robust_z = (cv − local_median) / scale
```

`local_median` is a centered rolling median of `cv` over `--window` runs — the level
expected for this run given its neighbours, a median so a few bad runs in the window do
not drag it. `scale` is `max(1.4826 × MAD, --min-scale)`, where `MAD` is the median
absolute deviation of the residuals. A standard deviation would be inflated by a single
dead run, and the inflated spread would then hide the anomaly that caused it; the factor
1.4826 converts MAD to the equivalent of a standard deviation on clean data. The floor
exists because a wire reproduces to about 0.4 %, so without it a 3 % wiggle would be a 7σ
excursion.

Channels within `--margin` of a cut without firing are reported separately.

---

## Run quality

`brightness` is a run's overall level relative to the campaign, taken from the layer
medians. It takes no part in the cuts. It marks runs where the detector was effectively
off, whose values are noise rather than measurements. Those runs are kept, marked
`run_ok = False`, shaded in the summary plot and excluded when building run ranges.

---

## Examples

All from `all.csv`, runs 21317–23061. Reports for the five runs are under `examples/`.

**Five runs.**

| run | brightness | bad | near cut | |
|---|---|---|---|---|
| 21697 | 0.63 | 95 | 35 | a step in the campaign |
| 22249 | 1.09 | 4 | 3 | quiet plateau |
| 22603 | 0.99 | 13 | 7 | typical run |
| 22897 | **0.26** | **3** | 0 | detector at a quarter power |
| 23055 | 0.14 | 56 | 18 | many wires dip together |

Run 22897 shows the ratios doing their job: every wire read low in absolute terms, and 3
of 576 were flagged. L1 W1 delivered 0.623 there against 2.095 in run 22603, yet reads
`rel_to_layer` 0.99 and `cv` 1.00 in both.

Run 23055 is the opposite — 53 wires change sharply while 520 read normally, so it is a
real detector event. Its brightness of 0.14 makes the statistics thin; `--min-gain 0.3`
would exclude such runs.

**One run, channel by channel** (run 22603, 13 bad of 576):

| channel | `rel_to_layer` | `own_norm` | `cv` | verdict |
|---|---|---|---|---|
| L1 W1 | 0.97 | 0.99 | 0.98 | — |
| L1 W19 | **0.26** | 1.03 | **0.26** | `low/dead` |
| L1 W46 | **0.23** | 0.96 | **0.24** | `low/dead` |
| L6 W61 | 0.57 | **1.40** | **0.41** | `low/dead` — a strong wire, so only B sees it |
| L4 W67 | 0.52 | 0.78 | 0.66 | — near-threshold |

**A single-run dropout** (L1 W26, flagged in 3 % of runs):

```
run    23053  23054  23055  23056  23057
cv      1.010  1.003  0.597  1.026  1.025
```

No absolute cut fires at 0.597, but the wire reproduces to a fraction of a percent, so
`robust_z = −8.5` and the `outlier` cut catches it.
