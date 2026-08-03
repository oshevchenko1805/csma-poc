"""
patch_plots_overplot.py — make overlapping points countable.

Two figures currently under-report their own sample size because
identical values land on identical pixels:

  * fig5, right panel: architecture A has five false-positive runs but
    shows three markers (values 1, 2, 3 with duplicates hidden). A reader
    counts markers and gets the wrong n.
  * fig4, command_injection panel: all fifteen C runs sit at (0, 0) as a
    single blob, so the strongest result in that panel looks like one
    observation.

Fixes, both deterministic — no random jitter, so the figure is identical
on every run and a reader can reproduce it exactly:

  * fig5 spreads duplicates symmetrically around the category centre by
    their index within the duplicate group;
  * fig4 annotates each panel with n per architecture.

Idempotent: re-running is a no-op.

    python patch_plots_overplot.py
"""

import io
import os
import sys

TARGET = os.path.join("metrics", "plots.py")

ANCHOR_BURSTS = """    top = 1
    for i, arch in enumerate(ARCHS):
        vals = bursts.get(arch, [])
        if vals:
            top = max(top, max(vals))
        axes[1].scatter([i] * len(vals), vals, s=34, marker=MARKER[arch],
                        facecolor=FILL[arch], edgecolor="black", linewidth=0.5)
"""

REPLACE_BURSTS = """    top = 1
    for i, arch in enumerate(ARCHS):
        vals = sorted(bursts.get(arch, []))
        if vals:
            top = max(top, max(vals))
        # Spread duplicates around the category centre so every run is
        # countable: identical values otherwise land on identical pixels
        # and the panel under-reports its own n. Deterministic, so the
        # figure is byte-identical on every regeneration.
        seen = collections.Counter()
        xs = []
        for v in vals:
            seen[v] += 1
            xs.append(i + 0.055 * ((seen[v] - 1) // 2 + 1)
                      * (1 if seen[v] % 2 == 0 else -1)
                      * (0 if seen[v] == 1 else 1))
        axes[1].scatter(xs, vals, s=34, marker=MARKER[arch],
                        facecolor=FILL[arch], edgecolor="black", linewidth=0.5)
        axes[1].annotate("n=%d" % len(vals), xy=(i, top + 0.55),
                         ha="center", fontsize=8)
"""

ANCHOR_TRADEOFF = """        ax.set_title(ATTACK_LABEL.get(attack, attack).replace("\\n", " "),
                     fontsize=9)
"""

REPLACE_TRADEOFF = """        ax.set_title(ATTACK_LABEL.get(attack, attack).replace("\\n", " "),
                     fontsize=9)
        # Sample size per architecture, stated rather than counted off the
        # markers: in command_injection every C run sits at (0, 0) and the
        # cluster is a single blob.
        counts = [
            "%s=%d" % (arch, sum(
                1 for r in rows_v
                if r["architecture"] == arch and r["attack"] == attack
                and num(r, "geometry_excess_m") is not None
                and num(r, "phase_excess_m") is not None))
            for arch in ARCHS
        ]
        ax.annotate("  ".join(counts), xy=(0.02, 0.02),
                    xycoords="axes fraction", fontsize=7.5, color="0.25")
"""

GUARD = "Spread duplicates around the category centre"


def main() -> None:
    if not os.path.exists(TARGET):
        sys.exit("!! %s not found — run from the repo root" % TARGET)

    with io.open(TARGET, encoding="utf-8") as fh:
        text = fh.read()

    if GUARD in text:
        print("already patched — nothing to do")
        return

    for name, anchor in (("bursts", ANCHOR_BURSTS), ("tradeoff", ANCHOR_TRADEOFF)):
        count = text.count(anchor)
        assert count == 1, "%s anchor matched %d times, expected 1" % (name, count)

    with io.open(TARGET + ".bak", "w", encoding="utf-8") as fh:
        fh.write(text)

    text = text.replace(ANCHOR_BURSTS, REPLACE_BURSTS)
    text = text.replace(ANCHOR_TRADEOFF, REPLACE_TRADEOFF)

    with io.open(TARGET, "w", encoding="utf-8") as fh:
        fh.write(text)

    print("patched %s (backup at %s.bak)" % (TARGET, TARGET))
    print("regenerate: python -m metrics.plots runs_campaign/campaign_master.csv "
          "--outdir figures")


if __name__ == "__main__":
    main()
