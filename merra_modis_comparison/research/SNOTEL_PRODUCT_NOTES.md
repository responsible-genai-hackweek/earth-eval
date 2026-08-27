# SNOTEL product research

Research date: 2026-08-26. Written for the season-shape comparison specified in
[`../plan/SEASON_SHAPE_PLAN.md`](../plan/SEASON_SHAPE_PLAN.md).

## The product

NRCS SNOTEL, the Snow Telemetry network: automated stations that weigh the snow
above a pressure pillow and report daily. Snow water equivalent (`WTEQ`) is the
long-record element; snow depth (`SNWD`) came later at most sites and is not used
here.

- Network code `SNTL`, state code `CO`. Station triplets look like `335:CO:SNTL`.
- 120 Colorado stations, **every one of which falls inside this project's model
  envelope** (−109.0625…−104.0625°E, 36.75…41.25°N). No spatial filtering is
  needed beyond selecting the state.
- `WTEQ` is stored in **inches** natively, which is also this project's display
  unit, so no conversion is applied anywhere.

## Access

The Air and Water Database REST API. No credentials, no rate limit encountered.

```
https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/stations
    ?stationTriplets=*:CO:SNTL&activeOnly=false

https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data
    ?stationTriplets=<triplet>&elements=WTEQ&duration=DAILY
    &beginDate=1980-10-01&endDate=2026-09-30
```

One station's full 46-year record is 16,765 daily values in about 0.58 MB and
takes roughly 1.3 s. All 120 stations complete in 29 s on four workers. This is
small enough that resumption matters less than it does for the reanalyses, but
the fetcher is resumable anyway and reconciles requested stations against files
on disk rather than trusting a zero exit status.

The response nests two levels deep and the element block carries its own period
of record:

```json
[{"stationTriplet": "335:CO:SNTL",
  "data": [{"stationElement": {"elementCode": "WTEQ", "beginDate": "1978-10-01 00:00",
                               "storedUnitCode": "in"},
            "values": [{"date": "1980-10-01", "value": 0.0}]}]}]
```

## Traps

**The station's `beginDate` is not the element's `beginDate`.** Berthoud Summit
reports a station begin of 1963-09-01 and a `WTEQ` begin of 1978-10-01. Read the
period of record from `stationElement`, never from the station record.

**An empty `data` array is usually real.** Alta Lakes carries a station
`beginDate` of 2025-09-25, so a request for 2023 returns `[]` with HTTP 200. That
is an absence, not a failure, and the fetcher types it as `no_record` so it can
never be confused with a fetch that broke. Every one of the 120 stations returned
`ok` on the recorded run; nothing was inferred from silence.

**The station set drifts across the record.** 47 stations report in WY1981
against 117 in WY2026, because most of the Colorado network was installed in
1978–1979 with a second tranche in 1985. A climatology computed over all
reporting stations is therefore not computed over a fixed set. This is recorded
rather than corrected; a fixed-subset sensitivity test has not been run.

**A raw day count rejects the current water year.** The archive ends 2026-08-25,
so WY2026 holds about 329 days and a 350-day completeness gate silently discards
the year the whole analysis is about. The gate is defined on the snow season
(1 October–31 July) instead.

## Elevation, and why it governs everything

| | elevation, ft |
|---|---|
| SNOTEL, lowest site | 8,240 |
| SNOTEL, median site | 10,250 |
| SNOTEL, highest site | 11,680 |
| Model domain, median cell | 8,010 |
| 8,000–14,500 ft band, mean cell | 9,103 |

**The lowest SNOTEL station in Colorado sits above the model domain's median
cell.** The network is not a sample of this domain; it is a sample of the high
country inside it, sited by design where snow accumulates and persists. Any
comparison that puts a raw network statistic beside a raw domain statistic is
measuring that siting difference and reporting it as model error.

That is why this product is used for **timing only**, and why even the timing
comparison carries an elevation correction. Both are specified in the plan.

## Independence — unresolved

MERRA-2 does not assimilate snow observations; its land surface is driven by
observation-corrected precipitation. ERA5 runs a snow analysis that does ingest
in-situ snow depth. **Whether the station set feeding that analysis over CONUS
overlaps SNOTEL has not been checked.** Until it is, SNOTEL is an independent
check on MERRA-2 but only a provisionally independent one on ERA5, and any
write-up must say so.

References:

- [AWDB REST API](https://wcc.sc.egov.usda.gov/awdbRestApi/swagger-ui/index.html)
- [NRCS SNOTEL network](https://www.nrcs.usda.gov/wps/portal/wcc/home/aboutUs/monitoringPrograms/automatedSnowMonitoring/)
