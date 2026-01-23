# Static Analysis Report (20260121-110824_b562249)

## Languages detected
- CSS: 2 file(s)
- HTML: 4 file(s)
- INI: 2 file(s)
- JSON: 22 file(s)
- JavaScript: 4 file(s)
- Markdown: 72 file(s)
- Python: 200 file(s)
- SQL: 1 file(s)
- TypeScript: 128 file(s)
- Unknown: 56 file(s)
- YAML: 3 file(s)

## Analysis modes + reliability
- CSS: regex / LOW
- HTML: regex / LOW
- INI: regex / LOW
- JSON: regex / LOW
- JavaScript: regex / LOW
- Markdown: regex / LOW
- Python: ast / MEDIUM
- SQL: regex / LOW
- TypeScript: regex / LOW
- Unknown: regex / LOW
- YAML: regex / LOW

## Signature metrics
- signatures_raw_multiline_count: 0
- signatures_raw_max_len: 189
- signatures_final_multiline_count: 0
- signatures_final_max_len: 189

## Counts
- files.csv rows: 494
- types: 299
- methods: 1265
- edges: 10067
- entrypoints: 221
- unused_prod: 866
- unused_with_tests: 866
- issues: 23

## Edge breakdown
{
  "total_edges": 10067,
  "internal_edges": 1382,
  "external_edges": 8685,
  "static_edges": 1382,
  "dynamic_edges": 2144,
  "unknown_edges": 0,
  "confidence_counts": {
    "HIGH": 0,
    "MEDIUM": 1382,
    "LOW": 8685
  },
  "unresolved_internal_targets_count": 0
}

## Entrypoints coverage
- prod_entrypoints_outgoing_internal_edges: 184/221
- test_entrypoints_outgoing_internal_edges: 0/0

## WARNING
Regex fallback: call graph/unused may contain false positives/negatives. Do NOT delete code based solely on unused_*. Use as radar for review.

## Paths
- output_root: /Users/kkitanin/Documents/MyApps/po_copilot/po_helper/analysis_output/runs/20260121-110824_b562249
- zip_path: /Users/kkitanin/Documents/MyApps/po_copilot/po_helper/analysis_output/exports/artifacts_20260121-110824_b562249.zip
- latest_zip: /Users/kkitanin/Documents/MyApps/po_copilot/po_helper/analysis_output/exports/LATEST.zip