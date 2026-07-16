"""
metrics.report — build per-metric comparison tables for Chapter 5.

Takes analyzed runs (from metrics.analyzer) and renders, for each metric,
a separate architecture x attack table — the standard layout for a
scientific comparison (one metric per table, not one giant grid). Each
table is emitted in three formats:

  * CSV      — machine-readable source for Streamlit / archival
  * Markdown — paste-ready for the dissertation text
  * console  — quick aligned view after a run

Tables produced
---------------
  Table  MTTD       rows = attacks, cols = architectures
  Table  MTTR       rows = attacks, cols = architectures
  Table  Impact     rows = attacks, cols = architectures
  Table  Detection  rows = attacks, cols = architectures
  Table  FP (base)  rows = architectures (baseline runs only)

Cell symbols (documented in the legend so a reviewer can read them):
  —      no runs for this cell (not measured / not yet collected)
  n/a    metric not applicable here (e.g. MTTR where the architecture,
         by design, never attempts recovery — arch A/B local isolation)
  n/d    runs exist but the attack was never detected (no MTTD)
  fail   recovery was attempted in every applicable run but none
         succeeded (no MTTR, but this is a real negative result, not n/a)

Numeric cells show `mean±std (k)` where k is the sample size behind that
cell; with a single sample only the mean is shown (std undefined).

CLI
---
    python -m metrics.report <runs_root> [--out <dir>]

Reads every run_*/ under <runs_root>, writes CSV + tables.md into <dir>
(default: <runs_root>/report/), and prints the console tables.
"""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Callable, Optional

from metrics.analyzer import RunMetrics, analyze_runs, find_run_dirs

# --- fixed axes -------------------------------------------------------------

ARCH_ORDER: list[str] = ["A", "B", "C"]
ATTACK_ORDER: list[str] = [
    "gps_spoofing",
    "comm_disruption",
    "command_injection",
    "detector_takeout+gps_spoofing",
    "monitor_takeout+gps_spoofing",
]
BASELINE_ATTACK = "none"

ATTACK_LABELS: dict[str, str] = {
    "gps_spoofing": "GPS spoofing",
    "comm_disruption": "Comm disruption",
    "command_injection": "Command injection",
    "detector_takeout+gps_spoofing": "GPS spoofing + local detector takeout",
    "monitor_takeout+gps_spoofing": "GPS spoofing + neighbour monitor host takeout",
    "none": "Baseline",
}

# Cell symbols
NO_DATA = "\u2014"        # em dash: no runs
NOT_APPLICABLE = "n/a"    # metric structurally not applicable
NOT_DETECTED = "n/d"      # runs exist, nothing detected
RECOVERY_FAIL = "fail"    # recovery attempted everywhere, none succeeded


# --- grouping ---------------------------------------------------------------


def group_runs(
    runs: list[RunMetrics],
) -> dict[tuple[str, str], list[RunMetrics]]:
    """Group valid runs by (architecture, attack_type)."""
    groups: dict[tuple[str, str], list[RunMetrics]] = defaultdict(list)
    for r in runs:
        if r.error is not None:
            continue
        groups[(r.architecture, r.attack_type)].append(r)
    return groups


# --- numeric formatting -----------------------------------------------------


def _fmt_mean_std(values: list[float], nd: int = 3) -> Optional[str]:
    """mean±std (k) — or mean (1) with a single sample. None if empty."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    m = statistics.mean(vals)
    if len(vals) >= 2:
        s = statistics.stdev(vals)
        return f"{m:.{nd}f}\u00b1{s:.{nd}f} ({len(vals)})"
    return f"{m:.{nd}f} ({len(vals)})"


# --- per-metric cell builders ----------------------------------------------
# Each takes the list of runs for one (arch, attack) cell and returns the
# display string. Empty list -> caller passes [] and we return NO_DATA.


def cell_mttd(runs: list[RunMetrics]) -> str:
    if not runs:
        return NO_DATA
    mttds = [r.mttd_sec for r in runs if r.mttd_sec is not None]
    if not mttds:
        return NOT_DETECTED
    return _fmt_mean_std(mttds) or NOT_DETECTED


def cell_mttr(runs: list[RunMetrics]) -> str:
    if not runs:
        return NO_DATA
    applicable = [
        r for r in runs if r.recovery_status in ("success", "failed")
    ]
    if not applicable:
        # No run in this cell ever requested recovery -> by-design n/a
        # (arch A/B local isolation, or an attack with no recovery policy).
        return NOT_APPLICABLE
    mttrs = [r.mttr_sec for r in runs if r.mttr_sec is not None]
    if not mttrs:
        return f"{RECOVERY_FAIL} (0/{len(applicable)})"
    formatted = _fmt_mean_std(mttrs)
    return formatted or NOT_APPLICABLE


def cell_impact(runs: list[RunMetrics]) -> str:
    if not runs:
        return NO_DATA
    vals = [float(r.impact_scope) for r in runs]
    return _fmt_mean_std(vals, nd=2) or NO_DATA


def cell_detection(runs: list[RunMetrics]) -> str:
    if not runs:
        return NO_DATA
    det = sum(1 for r in runs if r.detected)
    n = len(runs)
    return f"{det}/{n} ({det / n * 100:.0f}%)"


def cell_fp(runs: list[RunMetrics]) -> str:
    if not runs:
        return NO_DATA
    fp = sum(1 for r in runs if r.has_false_positive)
    n = len(runs)
    return f"{fp}/{n} ({fp / n * 100:.0f}%)"


# --- table assembly ---------------------------------------------------------


class Table:
    def __init__(self, title: str, header: list[str], rows: list[list[str]]):
        self.title = title
        self.header = header
        self.rows = rows


def build_attack_table(
    title: str,
    groups: dict[tuple[str, str], list[RunMetrics]],
    cell_fn: Callable[[list[RunMetrics]], str],
) -> Table:
    """rows = attacks, cols = architectures."""
    header = ["Attack"] + ARCH_ORDER
    rows: list[list[str]] = []
    for atk in ATTACK_ORDER:
        row = [ATTACK_LABELS.get(atk, atk)]
        for arch in ARCH_ORDER:
            row.append(cell_fn(groups.get((arch, atk), [])))
        rows.append(row)
    return Table(title, header, rows)


def build_fp_table(
    groups: dict[tuple[str, str], list[RunMetrics]],
) -> Table:
    """Baseline-only false-positive table. rows = architectures."""
    header = ["Architecture", "False-positive rate (baseline)"]
    rows: list[list[str]] = []
    for arch in ARCH_ORDER:
        rows.append([arch, cell_fp(groups.get((arch, BASELINE_ATTACK), []))])
    return Table("False-positive rate (baseline runs)", header, rows)


def build_all_tables(
    groups: dict[tuple[str, str], list[RunMetrics]],
) -> list[Table]:
    return [
        build_attack_table("MTTD, s (mean\u00b1std)", groups, cell_mttd),
        build_attack_table("MTTR, s (mean\u00b1std)", groups, cell_mttr),
        build_attack_table("Impact scope (mean\u00b1std)", groups, cell_impact),
        build_attack_table("Detection rate", groups, cell_detection),
        build_fp_table(groups),
    ]


# --- renderers --------------------------------------------------------------


def render_markdown(table: Table) -> str:
    lines = [f"### {table.title}", ""]
    lines.append("| " + " | ".join(table.header) + " |")
    lines.append("| " + " | ".join("---" for _ in table.header) + " |")
    for row in table.rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_console(table: Table) -> str:
    cols = list(zip(*([table.header] + table.rows))) if table.rows else [
        [h] for h in table.header
    ]
    widths = [max(len(str(c)) for c in col) for col in cols]

    def fmt_row(cells: list[str]) -> str:
        return "  ".join(
            str(c).ljust(widths[i]) for i, c in enumerate(cells)
        )

    sep = "  ".join("-" * w for w in widths)
    out = [table.title, fmt_row(table.header), sep]
    out += [fmt_row(r) for r in table.rows]
    return "\n".join(out)


def write_csv(table: Table, path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(table.header)
        w.writerows(table.rows)


LEGEND = (
    "Legend: mean\u00b1std (k) with k = sample size; single sample shows "
    "mean only.  \u2014 = no runs;  n/a = not applicable (architecture does "
    "not attempt recovery by design);  n/d = runs exist but attack never "
    "detected;  fail (0/k) = recovery attempted in all k applicable runs, "
    "none succeeded."
)


def _slug(title: str) -> str:
    keep = "".join(c if c.isalnum() else "_" for c in title.lower())
    return "_".join(p for p in keep.split("_") if p)[:40]


def write_report(
    runs: list[RunMetrics], out_dir: Path
) -> tuple[list[Table], Path]:
    """Build all tables, write CSVs + a combined tables.md. Returns
    (tables, markdown_path)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    groups = group_runs(runs)
    tables = build_all_tables(groups)

    for t in tables:
        write_csv(t, out_dir / f"table_{_slug(t.title)}.csv")

    md_parts = ["# Experiment results — comparison tables", "", LEGEND, ""]
    for t in tables:
        md_parts.append(render_markdown(t))
        md_parts.append("")
    md_path = out_dir / "tables.md"
    md_path.write_text("\n".join(md_parts))
    return tables, md_path


# --- CLI --------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Build Chapter-5 comparison tables from experiment runs."
    )
    ap.add_argument(
        "runs_root",
        type=Path,
        help="Directory containing run_*/ subdirectories.",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: <runs_root>/report/).",
    )
    args = ap.parse_args(argv)

    out_dir = args.out or (args.runs_root / "report")
    run_dirs = find_run_dirs(args.runs_root)
    if not run_dirs:
        print(f"No run_*/ directories with merged.jsonl under {args.runs_root}")
        return 1

    runs = analyze_runs(run_dirs)
    n_valid = sum(1 for r in runs if r.error is None)
    n_err = len(runs) - n_valid

    tables, md_path = write_report(runs, out_dir)

    for t in tables:
        print()
        print(render_console(t))
    print()
    print(LEGEND)
    print()
    print(
        f"Analyzed {len(runs)} runs ({n_valid} valid, {n_err} with errors). "
        f"CSV + Markdown written to {out_dir}/  (tables.md: {md_path})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
