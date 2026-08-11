#!/usr/bin/env python3
"""Figure for the talk: what the outlier cut accepts and what it rejects.

Two wires, the same run window, the same event at run 23055. The shaded band is
the acceptance region, local_median +/- 0.25 -- threshold 5 x scale 0.05, i.e.
the cut expressed in cv units. One wire leaves it, the other does not.
"""
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = "."
sys.path.insert(0, REPO)
import analyze_alert_adc as aa

T, R, MU, DK = "#0E7C86", "#C1553B", "#6B7A83", "#1F2A33"
CUT = 0.25
LO, HI, RUN0 = 22960, 23061, 23055

res = aa.detect_all(aa.mark_run_quality(aa.add_normalization(aa.load(f"{REPO}/all.csv"))))
res = res[res.run_ok.astype(bool)]

fig, axes = plt.subplots(2, 1, figsize=(11, 5.8), sharex=True)
panels = [
    (1, 26, R, "FLAGGED",     (0.40, 1.42), 0.60),
    (5, 41, T, "not flagged", (0.66, 1.58), 1.44),
]
for ax, (L, W, col, tag, ylim, ty) in zip(axes, panels):
    g = res[(res.layer_number == L) & (res.wire == W)
            & res.run.between(LO, HI)].sort_values("run")
    ax.fill_between(g.run, g.local_median - CUT, g.local_median + CUT,
                    color=T, alpha=0.12, lw=0,
                    label="accepted: within 0.25 of the local median")
    ax.plot(g.run, g.local_median, "--", color=MU, lw=1.1,
            label="local median (11 runs)")
    ax.plot(g.run, g.cv, "-", color="0.82", lw=0.8, zorder=2)
    ax.scatter(g.run, g.cv, s=16, color="steelblue", zorder=3, label="cv")

    q = g[g.run == RUN0].iloc[0]
    dev = q.cv - q.local_median
    ax.scatter([RUN0], [q.cv], s=170, facecolors="none", edgecolors=col,
               linewidths=2.3, zorder=4)
    ax.annotate(f"{dev:+.3f}   {tag}",
                xy=(RUN0, q.cv), xytext=(22993, ty),
                fontsize=11, color=col, weight="bold", va="center",
                arrowprops=dict(arrowstyle="->", color=col, lw=1.4,
                                connectionstyle="arc3,rad=-0.12"))
    ax.set_ylabel("cv")
    ax.set_ylim(*ylim)
    ax.set_xlim(LO, HI)
    ax.grid(alpha=0.25)
    ax.text(0.006, 0.93, f"layer {L}, wire {W}", transform=ax.transAxes,
            fontsize=11, weight="bold", color=DK, va="top")

h, lab = axes[0].get_legend_handles_labels()
fig.legend(h, lab, fontsize=9.5, ncol=3, loc="lower center",
           bbox_to_anchor=(0.5, 0.0), frameon=False)
axes[1].set_xlabel("run number")
fig.suptitle("The outlier cut: both wires move in run 23055 — only one moves far enough",
             fontsize=13, weight="bold", color=DK, x=0.125, ha="left")
fig.tight_layout(rect=[0, 0.055, 1, 0.955])
out = f"{REPO}/outlier_example.png"
fig.savefig(out, dpi=140)
print("wrote", out)

for L, W, *_ in panels:
    q = res[(res.layer_number == L) & (res.wire == W) & (res.run == RUN0)].iloc[0]
    d = q.cv - q.local_median
    print(f"  L{L}W{W} run {RUN0}: cv={q.cv:.4f}  local_median={q.local_median:.4f}  "
          f"dev={d:+.4f}  |dev|>{CUT}? {abs(d) > CUT}  status={q.status or '-'}")
