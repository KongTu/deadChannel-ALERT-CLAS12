#!/usr/bin/env python3
"""
analyze_alert_adc.py
====================
Analyze the AHDC per-wire ADC timeline values produced by dump_alert_adc_csv.groovy.

Input CSV columns:
    run, layer_number, layer_code, wire, value, graph_name

Two things it does:
  (i)  plot the ADC value as a function of run number for a chosen (layer, wire)
  (ii) flag "abnormal" runs per wire -- runs whose value departs from the value
       in ADJACENT runs (local baseline), which catches a wire that goes dead
       (drops toward zero) or spikes for a subset of runs.

Method for (ii), per wire, in run order:
  - local_median : centered rolling median over `window` runs  -> the expected
                   level given the neighboring runs
  - detrended    : value - local_median
  - robust scale : 1.4826 * MAD(detrended) over the whole series (stable even
                   when the rolling window is short)
  - robust_z     : detrended / scale  -> flag if |robust_z| > threshold
  - dead floor   : value < dead_frac * (this wire's median)  -> flag a collapse
                   toward zero even if it is gradual

Examples
--------
  # plot one wire and print its flagged runs
  python analyze_alert_adc.py alert_adc.csv --layer 1 --wire 1 --plot l1_w1.png

  # scan every wire, write all flagged runs to a CSV + a per-wire summary
  python analyze_alert_adc.py alert_adc.csv --scan flagged.csv

  # do both
  python analyze_alert_adc.py alert_adc.csv --layer 1 --wire 1 --plot l1_w1.png --scan flagged.csv
"""
import argparse
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")            # headless: write PNGs without a display (works on ifarm)
import matplotlib.pyplot as plt


def load(path):
    df = pd.read_csv(path)
    needed = {"run", "layer_number", "wire", "value"}
    missing = needed - set(df.columns)
    if missing:
        sys.exit(f"ERROR: input is missing column(s): {sorted(missing)}")
    df = df.dropna(subset=["value"])
    for c in ("run", "layer_number", "wire"):
        df[c] = df[c].astype(int)
    df["value"] = df["value"].astype(float)
    return df.sort_values(["layer_number", "wire", "run"]).reset_index(drop=True)


def detect_wire(g, window=11, threshold=5.0, dead_frac=0.2):
    """Flag anomalous runs for ONE wire's time-ordered series.
    Returns a copy of g with added analysis columns."""
    g = g.sort_values("run").copy()
    v = g["value"].to_numpy(dtype=float)

    # expected level from adjacent runs
    local_med = (g["value"].rolling(window, center=True, min_periods=3)
                 .median().bfill().ffill())
    detrended = v - local_med.to_numpy()

    # robust spread of the residuals across the whole series
    mad = np.median(np.abs(detrended - np.median(detrended)))
    scale = 1.4826 * mad if mad > 0 else 0.0
    robust_z = detrended / scale if scale > 0 else np.zeros_like(v)

    wire_med = np.median(v)
    dead_floor = dead_frac * wire_med

    is_outlier = (scale > 0) & (np.abs(robust_z) > threshold)
    is_low = v < dead_floor
    flag = is_outlier | is_low
    reason = np.where(is_low, "low/dead", np.where(is_outlier, "outlier", ""))

    g["local_median"] = local_med.to_numpy()
    g["robust_z"] = robust_z
    g["dead_floor"] = dead_floor
    g["flag"] = flag
    g["reason"] = reason
    return g


def plot_wire(df, layer, wire, window, threshold, dead_frac, outpath):
    g = df[(df.layer_number == layer) & (df.wire == wire)]
    if g.empty:
        print(f"No data for layer {layer} wire {wire}")
        return
    g = detect_wire(g, window, threshold, dead_frac)
    code = g.layer_code.iloc[0] if "layer_code" in g else ""

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(g.run, g.value, "-", color="0.7", lw=1, zorder=1)
    ax.scatter(g.run, g.value, s=18, color="steelblue", label="value", zorder=2)
    ax.plot(g.run, g.local_median, "--", color="green", lw=1.2,
            label=f"local median (window={window})")
    ax.axhline(g.dead_floor.iloc[0], color="red", ls=":", lw=1,
               label=f"dead floor ({dead_frac:g}×median)")
    fl = g[g.flag]
    if not fl.empty:
        ax.scatter(fl.run, fl.value, s=70, facecolors="none", edgecolors="red",
                   linewidths=1.7, label="flagged", zorder=3)
    ax.set_xlabel("run number")
    ax.set_ylabel("AHDC ADC value")
    ax.set_title(f"AHDC ADC — layer {layer} (code {code}), wire {wire}")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(outpath, dpi=120)
    plt.close(fig)
    print(f"wrote {outpath}  ({len(fl)} flagged of {len(g)} runs)")
    if not fl.empty:
        print(fl[["run", "value", "local_median", "robust_z", "reason"]]
              .to_string(index=False))


def scan_all(df, window, threshold, dead_frac, out_csv):
    parts = [detect_wire(g, window, threshold, dead_frac)
             for _, g in df.groupby(["layer_number", "wire"])]
    res = pd.concat(parts, ignore_index=True)

    flagged = res[res.flag].copy()
    cols = [c for c in ["run", "layer_number", "layer_code", "wire",
                        "value", "local_median", "robust_z", "reason"]
            if c in flagged.columns]
    flagged[cols].to_csv(out_csv, index=False)
    print(f"\nwrote {out_csv}: {len(flagged)} flagged (run,wire) entries "
          f"out of {len(res)} total")

    # per-wire summary: how often each wire is flagged + is it permanently low?
    global_typical = res.groupby(["layer_number", "wire"]).value.median().median()
    summary = (res.groupby(["layer_number", "wire"])
               .agg(n_runs=("run", "size"),
                    n_flagged=("flag", "sum"),
                    median_value=("value", "median"))
               .reset_index())
    summary["frac_flagged"] = summary.n_flagged / summary.n_runs
    summary["permanently_low"] = summary.median_value < dead_frac * global_typical

    worst = summary.sort_values(["permanently_low", "frac_flagged"],
                                ascending=False).head(15)
    print("\nWires with the most flagged runs (top 15):")
    print(worst.to_string(index=False))
    return res, flagged, summary


def main():
    ap = argparse.ArgumentParser(description="Plot and flag AHDC per-wire ADC vs run.")
    ap.add_argument("input", help="alert_adc.csv")
    ap.add_argument("--layer", type=int, help="layer_number (1-8) to plot")
    ap.add_argument("--wire", type=int, help="wire number to plot")
    ap.add_argument("--plot", metavar="PNG", help="output plot path (needs --layer and --wire)")
    ap.add_argument("--scan", metavar="CSV", nargs="?", const="alert_adc_flagged.csv",
                    help="scan all wires; write flagged runs here (default alert_adc_flagged.csv)")
    ap.add_argument("--window", type=int, default=11, help="rolling-median window in runs (default 11)")
    ap.add_argument("--threshold", type=float, default=5.0, help="robust-z threshold (default 5)")
    ap.add_argument("--dead-frac", type=float, default=0.2,
                    help="flag value below this fraction of the wire median (default 0.2)")
    args = ap.parse_args()

    df = load(args.input)
    print(f"loaded {len(df)} rows: {df.layer_number.nunique()} layers, "
          f"{df.groupby(['layer_number','wire']).ngroups} wires, "
          f"runs {df.run.min()}-{df.run.max()}")

    did_something = False
    if args.layer is not None and args.wire is not None:
        out = args.plot or f"adc_layer{args.layer}_wire{args.wire}.png"
        plot_wire(df, args.layer, args.wire, args.window, args.threshold, args.dead_frac, out)
        did_something = True

    if args.scan is not None or not did_something:
        out_csv = args.scan if args.scan is not None else "alert_adc_flagged.csv"
        scan_all(df, args.window, args.threshold, args.dead_frac, out_csv)


if __name__ == "__main__":
    main()
