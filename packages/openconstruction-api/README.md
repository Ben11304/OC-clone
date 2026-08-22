# @openconstruction/api

A lightweight JavaScript/TypeScript SDK for accessing OpenConstruction catalogs
(static JSON) hosted under `/data/*.json` on the OpenConstruction Open Science Platform.

This package provides a client for programmatic access to
datasets, models, tools, guides, use cases, educational resources, contributors,
and taxonomy metadata curated by OpenConstruction.


## Features

- Simple client for OpenConstruction catalogs
- Works with the hosted site **or** GitHub raw URLs
- Normalizes common JSON shapes:
  - Arrays
  - `{ id: record }` maps
  - Envelope objects (e.g., `{ datasets: [...] }`)
- Built-in keyword search helper
- Designed for browsers, Node.js, CI pipelines, and reproducible research


## Install

```bash
npm i @openconstruction/api
```

## Quick start (Hosted site)

```ts
import { OpenConstructionClient } from "@openconstruction/api";

const oc = new OpenConstructionClient({
  baseUrl: "https://www.openconstruction.org",
  noCache: true
});

const datasets = await oc.datasets();
const hits = await oc.search("models", "BIM", { limit: 50 });
const downloadPlan = await oc.datasetDownloadPlan("TBBR");

console.log(datasets.length, hits.length, downloadPlan);
```


## Quick start (GitHub raw)

This mode is useful for CI, reproducibility, or testing against a specific branch.

```ts
import { OpenConstructionClient } from "@openconstruction/api";

const oc = new OpenConstructionClient({
  baseUrl: "https://raw.githubusercontent.com/ruoxinx/open-construction/main/site",
  noCache: true
});

const vocab = await oc.objectVocab();
console.log(vocab);
```



## Catalog keys

Use these keys with `oc.list(key)`, `oc.get(key, id)`, or `oc.search(key, query, opts)`:

- `datasets`
- `models`
- `useCases`
- `tools`
- `guides`
- `oer`
- `contributors`
- `objectVocab`
- `objectTaxonomyConfig`



## Common methods

```ts
await oc.list("datasets");
await oc.get("models", "BIMgent");
await oc.search("tools", "annotation", { limit: 20 });
await oc.datasetDownloadPlan("VideoCAD");
```

`datasetDownloadPlan()` returns a normalized `direct`, `programmatic`, or `site`
plan. MCP tools can dispatch `programmatic` plans by their method, including
`figshare_files`, `dataverse_collection`, `designsafe_globus`, and
`google_drive_folder`, `http_files`, `dreamhouse_setup`, `roboflow_version`,
`kaggle_competition`, and `baidu_share_transfer`, while direct
plans expose the stable archive URL and filename.



## Notes

- Setting `noCache: true` forces `fetch()` to use `cache: "no-store"` for always-fresh data.
- All catalogs are **read-only** and served as static JSON.
- This SDK performs no authentication and makes no assumptions about backend services.
- The SDK is optional — OpenConstruction catalogs can always be accessed directly via `fetch()`.

## License

This package is licensed under Apache 2.0. See the repository root `LICENSE` and
`NOTICE` files for full terms and attribution information.
