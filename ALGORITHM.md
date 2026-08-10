# How a channel gets called bad — quick guide

One page. The full reference is in [README.md](README.md).

**The problem.** We have one number per wire per run: the ADC integral, normalized to the
trigger count. A wire is bad if that number is wrong. The difficulty is that "wrong"
cannot be a fixed threshold — the number depends on which layer the wire is in, on how
bright the run was, and on what that particular wire delivers when it is working.

So the wire is measured against two references, both evaluated run by run.

---

## The wire used throughout: layer 4, wire 39

This one wire shows every part of the method, because it is broken for part of the
campaign and healthy for the rest.

| run | `value` | median wire of layer 4 | `rel_to_layer` | `cv` | verdict |
|---|---|---|---|---|---|
| 21551 | 0.021 | 1.103 | 0.02 | 0.02 | `low/dead` |
| 21643 | 0.091 | 1.518 | 0.06 | 0.06 | `low/dead` |
| 22083 | 0.230 | 1.319 | 0.17 | 0.17 | `low/dead` |
| 22247 | 1.437 | 1.408 | 1.02 | 1.01 | — |
| 22638 | 1.398 | 1.338 | 1.04 | 1.02 | — |

Dead early, then it recovers and reads like its neighbours. It is flagged in the runs
where it is dead — 23 % of them — and left alone in the rest.

---

## Step 1 — what is normal *for this wire*?

Every wire has its own working level, so each is compared against its own norm:

```
rel  = value / wire_med
gain = median of rel over all wires in the same run and layer
cv   = rel / gain            <- what the step-2 cuts act on
```

`cv = 1` means *this wire is at its own normal level, for this run's conditions*. Dividing
by `gain` removes the run-wide breathing: the detector's overall level varies by more than
an order of magnitude across the campaign, and 383 of 1111 runs sit below half normal.

**Getting `wire_med` right is the subtle part.** It must be the wire's *healthy* level. The
obvious choice — the median over all its runs — is wrong for exactly the wire above: with
L4 W39 dead for a large share of the campaign, its all-run median lands at 0.649, between
its dead and healthy levels. Its healthy runs then read 1.44/0.649 ≈ 2.2 and get flagged
**hot**, which is backwards — those are the runs where it works.

So the norm is estimated only from runs where the wire reads like its layer *and* the
detector was running at a normal level. For L4 W39 that gives **1.384**, from 548 runs,
and its healthy runs now read `cv ≈ 1.01`.

Both conditions matter. Allowing dim runs into the estimate fails the same way by another
route: a weak wire most resembles its neighbours exactly when the whole detector is
compressed, so its norm would be anchored on the dimmest runs and every normal run would
look hot.

If a wire never shows 20 such runs, it gets no norm at all — `cv` is left undefined and it
is judged on step 3 alone. Two wires are in that position, L1 W46 and L2 W55. If a wire's
normal level was never observed, there is no honest statement to make about it having
changed from normal.

**Sanity check.** Layer 1 wire 1 is healthy throughout. In run 22603 it reads `value` 2.095
against a norm of 2.225 → `cv` 0.981. In run 22897, where the detector was at 26 % of
normal, it reads 0.623 — a third as much — but `gain` falls with it, so `cv` is 1.024. Fine
in both.

---

## Step 2 — three cuts on `cv`

| verdict | rule | meaning |
|---|---|---|
| `low/dead` | `cv < 0.5` | under half its own normal |
| `hot` | `cv > 2.0` | over twice its own normal |
| `outlier` | `\|robust_z\| > 5` | sharp change vs the same wire in nearby runs |

**`low/dead` — layer 1 wire 19, run 22603:** `value` 0.570 against a norm of 2.380, with
`gain` 0.960 → **`cv` 0.249**. A quarter of its own normal.

**`hot` — layer 4 wire 65, run 21604:** `value` 4.760 against a norm of 1.385 →
**`cv` 8.06**, and 8.3× its layer. Unambiguous on both references.

**`outlier` — layer 1 wire 26, run 23055.** This wire is flagged in only 3 % of runs:

```
run    23053  23054  23055  23056  23057
cv      1.020  1.011  0.601  1.049  1.047
```

At 0.601 it stays inside the 0.5–2.0 band, so neither absolute cut fires. But its
neighbours say 1.05 and this wire is reproducible to a fraction of a percent, so
`robust_z = −8.9`. The local cut catches the single-run dropout.

`robust_z` is `(cv − local median) / scale`, the local median being a rolling median over
11 runs and `scale` a robust standard deviation floored at 0.05. The floor matters: a
normalized wire reproduces to about 0.4 %, so without it a harmless 3 % wiggle would be a
7σ excursion.

---

## Step 3 — compare the wire with its neighbours, in the same run

Step 2 needs to know what the wire delivers when healthy. Step 3 does not:

```
rel_to_layer = value / (median value of the wires of that layer, in that run)
```

| verdict | rule |
|---|---|
| `low vs layer` | `rel_to_layer < 0.5` |
| `hot vs layer` | `rel_to_layer > 2.0` |

**Worked example — layer 1 wire 46, run 22603:** `value` 0.496 while the median layer-1
wire reads 2.160, so `rel_to_layer = 0.23`. This is one of the two wires with no estimable
norm, so `cv` is undefined and this is the only cut available — and it is enough.
**`low vs layer`.**

The comparison is made *within a layer* because the layers genuinely differ — the median
wire of layer 1 delivers about three times that of layer 7:

| layer | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| median wire, run 22603 | 2.16 | 1.62 | 1.53 | 1.32 | 1.28 | 1.20 | 0.65 | 0.70 |

This cut needs no gain correction: in a dim run the wire and its layer fall together, so
the ratio is unchanged. Layer 1 wire 1 reads 0.97 in run 22603 and 0.99 in run 22897.

---

## Putting it together

Five channels of run 22603:

| channel | `cv` | `rel_to_layer` | verdict | why |
|---|---|---|---|---|
| L1 W1 | 0.98 | 0.97 | — | normal on both references |
| L4 W39 | 1.03 | 1.05 | — | recovered by this run; flagged only in its dead period |
| L1 W19 | **0.25** | **0.26** | `low/dead` | healthy historically, dead in this run |
| L1 W46 | undefined | **0.23** | `low vs layer` | no norm can be estimated; the layer settles it |
| L4 W67 | 0.92 | 0.52 | — | just above the cut; listed as near-threshold |

Run 22603 gives **14 bad channels of 576**.

```bash
python analyze_alert_adc.py all.csv --run 22603
```

The `status` column carries one of five verdicts: `low/dead`, `low vs layer`, `hot`,
`hot vs layer`, `outlier`. The thresholds that matter most are `--dead-frac` (0.5) and
`--hot-frac` (2.0); they move the step-2 and step-3 cuts together.

A threshold is a line drawn through a continuum, so the report also lists channels that
came within 30 % of a cut without firing — 6 of them in run 22603, including L4 W67 at
`rel_to_layer` 0.52. Adjust with `--margin`.

---

## The three traps this avoids

**A dip that affects everything.** Run 22603 sits about 6 % below its own local baseline —
and **all 576 wires read low**, not some of them. A normalized wire reproduces to about
0.4 %, so a coherent 6 % shift is many sigmas for every wire at once, and judged only
against nearby runs the whole chamber looks dead. Dividing by `gain` removes it.

**A wire that was never alive.** Any method that asks "has this wire changed?" is blind to
a wire that has always been broken — it never changed. Step 3 asks "is this wire like its
neighbours?" instead, and needs no history at all.

**A wire whose history is mostly broken.** If a wire's own norm is taken from all its runs,
a wire that is dead for much of the campaign gets a norm halfway between dead and healthy,
and its *good* runs are flagged as hot. Anchoring the norm on healthy runs at normal
detector level is what prevents it — worth 2700 spurious flags across this dataset.
