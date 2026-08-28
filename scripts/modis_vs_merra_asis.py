#!/usr/bin/env python
"""Two-panel 'as-is' comparison: real MODIS raw 500 m snow_fraction next to
real MERRA-2 raw FRSNO on its native 0.625x0.5 grid, for one day. No
aggregation, no regridding, no diff -- each panel is exactly what that
product reports, at its own native resolution, so the resolution mismatch is
visible directly.

Reads the netCDF already produced by `cli.py examples` (real Earthdata/FTP
fetch, done separately) -- results/water_year_2010_2023_example_{label}_{date}.nc.
Does not fetch anything or touch the aggregation pipeline.

Usage: python scripts/modis_vs_merra_asis.py [--label high_snow] [--date 20110115]
"""

from __future__ import annotations

import argparse
import os

import numpy as np
import xarray as xr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(REPO_ROOT, "results")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="high_snow")
    parser.add_argument("--date", default="20110115")
    args = parser.parse_args()

    nc_path = os.path.join(RESULTS_DIR, f"water_year_2010_2023_example_{args.label}_{args.date}.nc")
    out_path = os.path.join(RESULTS_DIR, f"derived_modis_vs_merra_asis_{args.label}_{args.date}.png")

    ds = xr.open_dataset(nc_path)

    import matplotlib.pyplot as plt

    modis_lon = ds.modis_pixel_lon.values
    modis_lat = ds.modis_pixel_lat.values
    modis_sf = ds.modis_raw_snow_fraction.values
    valid = modis_sf <= 100
    modis_sf_plot = np.where(valid, modis_sf, np.nan)

    merra_raw = ds.merra_raw.values
    lon_centers = ds.lon.values
    lat_centers = ds.lat.values
    dlon = float(np.mean(np.diff(lon_centers)))
    dlat = float(np.mean(np.diff(lat_centers)))
    lon_edges = np.concatenate([lon_centers - dlon / 2, [lon_centers[-1] + dlon / 2]])
    lat_edges = np.concatenate([lat_centers - dlat / 2, [lat_centers[-1] + dlat / 2]])

    lon_min, lon_max = float(lon_edges[0]), float(lon_edges[-1])
    lat_min, lat_max = float(lat_edges[0]), float(lat_edges[-1])

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), constrained_layout=True)

    ax = axes[0]
    sc = ax.scatter(modis_lon, modis_lat, c=modis_sf_plot, cmap="YlOrRd", vmin=0, vmax=100,
                     s=1, marker=".", zorder=2)
    fig.colorbar(sc, ax=ax, shrink=0.85, label="Snow fraction (%)")
    ax.set_xlim(lon_min, lon_max)
    ax.set_ylim(lat_min, lat_max)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(f"STC-MODSCAG, raw 500 m pixels\n{ds.attrs['date']}")

    ax = axes[1]
    mesh = ax.pcolormesh(lon_edges, lat_edges, merra_raw, cmap="YlOrRd", vmin=0, vmax=100, zorder=2)
    fig.colorbar(mesh, ax=ax, shrink=0.85, label="FRSNO (%)")
    ax.set_xlim(lon_min, lon_max)
    ax.set_ylim(lat_min, lat_max)
    ax.set_xlabel("Longitude")
    ax.set_title(f"MERRA-2, native 0.625°×0.5° grid\n{ds.attrs['date']}, index 15 (15-16Z)")

    fig.suptitle("Same day, each product at its own native resolution -- no aggregation, no regridding")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
