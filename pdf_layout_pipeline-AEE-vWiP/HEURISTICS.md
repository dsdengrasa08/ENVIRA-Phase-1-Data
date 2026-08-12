# Active heuristic inventory

This inventory separates layout evidence from consumer content policy. Publisher
profiles contain data only; they do not contain executable conditions, coordinates,
filenames, hashes, or document-specific exceptions.

| Stage | Action | Primary evidence | Category | Destructive | Safeguard |
|---|---|---|---|---:|---|
| Page-1 upper | Exclude furniture | normalized upper-band geometry and title/body anchors | generic geometry/structure | yes | protected title and body anchors |
| Page-1 upper | Confirm publisher furniture | named publisher term profile | publisher-specific lexical | yes | must agree with geometry/structure in `confirmatory` mode |
| Page-1 lower | Exclude metadata | lower-page position, short clusters, contact/affiliation terms | scholarly structure and English lexical | yes | paragraph/body protections |
| Later headers | Exclude header | top-band position, recurrence, source-PDF row geometry | generic geometry/recurrence | yes | caption/asset and body protections |
| Figure completion | Expand asset | caption assignment, image ink bands, blockers | generic geometry/structure | yes | barriers and minimum-score controls |
| Nested assets | Change emission | containment in a figure/table | generic geometry | yes | recovered into hierarchy resolution |
| Side margins | Exclude furniture | narrow outer-margin geometry | generic geometry | yes | text/type constraints |
| Footer furniture | Exclude furniture | bottom-band geometry and visual/text recurrence | generic recurrence; optional publisher lexical | yes | assigned captions protect assets |
| Document tail | Secondary stream | conclusion/back-matter headings, sequence and page position | scholarly structure and English lexical | yes | confidence threshold and column reconciliation |
| Content policy | Retain/secondary | semantic section category selected by consumer | consumer policy | no layout deletion | excluded content remains auditable |
| Table/caption association | Associate | detector class, geometry, order, optional English prefixes | generic structure and language lexical | no | ambiguous candidates remain unattached |
| General caption ownership | Associate | explicit identifier class, geometry, direction, column, blockers, competing-parent margin | generic structure and language lexical | no | incompatible, ambiguous, and unattached captions remain visible |
| Containment observation | Observe only | shared strong/center coverage thresholds | generic geometry | no | cannot alter emission or reading order |
| Hierarchy policy | Accept/flag | parent compatibility matrix and inferred child role | generic structure | only compatible children become nested | unknown, invalid, and ambiguous roles remain top-level |

## Evidence categories

- `generic_geometry`: ratios, overlap, alignment, size, or recurrence.
- `generic_structure`: title/body boundaries, neighboring blocks, or detector roles.
- `scholarly_article_structure`: abstract, conclusion, reference, caption, or author conventions.
- `language_specific_lexical`: words whose meaning depends on the configured/detected language.
- `publisher_specific_lexical`: terms stored in a named optional publisher profile.

## Conservative fallback

Unknown document families retain ambiguous content. Publisher lexical evidence is
non-destructive in `disabled` and `evidence_only` modes and confirmatory by default.
Valid semantic back matter is retained in the secondary excluded stream unless the
content policy explicitly restores it to the main stream.

## Containment policy

`layout_overlap.py` emits only `CONTAINMENT_CANDIDATE` observations. The authoritative
resolver infers roles such as panel label, figure-internal text, table-cell text,
table note, form field, list item, body paragraph, and caption identifier, then applies
the declarative matrix in `nested_containment.py`. Text-to-text containment is routed
to duplicate/identifier-fragment/ambiguous-occlusion outcomes and never establishes
container hierarchy. One shared `containment` configuration section supplies geometry
and role thresholds.
