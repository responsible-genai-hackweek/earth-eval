"""Season shape against SNOTEL: fetch, measure, and render.

Rebuilds everything in ``plan/SEASON_SHAPE_PLAN.md`` from the SNOTEL cache and
the existing per-cell checkpoints. Only SNOTEL needs the network, and only once.

Two routes through the model side are computed and both are reported, because
the verdict must not depend on how the model was aggregated:

* the 8,000-14,500 ft **band series**, the familiar domain-mean route; and
* **per cell**, median across band cells, which is the same operation SNOTEL
  gets and is therefore the fairer one — a band mean melts out later than a
  typical member inside it.
"""

from __future__ import annotations

import csv
import glob
import json
import os
from datetime import date
from pathlib import Path

import numpy as np

from . import season_shape_figures as ssf
from . import snotel, terrain
from .calendars import water_year
from .seasonshape import (
    METRICS,
    adjust_to_elevation,
    elevation_gradient,
    normalised_composite,
    season_shape,
)

__all__ = ["build_season_shape", "snotel_station_years"]

#: Coverage is gated on the snow season, not the calendar year. The archive ends
#: in August, so a full-water-year day count silently discards WY2026 - the year
#: the parent analysis is about.
SEASON_DAYS = (0, 303)          # 1 October - 31 July
SEASON_COVERAGE = 0.95
#: Membership gates, not metrics. They decide which members have a season worth
#: describing; they never appear in a reported day.
SNOTEL_FLOOR_IN = 2.0
MODEL_FLOOR_MM = 5.0
#: A station needs a real climatology before it may inform the elevation fit.
MIN_YEARS_FOR_GRADIENT = 20
CHECKPOINT_STEM = "water_year_1981_2026"
MODELS = (("era5", "ERA5", "snow_depth", 1000.0),      # ERA5 `sd` is SWE in metres
          ("merra2", "MERRA-2", "SNOMAS", 1.0))        # already kg m-2


def _day_of_water_year(day: date) -> int:
    return (day - date(water_year(day) - 1, 10, 1)).days


def snotel_station_years(cache: Path) -> list[dict]:
    """Shape metrics per station-year, for every station-year passing the gate."""
    stations = {s["triplet"]: s for s in json.loads((cache / "stations.json").read_text())}
    rows: list[dict] = []
    low, high = SEASON_DAYS
    for path in sorted(cache.glob("*_CO_SNTL.csv")):
        triplet = path.stem.replace("_", ":")
        days, values = snotel.load_station(path)
        if not days:
            continue
        by_year: dict[int, list[tuple[int, float]]] = {}
        for day, value in zip(days, values):
            by_year.setdefault(water_year(day), []).append(
                (_day_of_water_year(day), value)
            )
        for wy, pairs in sorted(by_year.items()):
            doy = np.array([p[0] for p in pairs], dtype=float)
            swe = np.array([p[1] for p in pairs], dtype=float)
            season = (doy >= low) & (doy <= high)
            covered = np.isfinite(swe) & season
            if covered.sum() < SEASON_COVERAGE * (high - low + 1):
                continue
            shape = season_shape(doy, swe, floor=SNOTEL_FLOOR_IN)
            if shape is None:
                continue
            station = stations[triplet]
            rows.append({
                "triplet": triplet, "water_year": wy,
                "elevation_ft": station["elevation_ft"],
                **{m: getattr(shape, m) for m in METRICS},
                "peak_swe_in": shape.peak_value,
            })
    return rows


def _model_cell_years(results: Path, model: str, variable: str, scale: float):
    """Shape metrics per band cell-year, and the normalised composite curve."""
    rows: list[dict] = []
    days_all, values_all, members_all = [], [], []
    pattern = str(results / f"{CHECKPOINT_STEM}_cell_checkpoints" / f"{model}_WY*.npz")
    for path in sorted(glob.glob(pattern)):
        wy = int(Path(path).stem.split("WY")[1])
        store = np.load(path, allow_pickle=True)
        band = terrain.band_masks(store["_lat"], store["_lon"])["above"]
        origin = date(wy - 1, 10, 1)
        doy = np.array([(date.fromisoformat(str(d)) - origin).days
                        for d in store["_days"]], dtype=float)
        cube = np.asarray(store[variable], dtype=float) * scale
        for i, j in zip(*np.nonzero(band)):
            series = cube[:, i, j]
            shape = season_shape(doy, series, floor=MODEL_FLOOR_MM)
            if shape is None:
                continue
            rows.append({"water_year": wy, "cell": f"{i}_{j}",
                         **{m: getattr(shape, m) for m in METRICS}})
            days_all.append(doy)
            values_all.append(np.nan_to_num(series))
            members_all.append(np.full(doy.size, f"{wy}_{i}_{j}"))
    curve = normalised_composite(
        np.concatenate(days_all), np.concatenate(values_all),
        np.concatenate(members_all),
    )
    return rows, curve


def _model_band_years(results: Path, model: str):
    """Shape metrics from the band-mean daily series, one value per water year."""
    rows: list[dict] = []
    pattern = str(results / f"{CHECKPOINT_STEM}_daily_checkpoints" / f"{model}_WY*.csv")
    for path in sorted(glob.glob(pattern)):
        wy = int(Path(path).stem.split("WY")[1])
        origin = date(wy - 1, 10, 1)
        doy, swe = [], []
        with open(path, newline="") as handle:
            for row in csv.DictReader(handle):
                doy.append((date.fromisoformat(row["date"]) - origin).days)
                swe.append(float(row["swe_mm_above"] or "nan"))
        shape = season_shape(np.array(doy, float), np.array(swe, float),
                             floor=MODEL_FLOOR_MM)
        if shape is not None:
            rows.append({"water_year": wy, **{m: getattr(shape, m) for m in METRICS}})
    return rows


def _write_csv(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp{os.getpid()}")
    with tmp.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)
    return path


def _band_mean_elevation_ft(results: Path) -> float:
    store = np.load(
        sorted(glob.glob(str(
            results / f"{CHECKPOINT_STEM}_cell_checkpoints" / "merra2_WY*.npz"
        )))[0], allow_pickle=True,
    )
    lat, lon = store["_lat"], store["_lon"]
    elevation = terrain.cell_mean_elevation(lat, lon)
    band = terrain.band_masks(lat, lon)["above"]
    return float(np.mean(elevation[band]) / 0.3048)


def _median_by_year(rows: list[dict]) -> dict[str, np.ndarray]:
    years = sorted({r["water_year"] for r in rows})
    out: dict[str, np.ndarray] = {}
    for metric in METRICS:
        out[metric] = np.array([
            np.nanmedian([r[metric] for r in rows if r["water_year"] == year])
            for year in years
        ])
    return out


def build_season_shape(results: Path, *, fetch: bool = True) -> dict:
    """Run the whole comparison and write every artefact. Returns the summary."""
    cache = results / "snotel_daily"
    if fetch:
        report = snotel.fetch_all(cache)
        print(f"SNOTEL fetch: {report.summary()}", flush=True)
        if not report.complete:
            raise RuntimeError(f"stations missing from disk: {report.missing}")

    band_ft = _band_mean_elevation_ft(results)
    station_years = snotel_station_years(cache)
    _write_csv(results / "snotel_season_shape.csv", station_years)

    # One value per station, so a long record does not outweigh a short one.
    per_station: dict[str, dict[str, float]] = {}
    for row in station_years:
        per_station.setdefault(row["triplet"], {"elevation_ft": row["elevation_ft"],
                                                "n": 0})
        per_station[row["triplet"]]["n"] += 1
    for metric in METRICS:
        for triplet, entry in per_station.items():
            entry[metric] = float(np.nanmedian(
                [r[metric] for r in station_years if r["triplet"] == triplet]
            ))
    fitted = {t: e for t, e in per_station.items() if e["n"] >= MIN_YEARS_FOR_GRADIENT}
    elevations = np.array([e["elevation_ft"] for e in fitted.values()])
    gradients = {
        m: elevation_gradient(elevations, np.array([e[m] for e in fitted.values()]))
        for m in METRICS
    }
    if not elevations.min() <= band_ft <= elevations.max():
        raise RuntimeError(
            f"band mean {band_ft:.0f} ft lies outside the fitted span "
            f"{elevations.min():.0f}-{elevations.max():.0f} ft: the correction "
            "would be an extrapolation, which this method does not license"
        )
    (results / "snotel_elevation_gradient.json").write_text(json.dumps(
        {m: {"slope_days_per_1000ft": gradients[m][0] * 1000,
             "intercept": gradients[m][1], "pearson_r": gradients[m][2]}
         for m in METRICS} | {"band_mean_ft": band_ft,
                              "fitted_stations": len(fitted),
                              "fitted_span_ft": [float(elevations.min()),
                                                 float(elevations.max())]}, indent=1))

    station_elev = np.array([r["elevation_ft"] for r in station_years])
    adjusted = {
        m: adjust_to_elevation(np.array([r[m] for r in station_years]),
                               station_elev, gradients[m][0], band_ft)
        for m in METRICS
    }
    years = np.array([r["water_year"] for r in station_years])
    snotel_by_year = {
        m: np.array([np.nanmedian(adjusted[m][years == y]) for y in sorted(set(years))])
        for m in METRICS
    }

    curves, per_year, band_rows = {}, {"SNOTEL": snotel_by_year}, {}
    for model, name, variable, scale in MODELS:
        cell_rows, curve = _model_cell_years(results, model, variable, scale)
        _write_csv(results / f"season_shape_cells_{model}.csv", cell_rows)
        band_rows[name] = _model_band_years(results, model)
        _write_csv(results / f"season_shape_band_{model}.csv", band_rows[name])
        per_year[name] = _median_by_year(cell_rows)
        curves[name] = curve

    curves["SNOTEL"] = _snotel_curve(cache)

    period = f"{min(years)}–{max(years)}"
    figures = [
        ssf.season_shape(curves, results / "season_shape", period=period),
        ssf.season_turning_points(per_year, results / "season_turning_points",
                                  period=period),
        ssf.snotel_timing_by_elevation(
            elevations, {m: np.array([e[m] for e in fitted.values()]) for m in METRICS},
            gradients, band_ft, results / "snotel_timing_by_elevation",
        ),
    ]
    summary = {
        "band_mean_ft": band_ft,
        "station_years": len(station_years),
        "stations": len(per_station),
        "fitted_stations": len(fitted),
        "period": period,
        "figures": [str(f) for f in figures],
        "median_days": {
            "SNOTEL": {m: float(np.nanmedian(adjusted[m])) for m in METRICS},
            **{name: {m: float(np.nanmedian(per_year[name][m])) for m in METRICS}
               for _, name, _, _ in MODELS},
        },
    }
    (results / "season_shape_summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def _snotel_curve(cache: Path):
    """Normalised composite over every admissible station-year."""
    low, high = SEASON_DAYS
    days_all, values_all, members_all = [], [], []
    for path in sorted(cache.glob("*_CO_SNTL.csv")):
        days, values = snotel.load_station(path)
        if not days:
            continue
        by_year: dict[int, list[tuple[int, float]]] = {}
        for day, value in zip(days, values):
            by_year.setdefault(water_year(day), []).append(
                (_day_of_water_year(day), value)
            )
        for wy, pairs in by_year.items():
            doy = np.array([p[0] for p in pairs], dtype=float)
            swe = np.array([p[1] for p in pairs], dtype=float)
            season = (doy >= low) & (doy <= high)
            if (np.isfinite(swe) & season).sum() < SEASON_COVERAGE * (high - low + 1):
                continue
            filled = np.nan_to_num(swe)
            if filled.max() < SNOTEL_FLOOR_IN:
                continue
            days_all.append(doy)
            values_all.append(filled)
            members_all.append(np.full(doy.size, f"{path.stem}_{wy}"))
    return normalised_composite(np.concatenate(days_all), np.concatenate(values_all),
                                np.concatenate(members_all))


if __name__ == "__main__":
    import pprint
    pprint.pp(build_season_shape(Path(__file__).resolve().parents[2] / "results"))
