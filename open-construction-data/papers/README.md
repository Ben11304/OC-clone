# OpenConstruction research papers

This directory is the local dataset-to-paper corpus used by the website and MCP
delivery layer.

## Layout

```text
papers/
├── manifest.json
└── <dataset-id>/
    └── paper.pdf
```

`manifest.json` covers every dataset in `datasets.json`. Each record contains
the paper identity, local availability, source, checksum, and verification
basis. A missing paper remains represented with `status: "unresolved"`.

## Storage, copyright, and publication

PDF files in this clone are tracked with Git LFS. The value
`redistribution_status: "unreviewed"` means that inclusion in this research
corpus is not evidence of a redistribution license. Verify the license or
permission for each paper before reusing or redistributing it. OpenConstruction
can always expose the DOI, citation, and legitimate source URL independently of
the local PDF.

## Refreshing the corpus

Run the importer from the OpenConstruction repository root with the audited
source manifest, its path root, the current dataset catalog, and this directory
as the destination. The importer verifies IDs and SHA-256 checksums and is safe
to rerun.
