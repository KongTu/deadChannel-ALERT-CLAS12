# How a channel gets called bad — quick guide

One page. The full reference is in [README.md](README.md).

**The problem.** We have one number per wire per run: the ADC integral, normalized to the
trigger count. A wire is bad if that number is wrong. The difficulty is that "wrong"
cannot be a fixed threshold — it depends on which layer the wire is in, on how bright the
run was, and on what that particular wire delivers when it is working.

Everything below is a **ratio taken inside a single run**, so anything that moves the whole
detector together — beam current, gas, thresholds, trigger composition — cancels exactly.
No run-level correction is applied, because none is needed.

---

## The two references

**A — the wire against its neighbours.**

```
lay_med      = median value over the wires of that layer, in that run
rel_to_layer = value / lay_med
```

Per layer, because the layers genuinely differ: the median layer-1 wire delivers about
three times the median layer-7 wire. This reference needs no history, so it sees a wire
that was already broken before the first run.

**B — the wire against itself.**

```
own_norm = median of rel_to_layer over the runs where the wire reads like its layer
           (its usual standing within the layer)
cv       = rel_to_layer / own_norm
```

`cv = 1` means *this wire is where it usually sits*.

**Why B is needed.** Reference A asks every wire to fall to the same fraction of the layer
median. That is fine for a typical wire, since 90 % of wires sit between 0.87 and 1.10 of
their layer — but not for the rest. **L6 W61** normally reads 1.40× its layer. In run 22603
it falls to 0.683, which is `cv` 0.41 — it has lost nearly 60 % of its output — yet
`rel_to_layer` is still 0.57, above the 0.5 cut. Reference A alone would miss it, and
Raphael circled it.

**Why A is needed.** `cv` is normalized to the wire's own standing, so a wire that is
always weak reads `cv ≈ 1`. Reference A is what sees it.

---

## The five cuts

| verdict | rule |
|---|---|
| `low/dead` | `cv < 0.5` |
| `low vs layer` | `rel_to_layer < 0.5` |
| `hot` | `cv > 2.0` |
| `hot vs layer` | `rel_to_layer > 2.0` |
| `outlier` | `\|robust_z\| > 5` |

`robust_z` is `(cv − local median) / scale`, the local median being a rolling median over
11 runs and `scale` a robust standard deviation floored at 0.05. It catches a sharp change
that stays inside both absolute bands. **L1 W26** is flagged in 3 % of runs:

```
run    23053  23054  23055  23056  23057
cv      1.010  1.003  0.597  1.026  1.025
```

At 0.597 no absolute cut fires, but the wire reproduces to a fraction of a percent, so
`robust_z = −8.5`.

---

## One wire, start to finish: layer 4, wire 39

This wire is broken for part of the campaign and healthy for the rest, so it exercises
every part of the method.

| run | `value` | `lay_med` | `rel_to_layer` | `cv` | verdict |
|---|---|---|---|---|---|
| 21551 | 0.021 | 1.103 | 0.02 | 0.02 | `low/dead` |
| 22247 | 1.437 | 1.408 | 1.02 | 0.99 | — |
| 22638 | 1.398 | 1.338 | 1.04 | 1.01 | — |

Its `own_norm` is 1.03, estimated from the 854 runs in which it reads like its layer. It
is flagged in the 23 % of runs where it is dead and left alone in the rest.

**Estimating `own_norm` on healthy runs only is the point.** Take the median over the
wire's *whole* history instead and the norm lands between its dead and healthy levels —
its **good** runs then read about twice the norm and get flagged **hot**, which is
backwards. On this dataset that mistake produced 2709 spurious flags across 11 wires.

---

## Five runs

| run | brightness | bad | near cut | breakdown | |
|---|---|---|---|---|---|
| 21697 | 0.63 | 95 | 35 | 74 low, 11 outlier, 10 hot | a step in the campaign |
| 22249 | 1.09 | 4 | 3 | 4 low | quiet plateau |
| 22603 | 0.99 | 13 | 7 | 13 low | Raphael's test run |
| 22897 | 0.26 | **3** | 0 | 3 low | detector at 26 % of normal |
| 23055 | 0.14 | 56 | 18 | 53 outlier, 3 low | many wires dip together |

Run 22897 is the check that matters: the detector delivered a quarter of its usual charge,
every wire read low in absolute terms, and **3 of 576** were flagged. Layer 1 wire 1 reads
0.623 there against 2.095 in run 22603 — and `rel_to_layer` is 0.99, `cv` 1.00 in both.

Run 23055 is the opposite case: 53 wires change together sharply, while the other 520 read
normally, so it is a real detector event rather than a run-level artefact. Its brightness
of 0.14 is low enough that the statistics behind it are thin — `--min-gain 0.3` would
exclude such runs.

---

## Run 22603 in detail

| channel | `rel_to_layer` | `own_norm` | `cv` | verdict |
|---|---|---|---|---|
| L1 W1 | 0.97 | 0.99 | 0.98 | — |
| L4 W39 | 1.05 | 1.03 | 1.01 | — recovered by this run |
| L1 W19 | **0.26** | 1.03 | **0.26** | `low/dead` |
| L1 W46 | **0.23** | 0.96 | **0.24** | `low/dead` |
| L6 W61 | 0.57 | **1.40** | **0.41** | `low/dead` — only reference B sees it |
| L4 W67 | 0.52 | 0.78 | 0.66 | — just above both cuts, listed as near-threshold |

**13 bad channels of 576.** Seven of Raphael's eight circled channels are flagged; the
eighth, L4 W67, appears in the near-threshold list.

```bash
python analyze_alert_adc.py all.csv --run 22603
```

The thresholds that matter are `--dead-frac` (0.5) and `--hot-frac` (2.0); they move both
references together. Channels within 30 % of a cut are listed separately — adjust with
`--margin`.

---

## The traps this avoids

**A dip that affects everything.** Run 22603 sits about 6 % below its own local baseline,
and all 576 wires read low. Comparing each wire only against its own recent runs makes
that a many-sigma excursion for every wire at once, and the whole chamber looks dead.
Both references are ratios within the run, so it cancels.

**A wire that was never alive.** Any method asking "has this wire changed?" is blind to a
wire that has always been broken — it never changed. Reference A needs no history.

**A wire stronger or weaker than its neighbours.** A single threshold against the layer
median asks a 1.4× wire to lose 64 % of its output before firing, and a 0.7× wire only
29 %. Reference B asks the same question of every wire.

**A wire whose history is mostly broken.** Anchoring its norm on its healthy runs is what
stops its good runs being flagged hot.
