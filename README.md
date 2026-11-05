Tensegrity Orientation Fetcher V8

A tiny Python prototype CLI to find and normalize per-module orientation time-series from given URLs (paper pages or supplement folders). It uses only the standard library and is meant as a starting point for a fuller tool.

Usage:

python3 main.py url1 [url2 ...]

Outputs: normalized JSON files named normalized_<n>.json and a provenance report provenance.txt in the current directory.

Notes and limitations:
- HTML link discovery is heuristic (finds hrefs ending with .csv or .json or containing 'supplement').
- No robust HTML parsing beyond simple href extraction; for complex pages, run with direct supplement URLs.
- Validation checks for time, module_id, and orientation fields in CSV/JSON rows; more complex formats need extensions.
- No external network credentials; access to paywalled supplements will fail and be recorded in provenance.

This is an experimental prototype. Expand parsing and validation rules for production use.