#!/bin/sh
# Regenerate FINDINGS.md from a live run.
#
# The catalog is published data and changes; this file is a dated snapshot, not a
# guarantee. Re-run this to refresh it.
set -eu
cd "$(dirname "$0")"

{
    echo "# Findings"
    echo
    echo "Snapshot of the live catalog, produced by \`./regenerate-findings.sh\` on $(date -u +%Y-%m-%d)."
    echo "The catalog changes; re-run to refresh."
    echo
    echo '## Catalog'
    echo
    echo '```'
    echo '$ python3 vesuvius_catalog_check.py'
    python3 vesuvius_catalog_check.py
    echo '```'
    echo
    echo '## Per-segment meta.json'
    echo
    echo '```'
    echo '$ python3 segment_meta_check.py'
    python3 segment_meta_check.py 2>/dev/null
    echo '```'
} > FINDINGS.md

echo "FINDINGS.md regenerated." >&2
