#!/usr/bin/env python3
"""Produce every per-wire and per-run figure into figures/.

    figures/per_wire/L<layer>_W<wire>.png   576 files, one per wire, value and cv
                                            against run number, flagged runs circled
    figures/per_run/run<N>.png             1111 files, one per run, the layer-vs-wire
                                            map with bad channels circled

The analysis is run once and reused, which is the only reason this is minutes
rather than hours -- the command-line tool re-reads and re-analyzes all.csv on
every invocation.

    python make_all_figures.py [--only wire|run] [--outdir figures]
"""
import argparse
import contextlib
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_alert_adc as aa

ap = argparse.ArgumentParser()
ap.add_argument("--input", default="all.csv")
ap.add_argument("--outdir", default="figures")
ap.add_argument("--only", choices=["wire", "run"])
ap.add_argument("--dead-frac", type=float, default=0.5)
ap.add_argument("--hot-frac", type=float, default=2.0)
ap.add_argument("--max-seconds", type=float, default=0,
                help="stop cleanly after this long; rerun to resume")
args = ap.parse_args()

t0 = time.time()
res = aa.detect_all(aa.mark_run_quality(aa.add_normalization(
    aa.load(args.input), dead_frac=args.dead_frac, hot_frac=args.hot_frac)))
print(f"analysis: {time.time() - t0:.1f} s, {len(res)} (run, wire) entries, "
      f"{int(res.flag.sum())} flagged", flush=True)

wires = res.groupby(["layer_number", "wire"]).size().index.tolist()
runs = sorted(res.run.unique())
quiet = contextlib.redirect_stdout(io.StringIO())   # the plotters print a table each
START = time.time()

def budget_left():
    return args.max_seconds <= 0 or (time.time() - START) < args.max_seconds

if args.only != "run":
    d = os.path.join(args.outdir, "per_wire")
    os.makedirs(d, exist_ok=True)
    t0 = time.time()
    for i, (L, W) in enumerate(wires, 1):
        f = os.path.join(d, f"L{L}_W{W:02d}.png")
        if os.path.exists(f):
            continue                      # already done, resume where we left off
        if not budget_left():
            print(f"  per_wire paused at {i}/{len(wires)}", flush=True)
            break
        with quiet:
            aa.plot_wire(res, L, W, args.dead_frac, args.hot_frac, f)
        if i % 50 == 0 or i == len(wires):
            print(f"  per_wire {i}/{len(wires)}  ({time.time()-t0:.0f} s)", flush=True)

if args.only != "wire":
    d = os.path.join(args.outdir, "per_run")
    os.makedirs(d, exist_ok=True)
    t0 = time.time()
    for i, r in enumerate(runs, 1):
        f = os.path.join(d, f"run{r}.png")
        if os.path.exists(f):
            continue
        if not budget_left():
            print(f"  per_run paused at {i}/{len(runs)}", flush=True)
            break
        with quiet:
            aa.plot_run_map(res, r, args.dead_frac, args.hot_frac, f)
        if i % 100 == 0 or i == len(runs):
            print(f"  per_run {i}/{len(runs)}  ({time.time()-t0:.0f} s)", flush=True)

tot = sum(os.path.getsize(os.path.join(dp, f))
          for dp, _, fs in os.walk(args.outdir) for f in fs)
n = sum(len(fs) for _, _, fs in os.walk(args.outdir))
print(f"\ndone: {n} files, {tot/1e6:.0f} MB under {args.outdir}/")
