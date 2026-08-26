---
date: 2026-08-25T22:45:00Z
researcher: Keiko Nomura
git_commit: eb3f4c529e0ad47f04312405d48489c6e7ee886e
branch: main
repository: earth-eval
topic: "Design and implementation of scalable MERRA-2 reanalysis validation pipeline against satellite observations"
tags: [research, architecture-design, merra2, satellite-validation, scalable-data-processing, memory-constraint]
status: complete
last_updated: 2026-08-25
last_updated_by: Keiko Nomura
---

# Research: Scalable MERRA-2 Validation Pipeline Against Satellite Observations

**Date**: 2026-08-25  
**Researcher**: Keiko Nomura  
**Git Commit**: eb3f4c529e0ad47f04312405d48489c6e7ee886e  
**Branch**: main  
**Repository**: earth-eval

## Research Question

Design and implement a scalable, configurable validation pipeline that:
- Evaluates MERRA-2 reanalysis output quality against independent MODIS and VIIRS satellite observations
- Excludes MERRA-2 variables directly assimilated as inputs (avoiding circular validation)
- Reconciles spatial resolution and temporal differences between datasets
- Supports user-configurable dataset/model selection, time periods, and geographic extent
- Operates within 10 GB memory/storage constraint using chunked/parallelized processing
- Includes MVP implementation with benchmarks for maximum data volume processable

## Summary

This research establishes the **architectural design** for the MERRA-2 validation pipeline, outlines the **data integration strategy**, defines **MVP scope and phased implementation**, identifies **key technical constraints**, and proposes a **benchmarking framework**. The repository is a greenfield project with no existing code, providing an opportunity to design clean architecture from first principles.

### Key Findings

1. **Data Compatibility Challenges**: MERRA-2 (0.5°×0.625° grid, hourly) vs MODIS/VIIRS (variable resolution, discrete overpasses) require spatial collocation and temporal interpolation
2. **Assimilation Awareness Critical**: MERRA-2 directly assimilates MODIS/AVHRR/MISR AOD, cloud properties, and precipitation—validation against these creates circular dependencies
3. **Memory Constraint Drives Architecture**: 10 GB is tight for climate data; single MERRA-2 monthly file (1-2 GB) + satellite data requires chunked loading and lazy evaluation
4. **Configurable Registry Pattern**: User control over dataset/variable/time/space selection requires factory pattern and configuration framework
5. **MVP Scope**: Start with temperature/humidity validation to establish patterns before adding complexity

---

## Detailed Findings

### 1. MERRA-2 Reanalysis Data Structure

#### Overview
- **Spatial Grid**: 0.5° latitude × 0.625° longitude (~55 km at equator)
- **Temporal Resolution**: Hourly instantaneous values + monthly time-averaged means
- **Variable Count**: 400+ variables (temperature, humidity, pressure, wind, precipitation, radiation, aerosols, clouds, etc.)
- **File Format**: NetCDF-4 (HDF5-based)
- **Typical File Sizes**: 
  - Monthly file (single variable, global): 1-2 GB
  - Daily file: ~60-80 MB
  - Analysis + forecast archives available

#### MERRA-2 Assimilation Constraints
MERRA-2 uses data assimilation to blend observations with model forecasts. Directly assimilating datasets include:
- **Aerosol Optical Depth (AOD)**: MODIS, AVHRR, MISR input → **DO NOT validate AOD against these sources**
- **Cloud Properties**: MODIS cloud fraction and optical depth assimilated → **avoid direct validation**
- **Precipitation**: TRMM, GPM, ground radar, gauge data assimilated → **use caution with precipitation validation**
- **Temperature/Wind**: Satellite-derived temperature, wind retrievals assimilated
- **Sea Ice/Snow**: Satellite observations assimilated

**Validation-Safe Variables**: 
- 2m Temperature (if satellite retrievals not used directly)
- Relative Humidity
- 10m Wind Speed/Direction (depending on satellite wind sources)
- Surface pressure
- Radiation fields (not directly assimilated but modeled)
- Soil moisture (partially assimilated, but satellite-independent retrievals exist)

#### Data Access Strategy
- MERRA-2 data available via NASA GES DISC (Earth Observing System Data and Information System)
- Requires authentication
- Provides subset/download capabilities (spatial, temporal, variable-level)
- NetCDF or HDF5 format download

---

### 2. MODIS and VIIRS Satellite Observation Data

#### MODIS (Moderate Resolution Imaging Spectroradiometer)
- **Resolution**: 1 km (band 1-2) to 500 m (bands 3-7), commonly aggregated to 5 km
- **Temporal Coverage**: Terra (1999-present), Aqua (2002-present)
- **Overpass Times**: Terra ~10:30 AM, Aqua ~1:30 PM local solar time (daily global coverage)
- **Primary Products for Validation**:
  - **MOD11/MYD11** (LST): Land Surface Temperature (~1 km)
  - **MOD04/MYD04** (AOD): Aerosol Optical Depth (~10 km) — **assimilated, avoid using**
  - **MOD05/MYD05** (Precipitable Water): Column water vapor (~1 km, 5 km)
  - **MOD06/MYD06** (Cloud Properties): Cloud optical depth, effective radius — **assimilated, avoid**
- **File Format**: HDF-EOS or NetCDF
- **Typical Granule**: ~5-10 MB (1 day, swath data)

#### VIIRS (Visible Infrared Imaging Radiometer Suite)
- **Resolution**: 375 m (I-bands), 750 m (M-bands), 1.6 km (DNB)
- **Coverage**: NOAA-20 (2017-present), S-NPP (2011-present)
- **Overpass Times**: Daily at ~13:30 and ~01:30 local solar time
- **Primary Products for Validation**:
  - **VNP21/VNP21C1** (LST): Land Surface Temperature (~375 m to 5 km)
  - **VNP14** (Fire Radiative Power)
  - **VNP46** (Nighttime Lights)
  - **VNP45** (Aerosol Properties) — **partially assimilated, use caution**
  - **VNP02/VNP03** (Corrected Radiance/Geolocation)
- **File Format**: NetCDF
- **Temporal Coverage**: Available L1/L2 products at NASA LP DAAC (Land Processes Distributed Active Archive Center)

#### Data Characteristics
- **Swath vs Grid**: Native swath data (irregular grid); requires regridding to common grid
- **Quality Flags**: Both MODIS and VIIRS include QA/QC flags (cloud contamination, retrieval quality)
- **Gaps**: Orbital gaps, cloud cover, instrument failures require handling
- **Latency**: L2 products available within days; some L3 gridded products within 1-2 months

---

### 3. Spatial and Temporal Reconciliation Strategies

#### Spatial Alignment Challenges
| Aspect | MERRA-2 | MODIS | VIIRS | Strategy |
|--------|---------|-------|-------|----------|
| Grid Type | Regular lat/lon | Swath (irregular) | Swath (irregular) | Reproject satellite to MERRA-2 grid |
| Resolution | 0.5°×0.625° (~55 km) | 1-5 km | 375 m - 1.6 km | Aggregate satellite to 0.5° grid |
| Reference System | WGS84 (EPSG:4326) | Swath-specific | Swath-specific | Use geospatial libraries (rasterio, pyproj) |

#### Spatial Collocation Approach
1. **Reproject satellite retrievals** to MERRA-2 grid using conservative interpolation (area-weighted aggregation preserves mass)
2. **Quality-aware aggregation**: Use QA flags to exclude poor-quality satellite retrievals before aggregating
3. **Spatial matching**: Match MERRA-2 cell to satellite-derived value at coincident location
4. **Uncertainty propagation**: Track satellite retrieval uncertainty through aggregation

#### Temporal Reconciliation Challenges
| Aspect | MERRA-2 | MODIS/VIIRS | Challenge |
|--------|---------|------------|-----------|
| Frequency | Hourly (instantaneous) | 1-2 times/day (swath timing) | Sparse temporal sampling |
| Time Reference | UTC, exact hour | Swath time (varies by location) | ±1-2 hour spread across swath |
| Temporal Support | Instantaneous | ~6-7 minute swath acquisition | Different observation window |

#### Temporal Matching Strategy
1. **Satellite-collocated**: Extract MERRA-2 at time closest to satellite overpass (±1-2 hours, configurable)
2. **Daily aggregation**: Average MERRA-2 hourly to daily, compare with daily satellite mean
3. **Time binning**: Bin both datasets to 6-hourly or daily resolution for robust comparison
4. **Uncertainty bounds**: Quantify temporal mismatch impact on validation metrics

---

### 4. Memory and Storage Constraints Analysis

#### 10 GB Constraint Breakdown

**Scenario 1: Single 1-year period, global domain, 2-4 variables**
- MERRA-2 (1 year, 1 variable, global, NetCDF): ~12 GB (exceeds budget)
- MODIS/VIIRS data (1 year, global): ~500 GB-1 TB raw
- **Issue**: Cannot load full year + satellite data simultaneously

**Scenario 2: Regional domain (e.g., 1000×1000 km), 1 month, multiple variables**
- MERRA-2 (1 month, 5 variables, regional): ~1-2 GB (manageable)
- MODIS/VIIRS (1 month, regional): ~10-50 GB raw, ~1-5 GB after quality filtering
- **Issue**: Still tight; requires selective loading and filtering

#### Storage Efficiency Strategies

| Strategy | Benefit | Trade-off |
|----------|---------|-----------|
| **NetCDF chunking** | Load only needed chunks (time/space slices) | Requires chunked file organization |
| **Zarr format** | Cloud-native chunks, lazy loading, compression | File format migration required |
| **Dask arrays** | Out-of-core computation, automatic chunking | API differs from NumPy, potential memory overhead |
| **Satellite QA filtering** | Exclude poor retrievals before loading | Reduces usable observations, requires QA knowledge |
| **Temporal subsampling** | Use every Nth day/week instead of daily | Reduces temporal resolution, may miss events |
| **Spatial subsampling** | Coarsen to coarser grid (1° instead of 0.5°) | Reduces spatial detail |
| **Variable selection** | Load only variables being validated | Requires upfront variable specification |
| **Cloud-native processing** | S3-resident data with on-demand access | Requires cloud infrastructure (AWS, Google Cloud) |

#### Recommended Approach: Chunked Lazy Loading
1. **Use xarray with NetCDF backend and explicit chunking** (e.g., 1 month × spatial domain per chunk)
2. **Filter satellite data by QA flags before aggregation** (typically 30-50% reduction)
3. **Process by time window** (monthly or seasonal chunks) to avoid full-year loading
4. **Compress intermediate results** (netCDF compression level 4-5)
5. **Use Dask for parallelized operations** within chunk boundaries

#### Memory Profiling for MVP
```
Memory allocation targets:
- MERRA-2 data in memory: 2-3 GB (1 month, regional, 5 variables)
- Satellite data in memory: 2-3 GB (1 month, regional, after QA filtering)
- Working arrays (interpolation, metrics): 2-3 GB
- Overhead (metadata, indices, temporary arrays): 1-2 GB
Total: ~8-10 GB
```

---

### 5. Validation Metrics and Methodologies

#### Core Comparison Metrics for Snow Cover Fraction

**Primary Metric (MVP)**:
| Metric | Formula | Use Case | Interpretation |
|--------|---------|----------|---|
| **Bias** | mean(MERRA2_snowfrac - Satellite_snowfrac) | Systematic over/under-estimation | +0.1 = 10% overestimate; -0.1 = 10% underestimate |

**Why bias for snow?**
- Snow cover fraction is bounded [0, 1], so bias directly shows systematic model error
- Easy to interpret: positive bias = MERRA-2 overestimates snow coverage
- Spatially explicit: can map bias to identify regional problem areas (sheltered valleys, ridgetops, etc.)

**Secondary Metrics (Phase 2)**:
- **Spatial Pattern Correlation**: Captures spatial structure agreement (does MERRA-2 get the "snow pattern" right?)
- **Temporal Consistency**: Track bias through time (Dec → Jan → Feb)
- **Histogram Matching**: Compare probability distributions (MERRA-2 snow freq vs satellite)
- **ROC Analysis**: If converting to binary (snow/no-snow), compute POD/FAR curves

#### Validation Considerations for Snow
- **QA filtering**: Use MODIS/VIIRS QA flags to exclude cloud-contaminated retrievals
- **Diurnal timing**: Satellite overpasses ~10:30 AM (MODIS Terra) and ~1:30 PM (Aqua); match to MERRA-2 daily mean
- **Observation gaps**: Clouds frequent in winter; track valid observation count per day
- **Elevation dependency**: Colorado has steep topography; snow varies dramatically with elevation

---

### 6. Configurable Pipeline Architecture

#### High-Level Design

```
┌─────────────────────────────────────────────────────────────┐
│                     USER CONFIGURATION                      │
│  (YAML: datasets, variables, time period, geographic box)   │
└──────────────────────────┬──────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    ┌────▼────┐     ┌─────▼─────┐     ┌────▼────┐
    │ MERRA-2 │     │   MODIS   │     │  VIIRS  │
    │ Loader  │     │  Loader   │     │ Loader  │
    └────┬────┘     └─────┬─────┘     └────┬────┘
         │                │                │
         │          ┌──────┴──────┐        │
         │          │   Reproject │        │
         │          │   & Filter  │        │
         │          └──────┬──────┘        │
         │                 │               │
         └────────┬────────┴───────────────┘
                  │
         ┌────────▼────────┐
         │  Spatial Align  │
         │ (Regrid to 0.5°)│
         └────────┬────────┘
                  │
         ┌────────▼────────┐
         │ Temporal Match  │
         │ (±2 hr, daily)  │
         └────────┬────────┘
                  │
         ┌────────▼────────┐
         │  Compute Metrics│
         │ (bias, RMSE, r) │
         └────────┬────────┘
                  │
         ┌────────▼────────┐
         │    Visualize    │
         │    & Report     │
         └────────────────┘
```

#### Configuration Schema (YAML) - MVP Example: Colorado Snow

```yaml
validation:
  merra2:
    product: M2T1NXLND.5.12.4  # Land surface variables (daily)
    variables: [SNODP]  # Snow depth (mm)
    convert_to_fraction: true  # Convert depth to snow cover fraction [0-1]
    snow_depth_threshold: 10  # mm (snow present if depth > threshold)
    time_period:
      start: "2022-12-01"
      end: "2023-02-28"
    
  satellite:
    products:
      - name: MODIS
        datasets: [MOD10A1]  # Collection 6.1, daily snow cover, 500 m
        variables: [NDSI_Snow_Cover]  # 0-100 scale, convert to [0-1]
        qa_filtering: true  # Exclude cloud-masked, inland water
      - name: VIIRS
        datasets: [VNP10A1]  # Collection 1, daily snow cover, 375 m
        variables: [NDSI_Snow_Cover]
        qa_filtering: true
    
  spatial:
    domain: [37.5, 40.5, -106.5, -104.5]  # [lat_min, lat_max, lon_min, lon_max] Colorado
    merra2_grid: true  # Aggregate satellite (500 m / 375 m) to 0.5° MERRA-2 grid
    aggregation_method: "conservative"  # Preserve mass in reprojection
    
  temporal:
    matching_window: 2  # hours (satellite overpass ±2h)
    aggregation: daily  # Average to daily from hourly
    
  metrics:
    - bias  # Primary MVP metric
    
  output:
    format: netcdf  # Output as NetCDF
    compression: 4  # gzip compression level
    variables: [bias, merra2_snowfrac, satellite_snowfrac, count_valid_observations]
```

#### Registry/Factory Pattern
```python
class DatasetRegistry:
    """Factory for dataset handlers"""
    _registry = {}
    
    @classmethod
    def register(cls, name, handler_class):
        cls._registry[name] = handler_class
    
    @classmethod
    def get_handler(cls, name, config):
        return cls._registry[name](config)

# Register built-in handlers
DatasetRegistry.register("MERRA2", MERRA2Handler)
DatasetRegistry.register("MODIS", MODISHandler)
DatasetRegistry.register("VIIRS", VIIRSHandler)
```

---

### 7. MVP Scope and Phased Implementation

#### Phase 1: MVP (Minimum Viable Product)
**Goal**: Establish core patterns, validate architecture, benchmark 10 GB constraint

**Scope**:
- Single MERRA-2 variable: Snow Cover Fraction (SNODP or derived binary)
- Satellite datasets: MODIS MOD10A1 (daily, 500 m) + VIIRS VNP10A1 (daily, 375 m)
- Geographic domain: Colorado (~450×350 km, centered ~39°N, 105.5°W)
- Time period: 3 months (Dec 2022 - Feb 2023, Northern Hemisphere winter)
- Validation metric: Bias (systematic over/under-estimation of snow coverage)
- Processing: Daily chunking, no parallelization (sequential)

**Assimilation Status**: ✅ CONFIRMED - MODIS/VIIRS snow products NOT assimilated into MERRA-2; independent validation

**Deliverables**:
1. MERRA-2 snow loader (read SNODP, convert to snow cover fraction)
2. MODIS MOD10A1 loader (read daily snow cover)
3. VIIRS VNP10A1 loader (read daily snow cover)
4. Spatial regridding to 0.5° MERRA-2 grid (conservative aggregation)
5. Temporal matching (daily, satellite overpass ±2 hours)
6. Bias computation: mean(MERRA2_snow - satellite_snow)
7. CSV report + spatial map visualization
8. Memory/runtime profiling

**Expected Resource Usage** (MVP):
- Disk: ~300-500 MB (output only; input streaming)
- Memory: ~1-2 GB (Colorado domain is small)
- Runtime: ~3-10 minutes (single-threaded)
- Data Volume: ~500 MB - 1 GB

#### Phase 2: Expansion (Post-MVP)
- Add second satellite: VIIRS VNP21C1
- Add more MERRA-2 variables: humidity (QV2M), wind (U10M, V10M)
- Extend time period to full year
- Expand spatial domain to regional/global subsets
- Add Dask parallelization for temporal chunks

#### Phase 3: Production
- Full global, multi-year capability
- User configuration CLI
- Cloud-native (Zarr, S3)
- Uncertainty quantification
- Web dashboard for visualization

---

### 8. Technology Stack Recommendation

#### Core Libraries
| Layer | Library | Purpose | Rationale |
|-------|---------|---------|-----------|
| **Data** | xarray | NetCDF/multidimensional data | Industry standard for climate data |
| **Compute** | NumPy/SciPy | Numerical operations, stats | Performance, ubiquitous |
| **Parallel** | Dask | Chunked, out-of-core processing | Seamless xarray integration |
| **Geospatial** | rasterio + pyproj | Reprojection, georeference | Production-grade, tested |
| **Config** | PyYAML + Pydantic | Configuration parsing, validation | Type-safe configs |
| **CLI** | Click or Typer | Command-line interface | User-friendly, structured |
| **Viz** | Matplotlib + Cartopy | Maps and time series plots | Scientific standard |

#### Rationale
- **xarray + Dask**: Designed for exactly this use case (climate data, chunked processing)
- **NetCDF backend**: MERRA-2 native format; zero-copy read with xarray
- **rasterio**: Robust handling of satellite georeference and reprojection
- **Pydantic**: Guarantees configuration is valid before processing starts

#### Environment Setup
```bash
# Core dependencies (python-3.10+)
pip install xarray[complete] dask[dataframe] netCDF4 h5netcdf h5py
pip install rasterio pyproj cartopy
pip install numpy scipy scikit-learn pandas
pip install pyyaml pydantic click
pip install pytest pytest-cov  # testing
```

---

### 9. Benchmarking Framework for MVP

#### Metrics to Track
1. **Peak Memory Usage** (`memory_peak_mb`): Maximum resident set size
2. **Disk Space** (`disk_used_mb`): Intermediate files + output
3. **Runtime** (`runtime_sec`): Total wall-clock time
4. **Data Volume Processed** (`data_volume_gb`): Input bytes read
5. **Effective Throughput** (`throughput_gbps`): Data volume / runtime

#### Benchmark Test Cases (MVP - Colorado Snow)

| Name | Scope | Expected Volume | Target Peak Mem | Target Runtime |
|------|-------|-----------------|-----------------|-----------------|
| **Tiny** | 1 week, Colorado, MERRA-2 only | 50 MB | 300 MB | 30 sec |
| **Small** | 1 month (Dec), Colorado, MERRA-2 + MODIS | 150 MB | 800 MB | 1 min |
| **MVP Target** | 3 months (Dec-Feb), Colorado, MERRA-2 + MODIS + VIIRS | 400-600 MB | 1.5-2 GB | 3-5 min |
| **Extended** | 6 months, Colorado, daily | 800 MB | 2-3 GB | 10 min |
| **Max Feasible** | 12 months, Colorado, daily | 1.6 GB | 3-4 GB | 20 min |

#### Profiling & Optimization Checkpoints
```python
# Use memory_profiler, py-spy for wall-clock profiling
from memory_profiler import profile

@profile
def load_merra2(time_period, domain, variables):
    # Profile peak memory during load
    pass

# Use cProfile for CPU time
import cProfile
cProfile.run('main()', sort='cumulative')
```

---

### 10. Known Constraints and Risks

#### Data Assimilation Constraints
- **AOD Validation**: Cannot validate MERRA-2 AOD against MODIS/MISR AOD (directly assimilated)
- **Cloud Properties**: Cannot validate cloud optical depth against MODIS (assimilated)
- **Precipitation**: Risky; TRMM/GPM data assimilated in MERRA-2
- **Temperature**: Satellite-derived T used in assimilation; surface temperature safer than profile

**Mitigation**: Maintain a registry of "assimilation-safe" and "risky" variable pairs; warn users when attempting risky validation.

#### Spatial and Temporal Mismatches
- **Grid Mismatch**: MERRA-2 0.5° vs satellite 1-5 km requires aggregation (loses detail, causes smoothing bias)
- **Temporal Mismatch**: Satellite overpass ≠ MERRA-2 time (±1-2 hour uncertainty); diurnal cycles cause aliasing
- **Orbital Gaps**: MODIS/VIIRS have daily gaps in polar regions; equatorial coverage nearly complete

**Mitigation**: 
- Document aggregation method in metadata
- Quantify temporal mismatch uncertainty
- Flag regions with poor satellite coverage

#### 10 GB Memory Constraint
- **Challenge**: Single MERRA-2 monthly global file (~1-2 GB) + satellite data quickly exceeds budget
- **Cannot process**: Full globe + full year simultaneously
- **Requires**: Chunking or domain subsetting

**Mitigation**:
- Force user to specify geographic domain (no global-by-default)
- Process by time chunks (monthly or seasonal)
- Implement automatic memory monitoring and graceful failure if exceeded

---

## Code References

*None yet—this is a greenfield project. References will be added as implementation proceeds.*

---

## Architecture Insights

### Design Principles
1. **Lazy Evaluation**: Load data only when needed; leverage xarray's lazy-loading capabilities
2. **Configuration-Driven**: User-facing configuration (YAML) decouples logic from data specifics
3. **Factory Pattern**: Extensible dataset handlers allow adding new data sources without core changes
4. **Chunked Processing**: Time/space chunks map to memory budget; process independently and aggregate results
5. **Metadata Preservation**: Track provenance (data source, QA flags, processing steps) through pipeline
6. **Testability**: Separate data loaders, regridding, metrics into independently testable units

### Architectural Components
```
earth_eval/
├── __init__.py
├── config/
│   ├── schema.py          # Pydantic config schema
│   └── validation_config.yaml  # Example config
├── data/
│   ├── loaders.py         # Dataset loaders (base class + implementations)
│   ├── merra2.py          # MERRA-2 handler
│   ├── modis.py           # MODIS handler
│   └── viirs.py           # VIIRS handler
├── processing/
│   ├── regridding.py      # Spatial regridding logic
│   ├── temporal_match.py   # Temporal collocation
│   └── qa_filtering.py    # Quality-aware filtering
├── metrics/
│   ├── comparison.py      # Bias, RMSE, correlation
│   └── uncertainty.py     # Uncertainty propagation
├── registry.py            # Dataset factory/registry
├── pipeline.py            # Main orchestration
├── cli.py                 # Command-line interface
├── visualization.py       # Plotting and reporting
└── benchmarks/
    ├── profile_memory.py
    ├── profile_time.py
    └── test_cases.py
```

### Key Design Decisions
1. **NetCDF over Zarr for MVP**: NetCDF is native for both MERRA-2 and MODIS; Zarr can follow in Phase 2 for cloud
2. **Monthly chunking**: Balances granularity and memory footprint
3. **Sequential processing for MVP**: Simplifies debugging; parallelization in Phase 2
4. **Satellite aggregation (not MERRA-2 interpolation)**: Preserves satellite retrieval accuracy; aggregation is more defensible than interpolating coarse MERRA-2 grid
5. **Explicit time matching over modeling diurnal cycle**: Avoids assumptions; trades temporal resolution for certainty

---

## Historical Context (from thoughts/)

*No prior research documents exist in thoughts/. This is a greenfield analysis.*

---

## Related Research

*None yet—first research on this project.*

---

## Open Questions (Snow Cover MVP)

1. **Data Access**: 
   - MERRA-2: GES DISC with authentication, or pre-staged downloads?
   - MODIS MOD10A1 / VIIRS VNP10A1: LP DAAC (Land Processes DAAC) direct download or AWS/Google Cloud?

2. **Snow Depth Threshold**:
   - MERRA-2 snow depth (SNODP) to snow cover fraction: use 10 mm threshold, or different?
   - Or use MERRA-2 existing snow cover fraction if available (FRSNO)?

3. **Quality Assurance**:
   - MODIS MOD10A1 QA: exclude cloud-masked (75-100) and inland water, keep 0-50?
   - VIIRS VNP10A1 QA: similar strategy?
   - Accept any pixels with valid data, or require 80%+ daily coverage?

4. **Bias Threshold**:
   - What bias level is "acceptable"? (e.g., bias within ±0.1 snow fraction = ±10%?)
   - Or focus on spatial patterns (where does MERRA-2 over/underestimate)?

5. **Error Handling**:
   - If satellite data missing for a day (cloud cover, orbit gap): skip day or interpolate?
   - Fail-fast on missing data, or graceful degradation?

6. **Reporting**:
   - Simple CSV report (date, bias, count_valid_obs), or spatial map (bias per grid cell)?
   - Include confidence intervals from satellite uncertainty?

---

## Next Steps (Recommended)

### Immediate (This Session)
1. ✓ Complete codebase research and architecture design (this document)
2. Implement Phase 1 MVP:
   - Basic project structure and dependencies
   - MERRA-2 loader (read T2M from NetCDF)
   - MODIS MOD11C2 loader (read LST)
   - Spatial regridding to 0.5° MERRA-2 grid
   - Temporal matching (daily averages)
   - Compute bias, RMSE, correlation
   - Generate CSV report and PNG plot

### Validation Checkpoints
- Memory profiling: Confirm MVP stays <3 GB peak memory
- Runtime benchmark: Establish baseline performance
- Accuracy check: Compare computed metrics against hand-calculated values for small subset

### Post-MVP
- Add configuration framework (YAML + Pydantic)
- Integrate VIIRS handler
- Implement command-line interface
- Add uncertainty quantification
- Extend to multi-variable, full-year validation

---

**Status**: Ready for implementation. MVP scope clearly scoped; technical risks identified; benchmark framework defined.
