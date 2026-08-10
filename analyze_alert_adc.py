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

Everything is a ratio taken inside a single run
-----------------------------------------------
The raw timeline value is a trigger-normalized ADC integral, but the overall
level still breathes from run to run by large factors: beam current, gas, high
voltage, thresholds and trigger composition all move it, and over runs
21317-23061 it varies by more than an order of magnitude.

Both references below are ratios formed within one run, so that common motion
cancels exactly and no separate run-normalization step is needed.

Reference A -- the wire against its neighbours
----------------------------------------------
    lay_med      = median `value` over the wires of that layer, in that run
    rel_to_layer = value / lay_med

Per layer, because the absolute level differs by a factor of about 3 between
layer 1 and layer 7. This reference needs no history at all, so it sees a wire
that was already broken before the first run.

Reference B -- the wire against itself
--------------------------------------
    own_norm = median of `rel_to_layer` over the runs where the wire reads like
               its layer, i.e. its usual standing within the layer
    cv       = rel_to_layer / own_norm

Reference A alone is not enough: its threshold asks every wire to fall to the
same fraction of the layer median, so a wire whose healthy level sits above its
neighbours can lose most of its output and still clear the cut. `cv` measures
how far a wire has moved from its own usual standing, which is the same question
for every wire.

`own_norm` is estimated only from the wire's healthy-looking runs. A median over
its whole history would land between the dead and healthy levels of any wire
broken for a large share of the campaign, and that wire's GOOD runs would then
read about twice the norm and be flagged hot. A wire with fewer than
--min-healthy such runs gets no `own_norm`: `cv` is left undefined and the wire
is judged on reference A alone.

The five cuts
-------------
  low/dead     : cv < dead_frac                 (default 0.5)
  hot          : cv > hot_frac                  (default 2.0)
  low vs layer : rel_to_layer < dead_frac
  hot vs layer : rel_to_layer > hot_frac
  outlier      : |robust_z| > threshold         (default 5) on the cv series,
                 i.e. a sharp change relative to the SAME wire in adjacent runs

`robust_z` uses a centered rolling median as baseline and 1.4826 x MAD (median
absolute deviation) as the scale, floored at --min-scale (default 0.05 in cv
units): a wire reproducible to 0.4 % should not be called anomalous for a 3 %
wiggle.

`status` carries the verdict, most specific first: `low/dead`, `low vs layer`,
`hot`, `hot vs layer`, `outlier`. Every one of them is a statement about the run
in front of you.

Run quality
-----------
`brightness` is the overall level of a run relative to the campaign, taken from
the layer medians. It plays no part in the cuts. It only marks runs where the
detector was effectively off (--min-gain, --max-gain), whose values are noise
rather than measurements.

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
def add_normalization(df, dead_frac=0.5, hot_frac=2.0, min_healthy=20):
    """Add lay_med, rel_to_layer, own_norm, cv and brightness."""
    df = df.copy()

    # Reference A -- the wire against its NEIGHBOURS in the same run and layer.
    # A ratio taken inside one run, so anything that moves the whole detector
    # together -- beam current, gas, trigger composition -- cancels exactly.
    df["lay_med"] = df.groupby(["run", "layer_number"]).value.transform("median")
    df["rel_to_layer"] = df.value / df.lay_med

    # Reference B -- the wire against ITSELF, in those same units.
    #
    # Reference A alone is not enough: its threshold asks every wire to fall to
    # the same fraction of the layer, so a wire whose healthy level sits above
    # its neighbours can lose most of its output and still clear the cut.
    # `own_norm` is that wire's usual standing within its layer, and `cv`
    # measures how far it has moved from it.
    #
    # `own_norm` is estimated only from the runs where the wire reads like its
    # layer. A median over the wire's whole history would land between its dead
    # and healthy levels for any wire broken for a large share of the campaign,
    # and its GOOD runs would then read about twice that norm and be flagged hot.
    #
    # No run-brightness condition is needed here, because rel_to_layer is
    # already a within-run ratio: a dim run does not bias it.
    healthy = df.rel_to_layer.between(dead_frac, hot_frac)
    agg = (df[healthy].groupby(["layer_number", "wire"])
           .agg(rl0=("rel_to_layer", "median"), n_healthy=("rel_to_layer", "size"))
           .reset_index())
    norm = (df[["layer_number", "wire"]].drop_duplicates()
            .merge(agg, on=["layer_number", "wire"], how="left"))
    norm["n_healthy"] = norm.n_healthy.fillna(0).astype(int)
    norm["own_norm"] = np.where(norm.n_healthy >= min_healthy, norm.rl0, np.nan)
    no_norm = norm[norm.own_norm.isna()]
    if len(no_norm):
        wires = ", ".join(f"L{int(r.layer_number)}W{int(r.wire)}" for _, r in no_norm.iterrows())
        print(f"note: {len(no_norm)} wire(s) never show {min_healthy} runs resembling their "
              f"layer, so no own-norm can be estimated and `cv` is undefined for them; they "
              f"are judged on rel_to_layer alone: {wires}")
    df = df.merge(norm[["layer_number", "wire", "own_norm", "n_healthy"]],
                  on=["layer_number", "wire"], how="left")
    df["cv"] = df.rel_to_layer / df.own_norm

    # How bright the run was overall, relative to the campaign. Used only to
    # mark runs where the detector was effectively off; it plays no part in the
    # cuts, which are all ratios taken inside a single run.
    lm = df.groupby(["run", "layer_number"]).lay_med.first().rename("lm").reset_index()
    lm["typ"] = lm.groupby("layer_number").lm.transform("median")
    df = df.merge((lm.lm / lm.typ).groupby(lm.run).median().rename("brightness"),
                  on="run", how="left")
    return df.sort_values(["layer_number", "wire", "run"]).reset_index(drop=True)


def mark_run_quality(df, min_gain=0.1, max_gain=10.0):
    """Mark runs whose OVERALL level is far from the campaign norm.

    The cuts are ratios taken inside a single run, so a run that is uniformly
    30 % low needs no special handling. A run where the detector was essentially
    off (brightness ~ 0.01) is different: there the values are consistent with
    noise and the surviving structure is statistical. Those runs are kept but
    marked `run_ok = False`, because their bad-channel count says more about the
    run than about the wires.
    """
    df = df.copy()
    rg = df.groupby("run").brightness.first()
    ok = (rg > min_gain) & (rg < max_gain)
    df["run_ok"] = df.run.map(ok)
    n_bad_run = int((~ok).sum())
    if n_bad_run:
        print(f"note: {n_bad_run} of {len(ok)} runs have an overall level outside "
              f"[{min_gain:g}, {max_gain:g}] x normal and are marked run_ok=False")
    return df


def detect_wire(g, window=11, threshold=5.0, dead_frac=0.5, hot_frac=2.0,
                min_scale=0.05):
    """Flag the bad runs of ONE wire, from its time-ordered series.

    Every cut is a statement about a single run. Two independent references:

      cv           -- the wire against its OWN norm, run-scale divided out.
                      Catches a wire that has changed.
      rel_to_layer -- the wire against the other wires of its layer, in the
                      SAME run. Catches a wire that is weak however long it has
                      been weak, which `cv` cannot see because it is normalized
                      to that same wire.

    Returns a copy of g with the analysis columns added. `g` must already have
    `cv` and `rel_to_layer` from add_normalization().
    """
    g = g.sort_values("run").copy()
    cv = g["cv"].to_numpy(dtype=float)

    # 1. local_median: expected cv for this run given its neighbors
    local_med = (g["cv"].rolling(window, center=True, min_periods=3)
                 .median().bfill().ffill())
    # 2. detrended: residual after removing slow drift
    detrended = cv - local_med.to_numpy()
    # 3. MAD -> 4. scale: robust sigma of the residuals, floored at min_scale.
    # A wire with no estimable norm has cv undefined throughout; leave its
    # robust_z undefined too rather than inventing a scale for it.
    if np.isfinite(detrended).any():
        mad = np.nanmedian(np.abs(detrended - np.nanmedian(detrended)))
        scale = max(1.4826 * mad, min_scale)
    else:
        scale = np.nan
    # 5. robust_z: how many robust sigmas from the local baseline
    robust_z = detrended / scale

    rl = g["rel_to_layer"].to_numpy(dtype=float)

    has_cv = np.isfinite(cv)            # false for a wire with no estimable norm
    low_own = has_cv & (cv < dead_frac)  # dropped against its own norm
    hot_own = has_cv & (cv > hot_frac)
    low_lay = rl < dead_frac            # weak against its neighbours this run
    hot_lay = rl > hot_frac
    is_outlier = has_cv & (np.abs(robust_z) > threshold)

    flag = low_own | hot_own | low_lay | hot_lay | is_outlier
    # Precedence, most specific first. `low/dead` means the wire dropped from
    # its own norm; `low vs layer` means it reads normally for itself but its
    # "itself" is well below the rest of the layer.
    status = np.where(low_own, "low/dead",
                      np.where(low_lay, "low vs layer",
                               np.where(hot_own, "hot",
                                        np.where(hot_lay, "hot vs layer",
                                                 np.where(is_outlier, "outlier", "")))))

    g["local_median"] = local_med.to_numpy()
    g["robust_z"] = robust_z
    g["scale"] = scale
    g["flag"] = flag
    g["status"] = status
    return g


def detect_all(df, window=11, threshold=5.0, dead_frac=0.5, hot_frac=2.0,
               min_scale=0.05):
    """Run detect_wire over every wire."""
    parts = [detect_wire(g, window, threshold, dead_frac, hot_frac, min_scale)
             for _, g in df.groupby(["layer_number", "wire"])]
    return pd.concat(parts, ignore_index=True)


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
    ax0.plot(g.run, g.lay_med * g.own_norm, "--", color="darkorange", lw=1.2,
             label="expected level (layer median x its usual standing)")
    ax0.set_ylabel("AHDC ADC value")
    ax0.set_title(f"AHDC ADC - layer {layer} (code {code}), wire {wire}")
    ax0.legend(fontsize=8)

    ax1.plot(g.run, g.cv, "-", color="0.75", lw=1, zorder=1)
    ax1.scatter(g.run, g.cv, s=14, color="seagreen", zorder=2, label="cv (vs its own norm)")
    ax1.plot(g.run, g.local_median, "--", color="green", lw=1, label="local median")
    ax1.axhline(1.0, color="0.4", lw=0.8)
    ax1.axhline(dead_frac, color="red", ls=":", lw=1, label=f"dead floor ({dead_frac:g})")
    ax1.axhline(hot_frac, color="magenta", ls=":", lw=1, label=f"hot ceiling ({hot_frac:g})")
    fl = g[g.flag]
    if not fl.empty:
        ax1.scatter(fl.run, fl.cv, s=70, facecolors="none", edgecolors="red",
                    linewidths=1.6, label="flagged", zorder=3)
    ax1.set_xlabel("run number")
    ax1.set_ylabel("cv = rel_to_layer / its own norm")
    ax1.legend(fontsize=8, ncol=2)

    fig.tight_layout()
    fig.savefig(outpath, dpi=120)
    plt.close(fig)
    print(f"wrote {outpath}  ({len(fl)} flagged of {len(g)} runs)")
    if not fl.empty:
        print(fl[["run", "value", "cv", "rel_to_layer", "robust_z", "status"]]
              .to_string(index=False))


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
    vs_own = bad[bad.status.isin(["low/dead", "hot", "outlier"])]
    vs_lay = bad[bad.status.isin(["low vs layer", "hot vs layer"])]
    axes[1].set_title(f"run-normalized: {len(bad)} bad channel(s) — "
                      f"{len(vs_own)} against their own norm, "
                      f"{len(vs_lay)} against their layer  "
                      f"(low<{dead_frac:g}, hot>{hot_frac:g})")
    if not vs_own.empty:
        axes[1].scatter(vs_own.wire, vs_own.layer_number, s=150, facecolors="none",
                        edgecolors="magenta", linewidths=2.0,
                        label="bad vs its own norm")
    if not vs_lay.empty:
        axes[1].scatter(vs_lay.wire, vs_lay.layer_number, s=150, facecolors="none",
                        edgecolors="black", linewidths=2.0, linestyle="--",
                        label="bad vs its layer")
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

    A wire that is weak in every run sits at cv ~ 1 (normal for itself) but low
    on the grey series, so its marker belongs on the grey one.
    """
    g = res[res.run == run]
    if g.empty:
        return
    has_layer = "rel_to_layer" in g.columns
    fig, axes = plt.subplots(8, 1, figsize=(12, 13.5), sharex=True)
    for i, ax in enumerate(axes, start=1):
        gl = g[g.layer_number == i].sort_values("wire")
        top = max(2.4, (gl.cv.max() * 1.15) if len(gl) else 2.4)
        ax.axhspan(0, dead_frac, color="red", alpha=0.07)
        ax.axhspan(hot_frac, top, color="magenta", alpha=0.07)
        ax.axhline(1.0, color="0.5", lw=0.8)

        if has_layer:
            ax.plot(gl.wire, gl.rel_to_layer, "-", color="0.85", lw=0.7, zorder=1)
            ax.scatter(gl.wire, gl.rel_to_layer, s=8, color="0.62", marker="s",
                       zorder=2, label="rel_to_layer: this wire vs its layer, this run")
        ax.plot(gl.wire, gl.cv, "-", color="0.8", lw=0.8, zorder=3)
        ax.scatter(gl.wire, gl.cv, s=12, color="steelblue", zorder=4,
                   label="cv: this run vs the wire's own norm")

        per_run = gl[gl.status.isin(["low/dead", "hot", "outlier"])]
        chronic = gl[gl.status.isin(["low vs layer", "hot vs layer"])]
        if not per_run.empty:
            ax.scatter(per_run.wire, per_run.cv, s=80, facecolors="none",
                       edgecolors="red", lw=1.6, zorder=5, label="bad vs its own norm")
            for _, r in per_run.iterrows():
                ax.annotate(int(r.wire), (r.wire, r.cv), textcoords="offset points",
                            xytext=(0, 7), ha="center", fontsize=7, color="red")
        if not chronic.empty:
            ax.scatter(chronic.wire, chronic.rel_to_layer, s=80, facecolors="none",
                       edgecolors="black", lw=1.6, linestyle="--", zorder=5,
                       label="bad vs its layer")
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


def run_report(res, run, dead_frac, hot_frac, prefix, margin=1.3):
    bad = plot_run_map(res, run, dead_frac, hot_frac, f"{prefix}_map.png")
    if bad is None:
        return
    plot_run_panels(res, run, dead_frac, hot_frac, f"{prefix}_panels.png")
    cols = ["run", "layer_number", "layer_code", "wire", "value", "lay_med",
            "rel_to_layer", "own_norm", "cv", "robust_z", "status"]
    cols = [c for c in cols if c in bad.columns]
    tab = bad[cols].sort_values(["layer_number", "wire"])
    tab.to_csv(f"{prefix}_bad.csv", index=False)
    print(f"wrote {prefix}_bad.csv")
    if "run_ok" in res.columns and not res[res.run == run].run_ok.iloc[0]:
        print(f"\nWARNING: run {run} reads far from the normal overall level "
              f"(brightness={res[res.run == run].brightness.iloc[0]:.3f}); "
              f"treat its bad-channel list with care")
    print(f"\nBad channels in run {run}: {len(tab)} of {len(res[res.run == run])}")
    fmt = {"value": "{:.4f}".format, "lay_med": "{:.4f}".format,
           "own_norm": "{:.3f}".format, "cv": "{:.3f}".format,
           "rel_to_layer": "{:.2f}".format, "robust_z": "{:.1f}".format}
    if not tab.empty:
        print(tab.to_string(index=False, formatters=fmt))

    # Channels that came close to a cut without firing. A threshold is a line
    # drawn through a continuum, so the entries just the wrong side of it are
    # worth seeing before trusting the count.
    g = res[res.run == run]
    near = g[(~g.flag)
             & (((g.cv > dead_frac) & (g.cv < dead_frac * margin))
                | ((g.rel_to_layer > dead_frac) & (g.rel_to_layer < dead_frac * margin))
                | ((g.cv < hot_frac) & (g.cv > hot_frac / margin))
                | ((g.rel_to_layer < hot_frac) & (g.rel_to_layer > hot_frac / margin)))]
    if not near.empty:
        near = near.sort_values("rel_to_layer")
        print(f"\nNot flagged, but within {100*(margin-1):.0f} % of a cut "
              f"({len(near)} channel(s)):")
        print(near[[c for c in cols if c in near.columns]]
              .sort_values(["layer_number", "wire"])
              .to_string(index=False, formatters=fmt))


# --------------------------------------------------------------------------
# (iv) bad channels per run, across the campaign
# --------------------------------------------------------------------------
def plot_summary(res, outpath, csv_path=None):
    per = (res.groupby("run")
           .agg(n_bad=("flag", "sum"),
                n_low=("status", lambda s: (s == "low/dead").sum()),
                n_low_layer=("status", lambda s: (s == "low vs layer").sum()),
                n_hot=("status", lambda s: (s == "hot").sum()),
                n_hot_layer=("status", lambda s: (s == "hot vs layer").sum()),
                n_outlier=("status", lambda s: (s == "outlier").sum()),
                brightness=("brightness", "first"),
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
    ax0.plot(per.run, per.n_low, lw=1, color="steelblue", label="low vs its own norm")
    ax0.plot(per.run, per.n_hot, lw=1, color="magenta", label="hot vs its own norm")
    ax0.plot(per.run, per.n_low_layer, lw=1.2, color="black", ls="--",
             label="low vs its layer")
    ax0.set_ylabel("bad channels in the run")
    ax0.set_title("AHDC: number of bad channels per run "
                  f"({per.run.min()}-{per.run.max()}, {len(per)} runs, 576 wires)")
    ax0.legend(fontsize=8)
    ax0.grid(alpha=0.3)

    ax1.plot(per.run, per.brightness, lw=1, color="darkorange")
    ax1.set_yscale("log")
    ax1.axhline(1.0, color="0.5", lw=0.8)
    ax1.set_ylabel("run brightness\n(overall ADC level)")
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
    print(big[["run", "n_bad", "d", "brightness"]]
          .rename(columns={"d": "change"})
          .to_string(index=False, formatters={"change": "{:+.0f}".format,
                                              "brightness": "{:.3f}".format}))
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
                        "lay_med", "rel_to_layer", "own_norm", "cv", "local_median",
                        "robust_z", "status"]
            if c in flagged.columns]
    flagged[cols].to_csv(out_csv, index=False)
    print(f"\nwrote {out_csv}: {len(flagged)} flagged (run,wire) entries "
          f"out of {len(res)} total")

    summary = (res.groupby(["layer_number", "wire"])
               .agg(n_runs=("run", "size"),
                    n_flagged=("flag", "sum"),
                    median_value=("value", "median"),
                    median_rel_to_layer=("rel_to_layer", "median"),
                    n_low_layer=("status", lambda s: (s == "low vs layer").sum()))
               .reset_index())
    summary["frac_flagged"] = summary.n_flagged / summary.n_runs
    summary["frac_low_layer"] = summary.n_low_layer / summary.n_runs

    weak = summary[summary.frac_low_layer > 0.5].sort_values("median_rel_to_layer")
    print(f"\nwires below {dead_frac:g} x their layer in more than half of all runs: {len(weak)}")
    if not weak.empty:
        print(weak[["layer_number", "wire", "n_runs", "median_value",
                    "median_rel_to_layer", "frac_low_layer"]]
              .to_string(index=False, formatters={"median_value": "{:.4f}".format,
                                                  "median_rel_to_layer": "{:.2f}".format,
                                                  "frac_low_layer": "{:.2f}".format}))

    worst = summary.sort_values("frac_flagged", ascending=False).head(15)
    print("\nWires bad in the largest fraction of runs (top 15):")
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
    ap.add_argument("--min-healthy", type=int, default=20,
                    help="runs needed to estimate a wire's norm; below this cv is undefined (default 20)")
    ap.add_argument("--margin", type=float, default=1.3,
                    help="also list channels within this factor of a cut (default 1.3)")
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
    ap.add_argument("--min-gain", type=float, default=0.1,
                    help="runs dimmer than this are marked unreliable (default 0.1)")
    ap.add_argument("--max-gain", type=float, default=10.0,
                    help="runs whose overall level is above this are marked unreliable (default 10)")
    args = ap.parse_args()

    df = load(args.input)
    print(f"loaded {len(df)} rows: {df.layer_number.nunique()} layers, "
          f"{df.groupby(['layer_number','wire']).ngroups} wires, "
          f"runs {df.run.min()}-{df.run.max()}")

    df = add_normalization(df, dead_frac=args.dead_frac, hot_frac=args.hot_frac,
                           min_healthy=args.min_healthy)
    g = df.groupby("run").brightness.first()
    print(f"run brightness (overall ADC level relative to the campaign): "
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
                   args.run_prefix or f"run{args.run}", args.margin)
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
