# Data Sources

Last checked: 2026-09-27. “Live” means a successful current request from the named provider, not a seed record or simulation.

| Source | Dataset / endpoint | Authentication | License / terms | Fields / freshness | Current status |
|---|---|---|---|---|---|
| OpenStreetMap extract already bundled | `backend/kc_valley_area.osm`, `kc_valley_focused.graphml`, buildings and water GeoJSON | None for the existing files | ODbL 1.0; attribution required; verify extract provenance/date | Road graph, building footprints/heights, water; snapshot with unknown date | Bundled static snapshot; label `CACHED`, not live; scope is KC Valley area. |
| OpenStreetMap services | [OSM website](https://www.openstreetmap.org/) / public tile service | No key, but public tile policy and capacity rules apply | ODbL data; tile service has separate usage policy | Map tiles, not guaranteed live city incidents | Use only for a small non-commercial demo; visible attribution required. Do not bulk-download from the public tile servers. |
| CARTO basemap style in MapView | `https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json` | No key in current app | CARTO basemap attribution/usage terms apply; underlying sources retain their licenses | Rendered base-map style | Used by map when reachable; attribution is visible. |
| Mapzen Terrain Tiles on AWS | `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png` | No key; public AWS Open Data bucket | Terrain source attribution is required; datasets vary by region. Global elevation includes USGS sources; consult [Tilezen attribution](https://github.com/tilezen/joerd/blob/master/docs/attribution.md) | Raster DEM; static elevation, not live | Used for MapLibre terrain where tiles load; low-resolution topography, not building-level survey. |
| Open-Meteo | [Forecast API](https://api.open-meteo.com/v1/forecast?latitude=12.935&longitude=77.645&current=temperature_2m,relative_humidity_2m,precipitation,rain,wind_speed_10m&hourly=precipitation,rain,wind_speed_10m&forecast_days=3&timezone=Asia%2FKolkata) | No key for free non-commercial use | CC BY 4.0 data; attribute. Free API non-commercial only; quotas/terms apply | Current conditions and forecast; model refresh cadence varies | Configured and callable; mark `LIVE` only after success, otherwise `CACHED` or `SIMULATED`. |
| Karnataka OGD / data.gov.in | [Karnataka portal](https://karnataka.data.gov.in/), [API docs](https://data.gov.in/help/how-use-datasets-apis) | Free account/API key for API use (`DATAGOV_API_KEY`) | Government Open Data License–India, subject to each resource metadata | Dataset-dependent; catalog item does not imply an API exists | Generic resource connector exists; no resource ID selected or live resource verified. Requires `DATAGOV_RESOURCE_ID`. |
| Bengaluru Open Data Portal (BenSCL) | [DataStore](https://opendata.benscl.com/) | No general API key; download/access is dataset-specific | License varies by dataset; portal FAQ says check each package | Mostly published datasets; update date varies | Candidate for static civic/hospital/ward datasets; no live operational feed assumed. |
| BBMP / Greater Bengaluru Authority | [BBMP/GBA site](https://site.bbmp.gov.in/) | No public general API identified | Dataset/site-specific | Maps and citizen-service pages; no verified incident stream | Not integrated. Citizen service pages are not a data API. |
| Hospitals / ambulance / fire / traffic | No verified public Bengaluru operational API found in this audit | Unknown / likely controlled | Must be established with provider | No verified live endpoint/freshness/read-only status | Use explicitly labeled demo inventory; no live dispatch integration. |
| Demo provider | Local deterministic state in the application | None | Project code | Repeatable simulated incidents, resource state and roads | `SIMULATED`; must never be displayed as live. |

## Provider rules

- Keep source URL, last-updated/fetched timestamp, license, and status with every provider result.
- A catalog page is not an API. Store government resource IDs in configuration; do not invent IDs.
- Do not ingest private ambulance/medical location data without authorization and a documented interface.
- Do not issue real dispatches, SMS, email, WhatsApp, or public alerts in demo mode.
- Weather endpoint status is returned as `LIVE`, `CACHED`, or `SIMULATED`; current weather is fetched from Open-Meteo when reachable.
- Emergency resource/hospital/traffic records remain seeded simulation data. They are not city operational feeds.
