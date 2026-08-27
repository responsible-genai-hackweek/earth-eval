"""Build the final tables and figures from the daily checkpoints.

Reads only checkpoints - no network. Everything it writes is derived from the
domain-mean series, so the whole report can be rebuilt without refetching.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import numpy as np

from .figures import (
    DRY_COLOUR,
    WET_COLOUR,
    anomaly_bars,
    collect_pdf,
    model_agreement_scatter,
    spaghetti,
    validation_series,
)
from .snowseason import rank_ascending
from .summarize import (
    load_depth_series,
    load_swe_series,
    model_agreement,
    ranked,
    summarize_model,
)

__all__ = ["build_report", "write_findings"]

#: Fewest water years that make a rank worth stating. Below this the record is
#: reported as a value with its period, and no rank: "lowest of 3" invites a
#: reader to hear "record low", which it is not.
MIN_YEARS_FOR_RANK = 10

FIELDS = (
    ("april_first_swe_mm", "1 April SWE", "mm w.e."),
    ("april_first_depth_m", "1 April snow depth", "m"),
    ("peak_swe_mm", "peak SWE", "mm w.e."),
    ("season_mean_swe_mm", "season-mean SWE", "mm w.e."),
)

TABLE_COLUMNS = (
    "model", "water_year", "n_days",
    "april_first_swe_mm", "april_first_swe_rank", "april_first_swe_anomaly",
    "april_first_depth_m", "april_first_depth_rank",
    "peak_swe_mm", "peak_day", "peak_swe_rank",
    "season_mean_swe_mm", "season_mean_swe_rank",
    "melt_out_date",
)


def _write_atomic(path: Path, header, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp{os.getpid()}")
    with tmp.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def build_report(
    checkpoints: Path,
    results: Path,
    water_years: list[int],
    feature_years: tuple[int, ...] = (2023, 2026),
    complete_only: bool = True,
) -> dict:
    """Write the statistics table and every figure. Returns a summary dict."""
    with collect_pdf(results / "colorado_snowpack_figures.pdf"):
        return _build(checkpoints, results, water_years, feature_years, complete_only)


def _build(checkpoints, results, water_years, feature_years, complete_only) -> dict:
    stats = {
        model: summarize_model(checkpoints, model, water_years)
        for model in ("era5", "merra2")
    }
    if complete_only:
        # A part-built water year would rank spuriously low on peak and season
        # mean, so only years with a full accumulation and melt season count.
        stats = {
            model: [s for s in rows if s.n_days >= 270] for model, rows in stats.items()
        }

    rows = []
    for model, entries in stats.items():
        tables = {name: ranked(entries, name) for name, _, _ in FIELDS}
        for s in entries:
            rows.append([
                model, s.water_year, s.n_days,
                f"{s.april_first_swe_mm:.4f}",
                _rank(tables["april_first_swe_mm"], s.water_year),
                f"{tables['april_first_swe_mm'][s.water_year][2]:.3f}",
                f"{s.april_first_depth_m:.5f}",
                _rank(tables["april_first_depth_m"], s.water_year),
                f"{s.peak_swe_mm:.4f}",
                s.peak_day.isoformat() if s.peak_day else "",
                _rank(tables["peak_swe_mm"], s.water_year),
                f"{s.season_mean_swe_mm:.4f}",
                _rank(tables["season_mean_swe_mm"], s.water_year),
                s.melt_out.isoformat() if s.melt_out else "",
            ])
    rows.sort(key=lambda r: (r[0], r[1]))
    _write_atomic(results / "water_year_statistics.csv", TABLE_COLUMNS, rows)

    era5_years = [s.water_year for s in stats["era5"]]
    summary: dict = {"water_years": era5_years, "figures": []}

    if era5_years:
        swe = load_swe_series(checkpoints, "era5", era5_years)
        depth = load_depth_series(checkpoints, "era5", era5_years)
        span = f"WY{min(era5_years)}–WY{max(era5_years)}"

        summary["figures"].append(str(anomaly_bars(
            era5_years,
            np.array([s.april_first_swe_mm for s in stats["era5"]]),
            title="Colorado 1 April snow water equivalent, ERA5",
            subtitle=f"Domain-mean over 72 MERRA-2 cells, {span}. "
                     "Colour shows departure from the record mean.",
            unit="mm w.e.",
            highlight=feature_years,
            path=results / "april_first_swe_by_water_year.png",
        )))

        summary["figures"].append(str(anomaly_bars(
            era5_years,
            np.array([s.april_first_depth_m for s in stats["era5"]]),
            title="Colorado 1 April snow depth, ERA5",
            subtitle=f"Grid-cell mean geometric depth, {span}. "
                     "A sharper signal than SWE: the low year's snow was also less dense.",
            unit="m",
            highlight=feature_years,
            path=results / "april_first_depth_by_water_year.png",
        )))

        # Every year as its own line, rather than a percentile band. A band is
        # computed per day-of-year and traces a path no real year followed; each
        # curve here actually happened, and the shape of a year is part of the
        # result.
        peaks = np.array([s.peak_swe_mm for s in stats["era5"]])
        lowest = [era5_years[i] for i in np.argsort(rank_ascending(peaks))[:3]]
        near_misses = tuple(wy for wy in lowest if wy not in feature_years)
        summary["near_miss_years"] = near_misses
        summary["figures"].append(str(spaghetti(
            swe, era5_years,
            highlight={feature_years[0]: WET_COLOUR, feature_years[-1]: DRY_COLOUR},
            context=near_misses,
            title=f"Every Colorado water year since {min(era5_years)}, ERA5",
            subtitle="Daily domain-mean snow water equivalent. Each thin line is "
                     "one water year; overlap shows where years agree.",
            unit="mm w.e.",
            path=results / "spaghetti_swe.png",
        )))

        summary["figures"].append(str(spaghetti(
            depth, era5_years,
            highlight={feature_years[0]: WET_COLOUR, feature_years[-1]: DRY_COLOUR},
            context=near_misses,
            title=f"The same years, as snow depth",
            subtitle="Grid-cell mean geometric depth. The low year separates further "
                     "here than in water equivalent, because its snow was also "
                     "less dense.",
            unit="m",
            path=results / "spaghetti_depth.png",
        )))

    shared = sorted(
        {s.water_year for s in stats["era5"]} & {s.water_year for s in stats["merra2"]}
    )
    if len(shared) >= MIN_YEARS_FOR_RANK:
        rho, p, n = model_agreement(
            [s for s in stats["era5"] if s.water_year in shared],
            [s for s in stats["merra2"] if s.water_year in shared],
            "peak_swe_mm",
        )
        summary["agreement_peak_swe"] = {"rho": rho, "p": p, "n": n}
        summary["figures"].append(str(model_agreement_scatter(
            shared,
            np.array([s.peak_swe_mm for s in stats["era5"] if s.water_year in shared]),
            np.array([s.peak_swe_mm for s in stats["merra2"] if s.water_year in shared]),
            rho=rho, p_value=p,
            title="Do the two reanalyses rank the years the same way?",
            subtitle="Peak SWE rank, ERA5 versus MERRA-2. Ranks, not values: the "
                     "models' magnitude ratio itself varies with snowpack depth.",
            highlight=feature_years,
            path=results / "model_rank_agreement.png",
        )))

    validation = _validation_figure(checkpoints, results)
    if validation:
        summary["figures"].append(validation)

    for name, label, unit in FIELDS:
        table = ranked(stats["era5"], name)
        for wy in feature_years:
            if wy in table:
                value, rank, anomaly = table[wy]
                summary[f"era5_{name}_WY{wy}"] = {
                    "value": value, "rank": rank, "of": len(table),
                    "anomaly_sd": anomaly, "unit": unit, "label": label,
                }
    return summary


def write_findings(checkpoints: Path, results: Path, water_years: list[int],
                   feature_years: tuple[int, ...] = (2023, 2026)) -> Path:
    """Write the headline numbers as markdown, generated rather than transcribed.

    Every figure quoted in prose should come from here, so a number cannot drift
    from the data it claims to describe.
    """
    stats = {
        model: [s for s in summarize_model(checkpoints, model, water_years)
                if s.n_days >= 270]
        for model in ("era5", "merra2")
    }
    lines: list[str] = [
        "# Findings",
        "",
        "Generated from the daily checkpoints. Do not edit by hand.",
        "",
        "Domain: 72 native MERRA-2 cells over Colorado, 109-104W and 37-41N.",
        "",
    ]

    # The two models cover different periods, so each rank is stated against its
    # own record. A rank is meaningless without the distribution it is a rank in.
    for model, entries in stats.items():
        if not entries:
            continue
        years = [s.water_year for s in entries]
        label = "ERA5" if model == "era5" else "MERRA-2"
        contiguous = len(years) == max(years) - min(years) + 1
        lines.append(
            f"- **{label}**: WY{min(years)}-WY{max(years)}, {len(years)} complete "
            f"water years{'' if contiguous else ' (not contiguous)'}."
        )
    lines.append("")

    for model, entries in stats.items():
        if not entries:
            continue
        label = "ERA5" if model == "era5" else "MERRA-2"
        lines += [f"## {label}", ""]
        years = [s.water_year for s in entries]
        lines += [
            f"Ranks below are within WY{min(years)}-WY{max(years)}."
            if len(years) >= MIN_YEARS_FOR_RANK
            else f"Only WY{min(years)}-WY{max(years)} available so far; "
                 "values are reported without ranks.",
            "",
        ]
        for field, name, unit in FIELDS:
            if model == "merra2" and field == "april_first_swe_mm":
                lines += [
                    f"- **{name}** — omitted deliberately. MERRA-2 melts this "
                    "domain out almost entirely by April in most years, so the "
                    "ranking within that band is noise rather than a result.",
                ]
                continue
            table = ranked(entries, field)
            n = len(table)
            for wy in feature_years:
                if wy not in table:
                    continue
                value, rank, anomaly = table[wy]
                if not np.isfinite(value):
                    continue
                if n < MIN_YEARS_FOR_RANK:
                    lines.append(
                        f"- **{name}, WY{wy}**: {value:.4g} {unit} — not ranked; "
                        f"only {n} water year{'s' if n != 1 else ''} available, "
                        f"too few to place it in a distribution."
                    )
                    continue
                end = "lowest" if rank <= n / 2 else "highest"
                shown = int(rank if rank <= n / 2 else n - rank + 1)
                suffix = {1: "st", 2: "nd", 3: "rd"}.get(
                    shown if shown % 100 not in (11, 12, 13) else 0, "th"
                )
                phrase = f"{end} of {n}" if shown == 1 else f"{shown}{suffix} {end} of {n}"
                mean = float(np.nanmean([getattr(s, field) for s in entries]))
                pct = 100.0 * value / mean if mean else float("nan")
                anomaly_text = f" ({anomaly:+.2f} sd)" if np.isfinite(anomaly) else ""
                lines.append(
                    f"- **{name}, WY{wy}**: {value:.4g} {unit} — {phrase}, "
                    f"{pct:.0f}% of the record mean{anomaly_text}."
                )
        lines.append("")

    shared = sorted({s.water_year for s in stats["era5"]}
                    & {s.water_year for s in stats["merra2"]})
    if len(shared) >= MIN_YEARS_FOR_RANK:
        lines += [
            "## Do the two reanalyses agree?",
            "",
            f"Over the {len(shared)} water years both models cover "
            f"(WY{min(shared)}-WY{max(shared)}).",
            "",
        ]
        for field, name, _ in FIELDS:
            if field == "april_first_swe_mm":
                continue
            rho, pv, n = model_agreement(
                [s for s in stats["era5"] if s.water_year in shared],
                [s for s in stats["merra2"] if s.water_year in shared],
                field,
            )
            if np.isfinite(rho):
                shown_p = "< 1e-16" if pv == 0 else f"= {pv:.1e}"
                lines.append(f"- **{name}** rank correlation: rho = {rho:.3f}, p {shown_p}, n = {n}")
        lines += [
            "",
            "Rank, not magnitude. The two models' magnitude ratio varies with how "
            "thin the snowpack is, so a ratio quoted without naming the product is "
            "not a fact about Colorado.",
            "",
        ]

    lines += _validation_findings(checkpoints, results)

    path = results / "FINDINGS.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def _validation_findings(checkpoints: Path, results: Path) -> list[str]:
    """Compare each model's snow-cover fraction with the satellite reference."""
    from datetime import date as _date

    reference_path = results / "wy2023_modscag_domain_fsca.csv"
    if not reference_path.exists():
        return []
    with reference_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    reference = {
        _date.fromisoformat(r["date"]): float(r["domain_fsca"])
        for r in rows
        if r.get("status") == "ok" and r["domain_fsca"]
    }
    usable = sum(1 for r in rows if r.get("status") == "ok")
    absent = sum(1 for r in rows if r.get("status") == "no_reference")
    failed = sum(1 for r in rows if r.get("status") == "fetch_failed")

    out = [
        "## Satellite validation, WY2023",
        "",
        f"{usable} of {len(rows)} days carry a usable MODSCAG reference; "
        f"{absent} have none in the archive and {failed} failed to fetch.",
        "",
    ]
    for model, column, label in (("era5", "fsca", "ERA5"), ("merra2", "frsno", "MERRA-2")):
        path = checkpoints / f"{model}_WY2023.csv"
        if not path.exists():
            continue
        pairs = []
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                day = _date.fromisoformat(row["date"])
                raw = row.get(column) or ""
                if day in reference and raw:
                    pairs.append((float(raw), reference[day]))
        if len(pairs) < 30:
            continue
        model_values = np.array([a for a, _ in pairs])
        observed = np.array([b for _, b in pairs])
        bias = float(np.mean(model_values - observed))
        mae = float(np.mean(np.abs(model_values - observed)))
        note = (
            " ERA5 publishes no snow-cover fraction, so this is diagnosed from the "
            "IFS scheme, which saturates at 0.10 m of depth; a high bias is a "
            "property of that diagnostic as much as of the model."
            if model == "era5" else ""
        )
        out.append(
            f"- **{label} minus MODSCAG** snow-cover fraction, {len(pairs)} paired "
            f"days: mean bias {bias:+.3f}, MAE {mae:.3f}.{note}"
        )

    out += ["", "Melt-out, the last day snow cover stays above 0.10:", ""]
    for label, days_values in _melt_out_inputs(checkpoints, results).items():
        day = _last_day_above(days_values, 0.10)
        out.append(f"- **{label}**: {day.isoformat() if day else 'never reached'}")
    out.append("")
    return out


def _melt_out_inputs(checkpoints: Path, results: Path) -> dict:
    """Daily snow-cover series for the reference and each model, WY2023."""
    from datetime import date as _date

    series: dict[str, list[tuple]] = {}
    with (results / "wy2023_modscag_domain_fsca.csv").open(newline="") as handle:
        series["MODSCAG"] = [
            (_date.fromisoformat(r["date"]), float(r["domain_fsca"]))
            for r in csv.DictReader(handle)
            if r.get("status") == "ok" and r["domain_fsca"]
        ]
    for model, column, label in (("era5", "fsca", "ERA5"), ("merra2", "frsno", "MERRA-2")):
        path = checkpoints / f"{model}_WY2023.csv"
        if not path.exists():
            continue
        with path.open(newline="") as handle:
            series[label] = [
                (_date.fromisoformat(r["date"]), float(r[column]))
                for r in csv.DictReader(handle)
                if r.get(column)
            ]
    return series


def _last_day_above(pairs, threshold: float):
    """Last date whose value exceeds ``threshold``, scanning from the end."""
    for day, value in sorted(pairs, reverse=True):
        if np.isfinite(value) and value > threshold:
            return day
    return None


def _validation_figure(checkpoints: Path, results: Path) -> str | None:
    """Satellite fSCA against both models for the validation water year."""
    reference_path = results / "wy2023_modscag_domain_fsca.csv"
    if not reference_path.exists():
        return None
    from datetime import date as _date

    with reference_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    days = [_date.fromisoformat(r["date"]) for r in rows]
    index = {d: i for i, d in enumerate(days)}
    series = {
        "MODSCAG": np.array(
            [float(r["domain_fsca"]) if r["domain_fsca"] else np.nan for r in rows]
        )
    }

    for model, column in (("era5", "fsca"), ("merra2", "frsno")):
        path = checkpoints / f"{model}_WY2023.csv"
        if not path.exists():
            continue
        values = np.full(len(days), np.nan)
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                day = _date.fromisoformat(row["date"])
                raw = row.get(column) or ""
                if day in index and raw:
                    values[index[day]] = float(raw)
        if np.any(np.isfinite(values)):
            series["ERA5" if model == "era5" else "MERRA-2"] = values

    if len(series) < 2:
        return None
    return str(validation_series(
        days, series, wy=2023,
        title="Satellite validation, water year 2023",
        subtitle="Domain-mean fractional snow cover. MODSCAG is the observed "
                 "reference; ERA5's fraction is diagnosed, not archived.",
        path=results / "wy2023_validation_fsca.png",
    ))


def _rank(table, wy) -> str:
    value = table.get(wy, (np.nan, np.nan, np.nan))[1]
    return "" if not np.isfinite(value) else str(int(value))
