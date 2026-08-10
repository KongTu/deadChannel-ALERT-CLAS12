# How a channel gets called bad — quick guide

One page. The full reference is in [README.md](README.md).

**The problem.** We have one number per wire per run: the ADC integral, normalized to the
trigger count. A wire is bad if that number is wrong. The difficulty is that "wrong"
cannot be a fixed threshold — the number depends on which layer the wire is in, on how
bright the run was, and on the wire itself.

So the wire is compared against three different references, in order.

---

## Step 1 — divide out how bright the run was

Every wire in a run moves together with the beam current, trigger composition, gas and
thresholds. That common motion has to go before any single wire can be judged.

```
rel  = value / wire_med          wire_med = this wire's median over all runs
gain = median of rel over all wires in the same run and layer
cv   = rel / gain                <- everything in step 2 is a cut on cv
```

`cv = 1` means *this wire is at its own normal level, for this run's conditions*.

**Worked example — the same healthy wire, layer 1 wire 1, in two very different runs:**

| | run 22603 | run 22897 |
|---|---|---|
| `value` | 2.095 | 0.623 |
| `wire_med` | 2.164 | 2.164 |
| `rel` | 0.968 | 0.288 |
| `gain` (the whole detector) | 0.990 | 0.286 |
| **`cv`** | **0.978** | **1.007** |

In run 22897 the wire delivers a third of its usual charge — but so does every other
wire, because the detector as a whole was running at 28 % of normal. After dividing by
the gain the wire reads 1.007. It is fine, and it is not flagged.

Runs where the detector was effectively off (`gain ≈ 0.01`) cannot be rescued this way.
They are kept but marked `run_ok = False` and treated as unreliable.

---

## Step 2 — three cuts on `cv`, per run

| verdict | rule | meaning |
|---|---|---|
| `low/dead` | `cv < 0.5` | under half its own normal |
| `hot` | `cv > 2.0` | over twice its own normal |
| `outlier` | `\|robust_z\| > 5` | sharp change vs the same wire in nearby runs |

**`low/dead` — layer 1 wire 19, run 22603:**
`value` 0.570, `wire_med` 2.222 → `rel` 0.256, `gain` 0.990 → **`cv` 0.259**. A quarter of
its own normal. Flagged.

**`hot` — layer 4 wire 39, run 22603:** **`cv` 2.081**. Flagged.

**`outlier` — layer 4 wire 39, run 21677.** This wire normally sits at `cv ≈ 2.4`. Then:

```
run    21675  21676  21677  21678  21679
cv      2.45   1.25   0.66   2.20   2.25
```

At run 21677, `cv = 0.665` sits comfortably inside the 0.5–2.0 band, so neither absolute
cut fires. But its neighbours say 2.43, and the wire's run-to-run scatter is tiny, so
`robust_z = −35`. The local cut catches it.

`robust_z` is `(cv − local median) / scale`, where the local median is a rolling median
over 11 runs and `scale` is a robust standard deviation with a floor of 0.05. The floor
matters: a normalized wire reproduces to about 0.4 %, so without it a harmless 3 % wiggle
would be a 7σ excursion.

---

## Step 3 — one cut on the absolute level, per wire

Step 2 cannot see a wire that has been dead since before the first run. `cv` is
normalized to that wire's *own* median, so a permanently dead wire reads `cv ≈ 1` —
perfectly normal, for itself.

The fix is to compare the wire with its neighbours in the same layer instead:

```
rel_to_layer = wire_med / (median wire_med of the same layer)
```

| verdict | rule |
|---|---|
| `always low` | `rel_to_layer < 0.5` |
| `always hot` | `rel_to_layer > 2.0` |

**Worked example — layer 1 wire 46, run 22603:**
`value` 0.496, `wire_med` 0.533 → `cv` 0.940. Step 2 sees nothing wrong.
But a typical layer-1 wire has a median of 2.19, so `rel_to_layer = 0.24`. This wire has
been delivering a quarter of its neighbours' charge all campaign. **`always low`.**

The comparison is made *within a layer* because the layers genuinely differ:

| layer | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| typical wire median | 2.19 | 1.58 | 1.50 | 1.25 | 1.21 | 1.10 | 0.67 | 0.73 |

Seven wires qualify: L1 W46, L2 W54, L2 W55, L3 W56, L4 W67, L5 W5, L6 W61. They are
reported as bad in **every** run — because they are.

---

## Putting it together

Four channels of run 22603, side by side:

| channel | `cv` | `rel_to_layer` | verdict | why |
|---|---|---|---|---|
| L1 W1 | 0.98 | 0.99 | — | normal on both references |
| L1 W19 | **0.26** | 1.01 | `low/dead` | fine historically, dead in this run |
| L4 W39 | **2.08** | 0.52 | `hot` | over twice its own normal here |
| L1 W46 | 0.94 | **0.24** | `always low` | normal for itself, but its "itself" is a quarter of the layer |

Run 22603 gives **14 bad channels of 576**: 6 `low/dead`, 1 `hot`, 7 `always low`.

```bash
python analyze_alert_adc.py all.csv --run 22603
```

The `status` column in every output carries one of these five verdicts. The two
thresholds that matter most are `--dead-frac` (0.5) and `--hot-frac` (2.0); they move the
step-2 and step-3 cuts together.

---

## The two traps this avoids

**A dip that affects everything.** Run 22603 sits about 6 % below its own local baseline —
and **all 576 wires read low**, not some of them. A normalized wire reproduces to about
0.4 %, so a coherent 6 % shift is many sigmas for every wire at once, and judged only
against nearby runs the whole chamber looks dead. Step 1 removes it.

**A wire that was never alive.** Any method that asks "has this wire changed?" is blind to
a wire that has always been broken — it never changed. Step 3 asks "is this wire like its
neighbours?" instead.
