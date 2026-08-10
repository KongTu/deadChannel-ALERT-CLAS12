#!/usr/bin/env python3
"""
analyze_alert_adc.py
====================
Analyze the per-wire ADC (analogue-to-digital converter) timeline values of the
AHDC (ALERT Hyper Drift Chamber), as produced by dump_alert_adc_csv.groovy.

Input CSV columns:
    run, layer_number, layer_code, wire, value, graph_name

What it does
------------
  (i)   --layer/--wire : plot one wire's value as a function of run number
  (ii)  --scan         : flag abnormal (run, wire) entries over the whole dataset
  (iii) --run N        : the "other dimension" -- for ONE run, show all 576 wires
                         (layer vs wire map, as in the online-monitoring logbook
                         figures) plus a table of the bad channels in that run
  (iv)  --summary      : number of bad channels per run, across the campaign
  (v)   --segments     : contiguous run-ranges over which each wire is bad
                         (input for deciding how to store this in the
                         calibration constant database, CCDB, which holds a
                         given set of constants against a range of runs)

Step 1 -- put every run on a common scale
-----------------------------------------
The raw timeline value is a trigger-normalized ADC integral, but it still
breathes coherently from run to run by large factors (beam current, gas, high
voltage, threshold and trigger-composition changes). Over runs 21317-23061 the
overall level varies by more than an order of magnitude, and about a third of
the runs sit below half the campaign-typical level.

That coherent breathing has to be divided out before any per-wire statement can
be made. Judged against its own neighboring runs alone, a wire in a run that is
globally 6 % low sits many robust sigmas below its local baseline -- and so does
every other wire, so the whole detector is flagged for a property of the run.

    rel      = value / (this wire's median over all runs)
    gain     = median of `rel` over all wires in the same run and layer
    cv       = rel / gain          <- "corrected value", what the per-run cuts use

`cv` is 1.0 for a wire behaving at its own typical level once the run-wide (and
layer-wide) scale has been divided out. A dead wire has cv -> 0 and a hot wire
cv >> 1, regardless of how bright or dim the run was overall.

The gain is taken per layer as well as per run, so a change affecting one
superlayer does not leak into the others. Runs whose overall level is far from
normal (--min-gain, --max-gain) are kept but marked `run_ok = False`: at
gain ~ 0.01 the detector was effectively off and the values are noise.

Step 2 -- three per-run cuts, on `cv`
-------------------------------------
  low/dead : cv < dead_frac                 (default 0.5)
  hot      : cv > hot_frac                  (default 2.0)
  outlier  : |robust_z| > threshold         (default 5) on the cv series,
             i.e. a sharp change relative to the SAME wire in adjacent runs

`robust_z` uses a centered rolling median as baseline and 1.4826 x MAD (median
absolute deviation) as the scale, floored at --min-scale (default 0.05 in cv
units): a wire reproducible to 0.4 % should not be called anomalous for a 3 %
wiggle.

Step 3 -- one per-wire cut, on the absolute level
-------------------------------------------------
  always low / always hot : the wire's all-run median, divided by that of the
                            median wire in the SAME layer, outside
                            [dead_frac, hot_frac]

`cv` is normalized to each wire's own median and so is structurally blind to a
wire that is low in EVERY run: such a wire reads cv ~ 1, normal for itself. The
comparison is made per layer because the absolute level differs by a factor of
about 3 between layer 1 and layer 7. These wires are reported as bad in every
run, which is what a per-run dead-channel list has to contain.

The `status` column carries the verdict: `low/dead`, `hot`, `outlier`,
`always low` or `always hot`.

Examples
--------
  # bad channels in one run: map + table  (compare against the logbook figure)
  python analyze_alert_adc.py all.csv --run 22603

  # campaign summary: how many bad channels per run
  python analyze_alert_adc.py all.csv --summary bad_per_run.png

  # how segmented is the dataset?  (the CCDB run-range question)
  python analyze_alert_adc.py all.csv --segments segments.csv

  # single wire vs run
  python analyze_alert_adc.py all.csv --layer 1 --wire 19 --plot l1_w19.png

  # everything flagged, whole dataset
  python analyze_alert_adc.py all.csv --scan flagged.csv
"""
import argparse
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")            # headless: write PNGs without a display (works on ifarm)
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm, TwoSlopeNorm

# AHDC geometry: wires per layer_number 1..8, and the bank layer_code
WIRES_PER_LAYER = [47, 56, 56, 72, 72, 87, 87, 99]
LAYER_CODE = [11, 21, 22, 31, 32, 41, 42, 51]


# --------------------------------------------------------------------------
# input
# --------------------------------------------------------------------------
def load(path):
    df = pd.read_csv(path)
    needed = {"run", "layer_number", "wire", "value"}
    missing = needed - set(df.columns)
    if missing:
        sys.exit(f"ERROR: input is missing column(s): {sorted(missing)}")
    # Coerce to numeric. Blanks or non-numeric entries -- e.g. leftover rows
    # from the ATOF (ALERT Time-Of-Flight), which shares the timeline files and
    # has no layer/wire -- become NaN so we can drop them cleanly.
    for c in ("run", "layer_number", "wire", "value"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    before = len(df)
    df = df.dropna(subset=["run", "layer_number", "wire", "value"])
    dropped = before - len(df)
    if dropped:
        print(f"note: dropped {dropped} row(s) with blank run/layer/wire/value")
    # Some timeline points come back as inf (e.g. a zero trigger count in the
    # normalization). They are not measurements; drop them.
    before = len(df)
    df = df[np.isfinite(df.value)]
    n_inf = before - len(df)
    if n_inf:
        print(f"note: dropped {n_inf} row(s) with non-finite value")
    for c in ("run", "layer_number", "wire"):
        df[c] = df[c].astype(int)
    df["value"] = df["value"].astype(float)
    return df.sort_values(["layer_number", "wire", "run"]).reset_index(drop=True)


# --------------------------------------------------------------------------
# run-level normalization
# --------------------------------------------------------------------------
def add_normalization(df, per_layer=True):
    """Add wire_med, rel, gain and cv (see module docstring).

    per_layer=True computes the run gain within each layer, which also absorbs
    layer-dependent run effects (e.g. a threshold change on one superlayer).
    """
    df = df.copy()
    df["wire_med"] = df.groupby(["layer_number", "wire"]).value.transform("median")
    # A wire that is dead in every single run has wire_med == 0; `rel` is then
    # undefined. Those wires are caught separately as `permanently_low`.
    df["rel"] = np.where(df.wire_med > 0, df.value / df.wire_med.where(df.wire_med > 0), np.nan)
    key = ["run", "layer_number"] if per_layer else ["run"]
    df["gain"] = df.groupby(key).rel.transform("median")
    df["cv"] = df.rel / df.gain
    return df


def mark_run_quality(df, min_gain=0.1, max_gain=10.0):
    """Mark runs whose OVERALL level is far from the campaign norm.

    Dividing by the run gain rescues a run that is uniformly 30 % low, but not a
    run where the detector was essentially off (gain ~ 0.01): there the per-wire
    values are consistent with noise and the surviving structure is statistical.
    Those runs are kept but marked `run_ok = False`, because their bad-channel
    count says more about the run than about the wires.
    """
    df = df.copy()
    rg = df.groupby("run").gain.median()
    ok = (rg > min_gain) & (rg < max_gain)
    df["run_ok"] = df.run.map(ok)
    n_bad_run = int((~ok).sum())
    if n_bad_run:
        print(f"note: {n_bad_run} of {len(ok)} runs have an overall level outside "
              f"[{min_gain:g}, {max_gain:g}] x normal and are marked run_ok=False")
    return df


def detect_wire(g, window=11, threshold=5.0, dead_frac=0.5, hot_frac=2.0,
                min_scale=0.05):
    """Flag anomalous runs for ONE wire's time-ordered series of cv.

    Returns a copy of g with the analysis columns added. `g` must already have
    the `cv` column from add_normalization().
    """
    g = g.sort_values("run").copy()
    cv = g["cv"].to_numpy(dtype=float)

    # 1. local_median: expected cv for this run given its neighbors
    local_med = (g["cv"].rolling(window, center=True, min_periods=3)
                 .median().bfill().ffill())
    # 2. detrended: residual after removing slow drift
    detrended = cv - local_med.to_numpy()
    # 3. MAD -> 4. scale: robust sigma of the residuals, floored at min_scale
    mad = np.nanmedian(np.abs(detrended - np.nanmedian(detrended)))
    scale = max(1.4826 * mad, min_scale)
    # 5. robust_z: how many robust sigmas from the local baseline
    robust_z = detrended / scale

    is_low = cv < dead_frac
    is_hot = cv > hot_frac
    is_outlier = np.abs(robust_z) > threshold
    flag = is_low | is_hot | is_outlier
    # precedence: an absolute verdict beats a local one
    reason = np.where(is_low, "low/dead",
                      np.where(is_hot, "hot",
                               np.where(is_outlier, "outlier", "")))

    g["local_median"] = local_med.to_numpy()
    g["robust_z"] = robust_z
    g["scale"] = scale
    g["flag"] = flag & np.isfinite(cv)
    g["reason"] = reason
    return g


def add_chronic(res, dead_frac=0.5, hot_frac=2.0):
    """Mark wires that are low (or high) in essentially EVERY run.

    `cv` is normalized to each wire's own median, so it is structurally blind to
    this case: a wire that has been dead all campaign has cv ~ 1 and looks
    perfectly normal relative to itself. Such a wire is nevertheless dead in
    every run, and a per-run dead-channel list has to contain it.

    The comparison is absolute and made against the median wire in the SAME
    layer, because the level differs by a factor of ~3 between layer 1 and 7.
    """
    wm = (res.groupby(["layer_number", "wire"]).value.median()
          .rename("wire_median").reset_index())
    wm["layer_typical"] = wm.groupby("layer_number").wire_median.transform("median")
    wm["rel_to_layer"] = wm.wire_median / wm.layer_typical
    wm["chronic"] = np.where(wm.rel_to_layer < dead_frac, "always low",
                             np.where(wm.rel_to_layer > hot_frac, "always hot", ""))
    res = res.merge(wm[["layer_number", "wire", "rel_to_layer", "chronic"]],
                    on=["layer_number", "wire"], how="left")
    res["flag"] = res.flag | (res.chronic != "")
    # `reason` stays the per-run verdict; `status` is what to report
    res["status"] = np.where(res.chronic != "", res.chronic, res.reason)
    n = int((wm.chronic != "").sum())
    if n:
        print(f"note: {n} wire(s) are outside [{dead_frac:g}, {hot_frac:g}] x the typical "
              f"wire of their layer in essentially every run; they are reported as bad "
              f"in every run")
    return res


def detect_all(df, window=11, threshold=5.0, dead_frac=0.5, hot_frac=2.0,
               min_scale=0.05):
    """Run detect_wire over every wire, then add the chronic (all-run) verdict."""
    parts = [detect_wire(g, window, threshold, dead_frac, hot_frac, min_scale)
             for _, g in df.groupby(["layer_number", "wire"])]
    res = pd.concat(parts, ignore_index=True)
    return add_chronic(res, dead_frac, hot_frac)


# --------------------------------------------------------------------------
# (i) one wire vs run
# --------------------------------------------------------------------------
def plot_wire(res, layer, wire, dead_frac, hot_frac, outpath):
    g = res[(res.layer_number == layer) & (res.wire == wire)].sort_values("run")
    if g.empty:
        print(f"No data for layer {layer} wire {wire}")
        return
    code = g.layer_code.iloc[0] if "layer_code" in g else ""

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)

    ax0.plot(g.run, g.value, "-", color="0.75", lw=1, zorder=1)
    ax0.scatter(g.run, g.value, s=14, color="steelblue", zorder=2, label="raw value")
    ax0.plot(g.run, g.wire_med * g.gain, "--", color="darkorange", lw=1.2,
             label="expected level (wire median x run gain)")
    ax0.set_ylabel("AHDC ADC value")
    ax0.set_title(f"AHDC ADC - layer {layer} (code {code}), wire {wire}")
    ax0.legend(fontsize=8)

    ax1.plot(g.run, g.cv, "-", color="0.75", lw=1, zorder=1)
    ax1.scatter(g.run, g.cv, s=14, color="seagreen", zorder=2, label="cv (run-normalized)")
    ax1.plot(g.run, g.local_median, "--", color="green", lw=1, label="local median")
    ax1.axhline(1.0, color="0.4", lw=0.8)
    ax1.axhline(dead_frac, color="red", ls=":", lw=1, label=f"dead floor ({dead_frac:g})")
    ax1.axhline(hot_frac, color="magenta", ls=":", lw=1, label=f"hot ceiling ({hot_frac:g})")
    fl = g[g.flag]
    if not fl.empty:
        ax1.scatter(fl.run, fl.cv, s=70, facecolors="none", edgecolors="red",
                    linewidths=1.6, label="flagged", zorder=3)
    ax1.set_xlabel("run number")
    ax1.set_ylabel("cv = value / (wire median x run gain)")
    ax1.legend(fontsize=8, ncol=2)

    fig.tight_layout()
    fig.savefig(outpath, dpi=120)
    plt.close(fig)
    print(f"wrote {outpath}  ({len(fl)} flagged of {len(g)} runs)")
    if not fl.empty:
        print(fl[["run", "value", "cv", "robust_z", "reason"]].to_string(index=False))


# --------------------------------------------------------------------------
# (iii) one run, all wires -- the "other dimension"
# --------------------------------------------------------------------------
def _grid(run_df, column):
    """Fill an 8 x max(wires) array with `column`; NaN where the wire does not exist."""
    grid = np.full((8, max(WIRES_PER_LAYER)), np.nan)
    for _, r in run_df.iterrows():
        grid[int(r.layer_number) - 1, int(r.wire) - 1] = r[column]
    return grid


def plot_run_map(res, run, dead_frac, hot_frac, outpath):
    """Layer-vs-wire maps for one run, in the layout of the online-monitoring
    logbook figures: raw value (as posted online) and run-normalized cv with the
    bad channels circled."""
    g = res[res.run == run]
    if g.empty:
        print(f"No data for run {run}")
        return None
    raw = _grid(g, "value")
    cv = _grid(g, "cv")
    bad = g[g.flag]

    cmap = plt.get_cmap("jet").copy()
    cmap.set_bad("0.75")                      # grey where the wire does not exist

    fig, axes = plt.subplots(2, 1, figsize=(13, 6.5), sharex=True)

    pos = raw[np.isfinite(raw) & (raw > 0)]
    im0 = axes[0].imshow(np.ma.masked_invalid(raw), aspect="auto", origin="lower",
                         cmap=cmap, extent=[0.5, raw.shape[1] + 0.5, 0.5, 8.5],
                         norm=LogNorm(vmin=max(pos.min(), 1e-6), vmax=pos.max())
                         if pos.size else None)
    axes[0].set_title(f"AHDC ADC (trigger-normalized integral) - run {run}")
    fig.colorbar(im0, ax=axes[0], pad=0.01, label="value (log)")

    cmap2 = plt.get_cmap("RdBu_r").copy()
    cmap2.set_bad("0.75")
    im1 = axes[1].imshow(np.ma.masked_invalid(cv), aspect="auto", origin="lower",
                         cmap=cmap2, extent=[0.5, cv.shape[1] + 0.5, 0.5, 8.5],
                         norm=TwoSlopeNorm(vmin=0.0, vcenter=1.0, vmax=2.0))
    fig.colorbar(im1, ax=axes[1], pad=0.01,
                 label="cv  (1 = normal, 0 = dead, 2 = hot)")
    per_run = bad[bad.chronic == ""] if "chronic" in bad.columns else bad
    chronic = bad[bad.chronic != ""] if "chronic" in bad.columns else bad.iloc[0:0]
    axes[1].set_title(f"run-normalized: {len(bad)} bad channel(s) — "
                      f"{len(per_run)} bad in this run (low<{dead_frac:g}, hot>{hot_frac:g}), "
                      f"{len(chronic)} bad in every run")
    if not per_run.empty:
        axes[1].scatter(per_run.wire, per_run.layer_number, s=150, facecolors="none",
                        edgecolors="magenta", linewidths=2.0, label="bad in this run")
    if not chronic.empty:
        axes[1].scatter(chronic.wire, chronic.layer_number, s=150, facecolors="none",
                        edgecolors="black", linewidths=2.0, linestyle="--",
                        label="bad in every run")
    if not bad.empty:
        axes[1].legend(loc="upper right", fontsize=8, framealpha=0.9)

    for ax in axes:
        ax.set_ylabel("layer number")
        ax.set_yticks(range(1, 9))
    axes[1].set_xlabel("wire number")

    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)
    print(f"wrote {outpath}")
    return bad


def plot_run_panels(res, run, dead_frac, hot_frac, outpath):
    """The same run as 8 stacked per-layer panels.

    Two series are drawn per layer, because the two kinds of bad channel are
    judged on two different quantities and a marker must sit on the curve it
    came from:

      cv           (blue)  -- this run against the wire's OWN norm.
                             Catches a wire that changed in this run.
      rel_to_layer (grey)  -- the wire's all-run median against the median wire
                             of the same layer. Catches a wire that has been
                             low the whole campaign, which `cv` cannot see
                             because it is normalized to that same wire.

    A chronically dead wire sits at cv ~ 1 (normal for itself) but low on the
    grey series, so its marker belongs on the grey one.
    """
    g = res[res.run == run]
    if g.empty:
        return
    has_chronic = "chronic" in g.columns
    fig, axes = plt.subplots(8, 1, figsize=(12, 13.5), sharex=True)
    for i, ax in enumerate(axes, start=1):
        gl = g[g.layer_number == i].sort_values("wire")
        top = max(2.4, (gl.cv.max() * 1.15) if len(gl) else 2.4)
        ax.axhspan(0, dead_frac, color="red", alpha=0.07)
        ax.axhspan(hot_frac, top, color="magenta", alpha=0.07)
        ax.axhline(1.0, color="0.5", lw=0.8)

        if has_chronic:
            ax.plot(gl.wire, gl.rel_to_layer, "-", color="0.85", lw=0.7, zorder=1)
            ax.scatter(gl.wire, gl.rel_to_layer, s=8, color="0.62", marker="s",
                       zorder=2, label="wire median vs typical wire of this layer")
        ax.plot(gl.wire, gl.cv, "-", color="0.8", lw=0.8, zorder=3)
        ax.scatter(gl.wire, gl.cv, s=12, color="steelblue", zorder=4,
                   label="cv: this run vs the wire's own norm")

        per_run = gl[gl.flag & (gl.chronic == "")] if has_chronic else gl[gl.flag]
        chronic = gl[gl.chronic != ""] if has_chronic else gl.iloc[0:0]
        if not per_run.empty:
            ax.scatter(per_run.wire, per_run.cv, s=80, facecolors="none",
                       edgecolors="red", lw=1.6, zorder=5, label="bad in this run")
            for _, r in per_run.iterrows():
                ax.annotate(int(r.wire), (r.wire, r.cv), textcoords="offset points",
                            xytext=(0, 7), ha="center", fontsize=7, color="red")
        if not chronic.empty:
            ax.scatter(chronic.wire, chronic.rel_to_layer, s=80, facecolors="none",
                       edgecolors="black", lw=1.6, linestyle="--", zorder=5,
                       label="bad in every run")
            for _, r in chronic.iterrows():
                ax.annotate(int(r.wire), (r.wire, r.rel_to_layer),
                            textcoords="offset points", xytext=(0, -13),
                            ha="center", fontsize=7, color="black")
        ax.set_ylabel(f"L{i}", rotation=0, ha="right", va="center")
        ax.set_ylim(0, top)
        ax.set_xlim(0, max(WIRES_PER_LAYER) + 1)

    # one legend for the whole figure, built from every label used in any panel
    handles, labels = {}, []
    for ax in axes:
        for h, l in zip(*ax.get_legend_handles_labels()):
            if l not in handles:
                handles[l] = h
                labels.append(l)
    axes[0].legend([handles[l] for l in labels], labels, fontsize=7.5,
                   ncol=2, loc="upper left", framealpha=0.92)
    axes[0].set_title(f"run {run}: bad channels by layer "
                      f"(shaded = dead below {dead_frac:g}, hot above {hot_frac:g})")
    axes[-1].set_xlabel("wire number")
    fig.tight_layout()
    fig.savefig(outpath, dpi=120)
    plt.close(fig)
    print(f"wrote {outpath}")


def run_report(res, run, dead_frac, hot_frac, prefix):
    bad = plot_run_map(res, run, dead_frac, hot_frac, f"{prefix}_map.png")
    if bad is None:
        return
    plot_run_panels(res, run, dead_frac, hot_frac, f"{prefix}_panels.png")
    cols = ["run", "layer_number", "layer_code", "wire", "value", "wire_med",
            "gain", "cv", "rel_to_layer", "robust_z", "status"]
    cols = [c for c in cols if c in bad.columns]
    tab = bad[cols].sort_values(["layer_number", "wire"])
    tab.to_csv(f"{prefix}_bad.csv", index=False)
    print(f"wrote {prefix}_bad.csv")
    if "run_ok" in res.columns and not res[res.run == run].run_ok.iloc[0]:
        print(f"\nWARNING: run {run} reads far from the normal overall level "
              f"(gain={res[res.run == run].gain.median():.3f}); "
              f"treat its bad-channel list with care")
    print(f"\nBad channels in run {run}: {len(tab)} of {len(res[res.run == run])}")
    if not tab.empty:
        print(tab.to_string(index=False,
                            formatters={"value": "{:.4f}".format,
                                        "wire_med": "{:.4f}".format,
                                        "gain": "{:.3f}".format,
                                        "cv": "{:.3f}".format,
                                        "rel_to_layer": "{:.2f}".format,
                                        "robust_z": "{:.1f}".format}))


# --------------------------------------------------------------------------
# (iv) bad channels per run, across the campaign
# --------------------------------------------------------------------------
def plot_summary(res, outpath, csv_path=None):
    per = (res.groupby("run")
           .agg(n_bad=("flag", "sum"),
                n_chronic=("status", lambda s: s.str.startswith("always").sum()),
                n_low=("status", lambda s: (s == "low/dead").sum()),
                n_hot=("status", lambda s: (s == "hot").sum()),
                n_outlier=("status", lambda s: (s == "outlier").sum()),
                gain=("gain", "median"),
                run_ok=("run_ok", "first") if "run_ok" in res.columns else ("flag", "size"),
                n_wires=("flag", "size"))
           .reset_index())

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(13, 7), sharex=True,
                                   gridspec_kw={"height_ratios": [2, 1]})
    if "run_ok" in res.columns:
        for r in per.loc[~per.run_ok.astype(bool), "run"]:
            for ax in (ax0, ax1):
                ax.axvspan(r - 0.5, r + 0.5, color="0.85", zorder=0)
        ax0.plot([], [], color="0.85", lw=6, label="run reads far from normal level")
    ax0.plot(per.run, per.n_bad, "-", color="0.8", lw=0.8, zorder=1)
    ax0.scatter(per.run, per.n_bad, s=9, color="firebrick", zorder=2, label="all bad")
    ax0.plot(per.run, per.n_low, lw=1, color="steelblue", label="low/dead in this run")
    ax0.plot(per.run, per.n_hot, lw=1, color="magenta", label="hot in this run")
    ax0.plot(per.run, per.n_chronic, lw=1.2, color="black", ls="--",
             label="bad in every run")
    ax0.set_ylabel("bad channels in the run")
    ax0.set_title("AHDC: number of bad channels per run "
                  f"({per.run.min()}-{per.run.max()}, {len(per)} runs, 576 wires)")
    ax0.legend(fontsize=8)
    ax0.grid(alpha=0.3)

    ax1.plot(per.run, per.gain, lw=1, color="darkorange")
    ax1.set_yscale("log")
    ax1.axhline(1.0, color="0.5", lw=0.8)
    ax1.set_ylabel("run gain\n(overall ADC level)")
    ax1.set_xlabel("run number")
    ax1.grid(alpha=0.3)
    ax1.text(0.005, 0.06, "runs far below 1 read low detector-wide; their bad-channel "
             "count is less reliable", transform=ax1.transAxes, fontsize=7, color="0.35")

    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)
    print(f"wrote {outpath}")

    if csv_path:
        per.to_csv(csv_path, index=False)
        print(f"wrote {csv_path}")

    print("\nbad channels per run:")
    print(per.n_bad.describe().to_string())
    # Only look for "events" among runs that read at a normal overall level;
    # otherwise the list is just the runs where the detector was off.
    good = per[per.run_ok.astype(bool)] if "run_ok" in res.columns else per
    jump = good.assign(d=good.n_bad.diff()).dropna()
    big = jump.reindex(jump.d.abs().sort_values(ascending=False).index).head(12)
    print("\nLargest run-to-run changes in the bad-channel count "
          "(candidate events to look up in the logbook):")
    print(big[["run", "n_bad", "d", "gain"]]
          .rename(columns={"d": "change"})
          .to_string(index=False, formatters={"change": "{:+.0f}".format,
                                              "gain": "{:.3f}".format}))
    return per



# --------------------------------------------------------------------------
# (v) contiguous bad-run segments -- input for the CCDB storage question
# --------------------------------------------------------------------------
def segments(res, out_csv, plot_path=None, min_len=1):
    """For each wire, the contiguous stretches of runs over which it is bad.

    Runs marked run_ok=False are dropped first: a handful of detector-off runs
    scattered through a stable period would otherwise chop one long segment into
    many short ones and make the dataset look far more fragmented than it is.
    """
    if "run_ok" in res.columns:
        n_before = res.run.nunique()
        res = res[res.run_ok.astype(bool)]
        print(f"segments: using {res.run.nunique()} of {n_before} runs "
              f"(dropped runs that read far from the normal level)")
    rows = []
    for (layer, wire), g in res.groupby(["layer_number", "wire"]):
        g = g.sort_values("run")
        bad = g.flag.to_numpy()
        runs = g.run.to_numpy()
        if not bad.any():
            continue
        edges = np.diff(bad.astype(int))
        starts = list(np.where(edges == 1)[0] + 1)
        ends = list(np.where(edges == -1)[0])
        if bad[0]:
            starts = [0] + starts
        if bad[-1]:
            ends = ends + [len(bad) - 1]
        for s, e in zip(starts, ends):
            rows.append(dict(layer_number=layer, wire=wire,
                             run_start=runs[s], run_end=runs[e],
                             n_runs=e - s + 1,
                             status=pd.Series(g.status.to_numpy()[s:e + 1]).mode().iat[0]))
    seg = pd.DataFrame(rows)
    if seg.empty:
        print("no bad segments found")
        return seg
    seg = seg[seg.n_runs >= min_len].sort_values(["layer_number", "wire", "run_start"])
    seg.to_csv(out_csv, index=False)
    print(f"wrote {out_csv}: {len(seg)} bad segments over "
          f"{seg.groupby(['layer_number','wire']).ngroups} wires")

    n1 = (seg.n_runs == 1).sum()
    print(f"\nsegment length (in runs): median={seg.n_runs.median():.0f} "
          f"mean={seg.n_runs.mean():.1f} max={seg.n_runs.max()}")
    print(f"single-run segments: {n1} of {len(seg)} ({100*n1/len(seg):.0f} %)")
    cov = seg.groupby("n_runs").n_runs.sum().sort_index()
    print(f"fraction of all bad (run,wire) entries living in single-run segments: "
          f"{100*cov.get(1,0)/cov.sum():.0f} %")
    per_wire = seg.groupby(["layer_number", "wire"]).size()
    print(f"segments per affected wire: median={per_wire.median():.0f} "
          f"max={per_wire.max()}  ({(per_wire>10).sum()} wires with >10 segments)")

    if plot_path:
        fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(12, 4.2))
        ax0.hist(seg.n_runs, bins=np.logspace(0, np.log10(seg.n_runs.max() + 1), 40),
                 color="steelblue", edgecolor="white")
        ax0.set_xscale("log")
        ax0.set_yscale("log")
        ax0.set_xlabel("segment length (consecutive runs)")
        ax0.set_ylabel("number of segments")
        ax0.set_title("How long does a wire stay bad?")
        ax1.hist(per_wire, bins=np.arange(0.5, per_wire.max() + 1.5),
                 color="firebrick", edgecolor="white")
        ax1.set_yscale("log")
        ax1.set_xlabel("bad segments per affected wire")
        ax1.set_ylabel("number of wires")
        ax1.set_title("How often does a wire change state?")
        fig.tight_layout()
        fig.savefig(plot_path, dpi=130)
        plt.close(fig)
        print(f"wrote {plot_path}")
    return seg


# --------------------------------------------------------------------------
# (ii) whole-dataset scan
# --------------------------------------------------------------------------
def scan_all(res, dead_frac, hot_frac, out_csv):
    flagged = res[res.flag].copy()
    cols = [c for c in ["run", "layer_number", "layer_code", "wire", "value",
                        "wire_med", "gain", "cv", "rel_to_layer", "local_median",
                        "robust_z", "status"]
            if c in flagged.columns]
    flagged[cols].to_csv(out_csv, index=False)
    print(f"\nwrote {out_csv}: {len(flagged)} flagged (run,wire) entries "
          f"out of {len(res)} total")

    summary = (res.groupby(["layer_number", "wire"])
               .agg(n_runs=("run", "size"),
                    n_flagged=("flag", "sum"),
                    median_value=("value", "median"),
                    rel_to_layer=("rel_to_layer", "first"),
                    chronic=("chronic", "first"))
               .reset_index())
    summary["frac_flagged"] = summary.n_flagged / summary.n_runs

    chron = summary[summary.chronic != ""]
    print(f"\nwires outside [{dead_frac:g}, {hot_frac:g}] x their layer's typical wire in "
          f"essentially every run: {len(chron)}")
    if not chron.empty:
        print(chron.sort_values("rel_to_layer")
              [["layer_number", "wire", "n_runs", "median_value", "rel_to_layer", "chronic"]]
              .to_string(index=False, formatters={"median_value": "{:.4f}".format,
                                                  "rel_to_layer": "{:.2f}".format}))

    worst = summary[summary.chronic == ""].sort_values("frac_flagged", ascending=False).head(15)
    print("\nWires most often bad in a single run (chronic wires excluded, top 15):")
    print(worst.to_string(index=False))
    return flagged, summary


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Plot and flag AHDC per-wire ADC vs run.")
    ap.add_argument("input", help="alert_adc.csv")
    ap.add_argument("--layer", type=int, help="layer_number (1-8) to plot")
    ap.add_argument("--wire", type=int, help="wire number to plot")
    ap.add_argument("--plot", metavar="PNG", help="output plot path (needs --layer and --wire)")
    ap.add_argument("--scan", metavar="CSV", nargs="?", const="alert_adc_flagged.csv",
                    help="scan all wires; write flagged runs here")
    ap.add_argument("--run", type=int, metavar="N",
                    help="per-run report: layer-vs-wire map, per-layer panels, bad-channel table")
    ap.add_argument("--run-prefix", metavar="STR",
                    help="output prefix for --run (default run<N>)")
    ap.add_argument("--summary", metavar="PNG", nargs="?", const="bad_per_run.png",
                    help="plot the number of bad channels per run")
    ap.add_argument("--summary-csv", metavar="CSV", help="also write the per-run counts")
    ap.add_argument("--segments", metavar="CSV", nargs="?", const="segments.csv",
                    help="write contiguous bad-run segments per wire")
    ap.add_argument("--window", type=int, default=11, help="rolling-median window in runs (default 11)")
    ap.add_argument("--threshold", type=float, default=5.0, help="robust-z threshold (default 5)")
    ap.add_argument("--dead-frac", type=float, default=0.5,
                    help="flag cv below this (default 0.5)")
    ap.add_argument("--hot-frac", type=float, default=2.0,
                    help="flag cv above this (default 2.0)")
    ap.add_argument("--min-scale", type=float, default=0.05,
                    help="floor on the robust scale, in cv units (default 0.05)")
    ap.add_argument("--no-run-norm", action="store_true",
                    help="cut on the raw value instead of the run-normalized cv")
    ap.add_argument("--global-gain", action="store_true",
                    help="normalize per run only, not per run and layer")
    ap.add_argument("--min-gain", type=float, default=0.1,
                    help="runs whose overall level is below this are marked unreliable (default 0.1)")
    ap.add_argument("--max-gain", type=float, default=10.0,
                    help="runs whose overall level is above this are marked unreliable (default 10)")
    args = ap.parse_args()

    df = load(args.input)
    print(f"loaded {len(df)} rows: {df.layer_number.nunique()} layers, "
          f"{df.groupby(['layer_number','wire']).ngroups} wires, "
          f"runs {df.run.min()}-{df.run.max()}")

    df = add_normalization(df, per_layer=not args.global_gain)
    if args.no_run_norm:
        df["gain"] = 1.0
        df["cv"] = df.rel
    g = df.groupby("run").gain.median()
    print(f"run gain (overall ADC level relative to the wire medians): "
          f"min={g.min():.3f} median={g.median():.3f} max={g.max():.3f}; "
          f"{(g < 0.5).sum()} of {len(g)} runs below 0.5")
    df = mark_run_quality(df, args.min_gain, args.max_gain)

    res = detect_all(df, args.window, args.threshold, args.dead_frac,
                     args.hot_frac, args.min_scale)

    did = False
    if args.layer is not None and args.wire is not None:
        out = args.plot or f"adc_layer{args.layer}_wire{args.wire}.png"
        plot_wire(res, args.layer, args.wire, args.dead_frac, args.hot_frac, out)
        did = True
    if args.run is not None:
        run_report(res, args.run, args.dead_frac, args.hot_frac,
                   args.run_prefix or f"run{args.run}")
        did = True
    if args.summary is not None:
        plot_summary(res, args.summary, args.summary_csv)
        did = True
    if args.segments is not None:
        segments(res, args.segments,
                 plot_path=args.segments.replace(".csv", "") + "_hist.png")
        did = True
    if args.scan is not None or not did:
        scan_all(res, args.dead_frac, args.hot_frac,
                 args.scan if args.scan is not None else "alert_adc_flagged.csv")


if __name__ == "__main__":
    main()
