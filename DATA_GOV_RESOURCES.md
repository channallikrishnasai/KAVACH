# data.gov.in Resources

Verified 2026-09-27. **No government resource is currently connected.** The KAVACH adapter intentionally returns `NOT_CONFIGURED`/`UNAVAILABLE` until both `DATAGOV_API_KEY` and a real `DATAGOV_RESOURCE_ID` are supplied. An API key alone is not evidence that a dataset is accessible or suitable.

| Dataset | Resource ID | Endpoint | Fields used | Update frequency | License/terms | Current status | KAVACH agent |
|---|---|---|---|---|---|---|---|
| None selected | None | None | None | Unknown | Per-resource metadata required | NOT_CONFIGURED | None |

## Adapter behavior

- GET `https://api.data.gov.in/resource/{resource_id}` with server-side API key.
- Supports bounded `limit`/`offset` pagination (maximum 3 pages and 1,000 records per page), simple `q`, `fields`, `filters[field]`, and `sort[field]` parameters.
- Cache TTL is five minutes; a per-process rate limiter prevents request bursts. Failures return cached data when available or `UNAVAILABLE` with a sanitized error. API keys are excluded from provenance.
- The app does not invent resource IDs or infer a dataset's license. Before setting a resource ID, review its catalog entry, schema, update frequency, usage license and actual endpoint response.

See [data.gov.in API guide](https://data.gov.in/help/how-use-datasets-apis) and [registration](https://data.gov.in/user/register).
