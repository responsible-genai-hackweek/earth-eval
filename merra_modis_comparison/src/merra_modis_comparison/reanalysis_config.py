from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .grids import LambertConformalGrid, RegularLatLonGrid, SpatialGrid


@dataclass(frozen=True)
class LambertGridDefinition:
    x_origin: float
    y_origin: float
    x_step: float
    y_step: float
    full_width: int
    full_height: int
    latitude_of_projection_origin: float
    longitude_of_central_meridian: float
    standard_parallel: tuple[float, float]
    false_easting: float
    false_northing: float
    earth_radius: float


@dataclass(frozen=True)
class ReanalysisModelSpec:
    model_id: str
    display_name: str
    dataset_id: str
    variable: str
    cds_variables: tuple[str, ...]
    source_variable_candidates: tuple[tuple[str, ...], ...]
    fsca_method: str
    longitude_step: float
    latitude_step: float
    time_hour_utc: int
    product_type: str | None
    product_description: str
    doi: str
    access_backend: str = "cds"
    grid_kind: str = "regular_latlon"
    source_url_template: str | None = None
    lambert_grid: LambertGridDefinition | None = None

    def target_grid(
        self, west: float, east: float, south: float, north: float
    ) -> SpatialGrid:
        if self.grid_kind == "regular_latlon":
            return RegularLatLonGrid.from_domain(
                model_id=self.model_id,
                west=west,
                east=east,
                south=south,
                north=north,
                longitude_step=self.longitude_step,
                latitude_step=self.latitude_step,
            )
        if self.grid_kind == "lambert_conformal":
            if self.lambert_grid is None:
                raise ValueError(
                    f"{self.display_name} lacks a Lambert-grid definition"
                )
            definition = self.lambert_grid
            return LambertConformalGrid.from_domain(
                model_id=self.model_id,
                west=west,
                east=east,
                south=south,
                north=north,
                x_origin=definition.x_origin,
                y_origin=definition.y_origin,
                x_step=definition.x_step,
                y_step=definition.y_step,
                full_width=definition.full_width,
                full_height=definition.full_height,
                latitude_of_projection_origin=(
                    definition.latitude_of_projection_origin
                ),
                longitude_of_central_meridian=(
                    definition.longitude_of_central_meridian
                ),
                standard_parallel=definition.standard_parallel,
                false_easting=definition.false_easting,
                false_northing=definition.false_northing,
                earth_radius=definition.earth_radius,
            )
        raise ValueError(f"unknown grid kind: {self.grid_kind}")


MODEL_SPECS = {
    "era5": ReanalysisModelSpec(
        model_id="era5",
        display_name="ERA5",
        dataset_id="reanalysis-era5-single-levels",
        variable="diagnosed_snow_cover",
        cds_variables=("snow_depth", "snow_density"),
        source_variable_candidates=(
            ("sd", "snow_depth"),
            ("rsn", "snow_density"),
        ),
        fsca_method="era5_depth_density_diagnostic",
        longitude_step=0.25,
        latitude_step=0.25,
        time_hour_utc=15,
        product_type="reanalysis",
        product_description=(
            "reanalysis-era5-single-levels:snow_depth+snow_density[15:00Z]; "
            "ECMWF-documented diagnosed snow cover; "
            "CDS regular 0.25-degree grid"
        ),
        doi="10.24381/cds.adbb2d47",
    ),
    "era5-land": ReanalysisModelSpec(
        model_id="era5-land",
        display_name="ERA5-Land",
        dataset_id="reanalysis-era5-land",
        variable="snow_cover",
        cds_variables=("snow_cover",),
        source_variable_candidates=(("snowc", "snow_cover"),),
        fsca_method="direct_snow_cover",
        longitude_step=0.1,
        latitude_step=0.1,
        time_hour_utc=15,
        product_type=None,
        product_description=(
            "reanalysis-era5-land:snow_cover[15:00Z]; "
            "CDS regular 0.1-degree grid"
        ),
        doi="10.24381/cds.e2161bac",
    ),
    "narr": ReanalysisModelSpec(
        model_id="narr",
        display_name="NARR",
        dataset_id="Datasets/NARR/monolevel/snowc.{year}.nc",
        variable="snowc",
        cds_variables=(),
        source_variable_candidates=(("snowc",),),
        fsca_method="direct_snow_cover",
        longitude_step=32_463.0,
        latitude_step=32_463.0,
        time_hour_utc=15,
        product_type=None,
        product_description=(
            "NOAA PSL NARR:snowc[15:00Z]; direct snow-cover fraction; "
            "native AWIPS Grid 221 Lambert conformal grid"
        ),
        doi="gov.noaa.ncdc:C00618",
        access_backend="noaa_psl_opendap",
        grid_kind="lambert_conformal",
        source_url_template=(
            "https://psl.noaa.gov/thredds/dodsC/"
            "Datasets/NARR/monolevel/snowc.{year}.nc"
        ),
        lambert_grid=LambertGridDefinition(
            x_origin=0.0,
            y_origin=0.0,
            x_step=32_463.0,
            y_step=32_463.0,
            full_width=349,
            full_height=277,
            latitude_of_projection_origin=50.0,
            longitude_of_central_meridian=-107.0,
            standard_parallel=(50.0, 50.0),
            false_easting=5_632_642.22547,
            false_northing=4_612_545.65137,
            earth_radius=6_371_200.0,
        ),
    ),
}


@dataclass(frozen=True)
class ReanalysisRunConfig:
    start_water_year: int = 2010
    end_water_year: int = 2023
    model_ids: tuple[str, ...] = ("era5", "era5-land")
    west: float = -109.0
    east: float = -104.0
    south: float = 37.0
    north: float = 41.0
    workers: int = 16
    ftp_connections: int = 8
    cds_connections: int = 4
    support_threshold: float = 0.8
    retries: int = 4
    month_attempts: int = 2

    def validate(self) -> None:
        if self.start_water_year < 2001:
            raise ValueError("STC-MODSCAG water years begin after 2000-03-01")
        if self.end_water_year < self.start_water_year:
            raise ValueError("end water year must be at least the start water year")
        if self.end_water_year > 2023:
            raise ValueError(
                "STC_MODSCGDRF_HIST v1 ends 2023-09-30; end water year must be <= 2023"
            )
        if not self.model_ids:
            raise ValueError("at least one reanalysis model is required")
        if len(set(self.model_ids)) != len(self.model_ids):
            raise ValueError("reanalysis model identifiers must be unique")
        unknown = sorted(set(self.model_ids) - set(MODEL_SPECS))
        if unknown:
            raise ValueError(f"unknown reanalysis models: {', '.join(unknown)}")
        if not (-180 <= self.west < self.east <= 180):
            raise ValueError("expected -180 <= west < east <= 180")
        if not (-90 <= self.south < self.north <= 90):
            raise ValueError("expected -90 <= south < north <= 90")
        if not (1 <= self.workers <= 20):
            raise ValueError("workers must be between 1 and 20")
        if not (1 <= self.ftp_connections <= 9):
            raise ValueError(
                "FTP connections must be between 1 and 9 to remain below "
                "the MODSCAG archive's 10-connection per-IP limit"
            )
        if not (1 <= self.cds_connections <= 8):
            raise ValueError("CDS connections must be between 1 and 8")
        if not (0 < self.support_threshold <= 1):
            raise ValueError("support threshold must be in (0, 1]")
        if self.retries < 1:
            raise ValueError("retries must be at least 1")
        if self.month_attempts < 1:
            raise ValueError("month attempts must be at least 1")
        for spec in self.model_specs:
            if spec.time_hour_utc != 15:
                raise ValueError("the reviewed daily contract requires 15:00 UTC")
            if spec.access_backend not in {"cds", "noaa_psl_opendap"}:
                raise ValueError(
                    f"unsupported access backend for {spec.display_name}: "
                    f"{spec.access_backend}"
                )
            if spec.grid_kind not in {"regular_latlon", "lambert_conformal"}:
                raise ValueError(
                    f"unsupported grid kind for {spec.display_name}: {spec.grid_kind}"
                )
            if spec.access_backend == "cds" and not spec.cds_variables:
                raise ValueError(f"{spec.display_name} CDS variables cannot be empty")
            if (
                spec.access_backend == "noaa_psl_opendap"
                and spec.source_url_template is None
            ):
                raise ValueError(
                    f"{spec.display_name} NOAA OPeNDAP URL cannot be empty"
                )

    @property
    def model_specs(self) -> tuple[ReanalysisModelSpec, ...]:
        return tuple(MODEL_SPECS[model_id] for model_id in self.model_ids)

    def target_grid(self, model_id: str) -> SpatialGrid:
        try:
            spec = MODEL_SPECS[model_id]
        except KeyError as exc:
            raise ValueError(f"unknown reanalysis model: {model_id}") from exc
        return spec.target_grid(self.west, self.east, self.south, self.north)

    @property
    def water_years(self) -> tuple[int, ...]:
        return tuple(range(self.start_water_year, self.end_water_year + 1))

    @property
    def start_date(self) -> date:
        return date(self.start_water_year - 1, 10, 1)

    @property
    def end_date(self) -> date:
        return date(self.end_water_year, 9, 30)

    @property
    def dates(self) -> tuple[date, ...]:
        count = (self.end_date - self.start_date).days + 1
        return tuple(self.start_date + timedelta(days=index) for index in range(count))

    @property
    def calendar_months(self) -> tuple[tuple[int, int], ...]:
        months: list[tuple[int, int]] = []
        year, month = self.start_date.year, self.start_date.month
        end = (self.end_date.year, self.end_date.month)
        while (year, month) <= end:
            months.append((year, month))
            if month == 12:
                year, month = year + 1, 1
            else:
                month += 1
        return tuple(months)

    @property
    def domain_label(self) -> str:
        return (
            f"centers:{self.west:g},{self.east:g}E;"
            f"{self.south:g},{self.north:g}N"
        )


def month_dates(year: int, month: int) -> tuple[date, ...]:
    if month == 12:
        following = date(year + 1, 1, 1)
    else:
        following = date(year, month + 1, 1)
    current = date(year, month, 1)
    dates: list[date] = []
    while current < following:
        dates.append(current)
        current += timedelta(days=1)
    return tuple(dates)
