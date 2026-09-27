# Third-Party Components and Attribution

## Repository/source reuse

No source code was copied from another repository for the KAVACH conversion. The user-linked [KAVACH repository](https://github.com/channallikrishnasai/KAVACH) is Apache-2.0 licensed but currently has no implementation files. This workspace's CrisisFlow source remains the foundation; its original license/provenance is not present in the extracted directory and must be confirmed before redistribution.

The candidate external repository review and copy/no-copy decisions are in [EXTERNAL_COMPONENT_AUDIT.md](EXTERNAL_COMPONENT_AUDIT.md).

## Data and services currently referenced

- **OpenStreetMap:** Existing OSM extract and derived graph/GeoJSON are bundled. ODbL 1.0 applies to OSM database data. Preserve visible attribution: “© OpenStreetMap contributors”. Source URL: https://www.openstreetmap.org/copyright. Extract timestamp/source query are not recorded in the bundle and must be recovered before describing the snapshot as current.
- **CARTO Dark Matter:** The MapLibre style references `https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json`. Provider/source attribution is visible; follow CARTO usage terms: https://carto.com/basemaps/attributions/ .
- **Mapzen Terrain Tiles on AWS:** MapLibre terrain uses the public `elevation-tiles-prod` Terrarium tiles. No key is needed. Terrain provenance varies regionally; include Mapzen and contributing DEM source attribution per https://github.com/tilezen/joerd/blob/master/docs/attribution.md . Elevation is not building-level photogrammetry.
- **Open-Meteo:** Existing backend calls Open-Meteo. Attribute weather data to Open-Meteo and link https://open-meteo.com/ . Weather data is CC BY 4.0; free endpoint usage is non-commercial and subject to quotas: https://open-meteo.com/en/terms .

## Dependencies

The project uses React, Vite, Deck.gl, MapLibre, FastAPI, PyTorch, PyTorch Geometric, OSMnx, NetworkX, Motor and their transitive dependencies as declared in the package manifests/requirements. No dependency source was copied. Run package license inventory before binary redistribution; preserve each dependency's own notices. A KAVACH Apache-2.0 repository license does not override data/model/dependency licenses.

`tesseract.js` is used for browser-side OCR under Apache-2.0. It downloads language data on demand. OpenCV is used for measurable surface contrast cues only; neither package provides pothole/crack classification here.

## Models

`stgcn_weights.pth` and `stgcn_checkpoint.pth` are present, but their training dataset/source provenance and model license are not included. `val_dataset.pt` is missing. Do not redistribute or claim operational predictions until provenance and artifact compatibility are confirmed.

The candidate [Hugging Face road detector](https://huggingface.co/vinothvikas1987/pothole-detection-yolov8) declares Apache-2.0 in its model card, but its ONNX metadata declares AGPL-3.0 and does not identify a training-data license. The artifact was used only to inspect metadata and was deleted. KAVACH does not run or distribute this detector. Written license clarification and dataset provenance are required before reconsideration.
