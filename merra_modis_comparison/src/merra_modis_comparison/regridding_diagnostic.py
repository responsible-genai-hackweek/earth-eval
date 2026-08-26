from __future__ import annotations

import argparse
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import h5py
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize

from .config import RunConfig, TargetGrid
from .products import (
    TO_GEOGRAPHIC,
    TileMapping,
    aggregate_modscag,
    archived_tiles_for_grid,
    build_tile_mapping,
    download_modscag,
    tiles_for_grid,
)
from .spatial_plotting import _save_figure


@dataclass(frozen=True)
class NativeTile:
    tile: str
    longitude: np.ndarray
    latitude: np.ndarray
    snow_fraction_pct: np.ndarray
    target_index: np.ndarray


def _load_native_tile(path: Path, mapping: TileMapping) -> NativeTile:
    rows = slice(mapping.row_start, mapping.row_stop)
    columns = slice(mapping.col_start, mapping.col_stop)
    with h5py.File(path, "r") as dataset:
        x = np.asarray(dataset["x"][columns], dtype=np.float64)
        y = np.asarray(dataset["y"][rows], dtype=np.float64)
        snow = np.asarray(
            dataset["snow_fraction"][0, rows, columns], dtype=np.float64
        )
    xx, yy = np.meshgrid(x, y)
    longitude, latitude = TO_GEOGRAPHIC.transform(xx, yy)
    inside = mapping.target_index >= 0
    snow[(snow > 100) | ~inside] = np.nan
    return NativeTile(
        tile=mapping.tile,
        longitude=np.asarray(longitude),
        latitude=np.asarray(latitude),
        snow_fraction_pct=snow,
        target_index=mapping.target_index,
    )


def _draw_merra_grid(
    axis: plt.Axes,
    grid: TargetGrid,
    *,
    line_width: float = 0.65,
    alpha: float = 0.68,
) -> None:
    for longitude in grid.lon_edges:
        axis.axvline(longitude, color="#202124", linewidth=line_width, alpha=alpha)
    for latitude in grid.lat_edges:
        axis.axhline(latitude, color="#202124", linewidth=line_width, alpha=alpha)


def _format_geographic_axis(axis: plt.Axes, grid: TargetGrid) -> None:
    axis.set_xlim(grid.lon_edges[0], grid.lon_edges[-1])
    axis.set_ylim(grid.lat_edges[0], grid.lat_edges[-1])
    axis.set_xlabel("Longitude (°E)")
    axis.set_ylabel("Latitude (°N)")
    axis.set_aspect(1.0 / np.cos(np.deg2rad(float(np.mean(grid.lats)))))


def _draw_native(
    axis: plt.Axes,
    native_tiles: list[NativeTile],
    colormap: matplotlib.colors.Colormap,
    normalization: Normalize,
) -> None:
    for tile in native_tiles:
        axis.pcolormesh(
            tile.longitude,
            tile.latitude,
            tile.snow_fraction_pct,
            cmap=colormap,
            norm=normalization,
            shading="nearest",
            rasterized=True,
            zorder=1,
        )


def _draw_zoomed_cell(
    axis: plt.Axes,
    native_tiles: list[NativeTile],
    slot: int,
    grid: TargetGrid,
    colormap: matplotlib.colors.Colormap,
    normalization: Normalize,
) -> None:
    row, column = divmod(slot, len(grid.lons))
    west, east = grid.lon_edges[column : column + 2]
    south, north = grid.lat_edges[row : row + 2]
    for tile in native_tiles:
        selected = tile.target_index == slot
        if not np.any(selected):
            continue
        selected_rows, selected_columns = np.where(selected)
        row_slice = slice(max(0, int(selected_rows.min()) - 1), int(selected_rows.max()) + 2)
        column_slice = slice(
            max(0, int(selected_columns.min()) - 1),
            int(selected_columns.max()) + 2,
        )
        snow = tile.snow_fraction_pct[row_slice, column_slice].copy()
        target = tile.target_index[row_slice, column_slice]
        snow[target != slot] = np.nan
        axis.pcolormesh(
            tile.longitude[row_slice, column_slice],
            tile.latitude[row_slice, column_slice],
            snow,
            cmap=colormap,
            norm=normalization,
            shading="nearest",
            edgecolors=(1.0, 1.0, 1.0, 0.23),
            linewidth=0.08,
            rasterized=True,
        )
    axis.plot(
        [west, east, east, west, west],
        [south, south, north, north, south],
        color="#d94801",
        linewidth=2.0,
    )
    axis.set_xlim(west, east)
    axis.set_ylim(south, north)
    axis.set_xlabel("Longitude (°E)")
    axis.set_ylabel("Latitude (°N)")
    axis.set_aspect(1.0 / np.cos(np.deg2rad(grid.lats[row])))


def write_regridding_diagnostic(
    day: date,
    config: RunConfig,
    output: Path,
) -> None:
    grid = config.target_grid
    archive_tiles = archived_tiles_for_grid(grid)
    all_mappings = {
        tile: build_tile_mapping(None, tile, grid) for tile in tiles_for_grid(grid)
    }
    with tempfile.TemporaryDirectory(prefix=f"modscag-grid-{day:%Y%m%d}-") as temporary:
        temporary_path = Path(temporary)

        def download(tile: str) -> tuple[str, Path]:
            return tile, download_modscag(tile, day, temporary_path, retries=config.retries)

        with ThreadPoolExecutor(max_workers=len(archive_tiles)) as executor:
            paths = dict(executor.map(download, archive_tiles))
        for tile, path in paths.items():
            validated = build_tile_mapping(path, tile, grid)
            expected = all_mappings[tile]
            if not np.array_equal(validated.target_index, expected.target_index):
                raise ValueError(f"downloaded coordinate mapping changed for {tile}")
        native_tiles = [
            _load_native_tile(paths[tile], all_mappings[tile]) for tile in archive_tiles
        ]
        fraction, valid, expected, observed = aggregate_modscag(
            paths, all_mappings, grid
        )

        support = np.divide(
            valid,
            expected,
            out=np.zeros(grid.shape, dtype=np.float64),
            where=expected > 0,
        )
        accepted_fraction = fraction.copy()
        accepted_fraction[support < config.support_threshold] = np.nan
        if not np.isfinite(accepted_fraction).any():
            raise ValueError(f"no cells pass the support threshold on {day}")
        zoom_slot = int(np.nanargmax(accepted_fraction))
        zoom_row, zoom_column = divmod(zoom_slot, len(grid.lons))
        zoom_west, zoom_east = grid.lon_edges[zoom_column : zoom_column + 2]
        zoom_south, zoom_north = grid.lat_edges[zoom_row : zoom_row + 2]

        colormap = plt.get_cmap("Blues").copy()
        colormap.set_bad("#d9d9d9")
        normalization = Normalize(0, 100)
        figure, axes = plt.subplots(
            1,
            3,
            figsize=(13.5, 5.35),
            constrained_layout=True,
        )

        _draw_native(axes[0], native_tiles, colormap, normalization)
        _draw_merra_grid(axes[0], grid)
        axes[0].plot(
            [zoom_west, zoom_east, zoom_east, zoom_west, zoom_west],
            [zoom_south, zoom_south, zoom_north, zoom_north, zoom_south],
            color="#d94801",
            linewidth=2.2,
            zorder=4,
        )
        axes[0].set_title("Native 500 m MODSCAG\nMERRA-2 boundaries overlaid")
        _format_geographic_axis(axes[0], grid)

        _draw_zoomed_cell(
            axes[1], native_tiles, zoom_slot, grid, colormap, normalization
        )
        axes[1].set_title(
            "One MERRA-2 cell\n"
            f"{int(valid.ravel()[zoom_slot]):,} valid MODSCAG centers averaged"
        )

        image = axes[2].pcolormesh(
            grid.lon_edges,
            grid.lat_edges,
            100.0 * accepted_fraction,
            cmap=colormap,
            norm=normalization,
            shading="flat",
            edgecolors="#202124",
            linewidth=0.65,
        )
        for row, latitude in enumerate(grid.lats):
            for column, longitude in enumerate(grid.lons):
                value = accepted_fraction[row, column]
                label = "—" if not np.isfinite(value) else f"{100.0 * value:.0f}"
                axes[2].text(
                    longitude,
                    latitude,
                    label,
                    ha="center",
                    va="center",
                    fontsize=5.8,
                    color="#171717",
                )
        axes[2].set_title(
            "Pipeline result\nArithmetic mean after ≥80% support mask"
        )
        _format_geographic_axis(axes[2], grid)

        accepted_cells = int(np.count_nonzero(np.isfinite(accepted_fraction)))
        figure.suptitle(
            f"MODSCAG → MERRA-2 pixel-center aggregation | {day:%d %B %Y}\n"
            f"{','.join(archive_tiles)}; {accepted_cells}/{grid.size} target cells accepted",
            fontsize=12,
        )
        figure.colorbar(
            image,
            ax=axes,
            location="bottom",
            shrink=0.76,
            pad=0.04,
            label="Fractional snow-covered area (%)",
        )
        _save_figure(figure, output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plot one day of native and MERRA-grid MODSCAG fSCA"
    )
    parser.add_argument("--date", type=date.fromisoformat, default=date(2023, 1, 15))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/modscag_merra_grid_diagnostic_2023-01-15.png"),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = RunConfig()
    write_regridding_diagnostic(args.date, config, args.output)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
