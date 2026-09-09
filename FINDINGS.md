# Findings

Run against the live catalog on 2026-09-09.

```
Vesuvius catalog check
  45 samples · 67 scans · 71 volumes · 311 segments

[ok  ] coverage-bbox-inverted       —          0  volume_coverage bbox has a lower corner above its upper corner
[FAIL] coverage-ratio-contradicts-bbox #1734    407  overlap_ratio claims full coverage while the bbox falls outside the volume
           PHercMANBp/20251218010446: volume 20251216152116: overlap_ratio 1.0 but axes [2] fall outside shape [17148, 12577, 12577]
           PHercMANBp/20251218010446: volume 20260427100434: overlap_ratio 1.0 but axes [2] fall outside shape [35024, 22137, 20286]
           PHercMANBp/20251217234605: volume 20251216152116: overlap_ratio 1.0 but axes [2] fall outside shape [17148, 12577, 12577]
           PHercMANBp/20251217234605: volume 20260427100434: overlap_ratio 1.0 but axes [2] fall outside shape [35024, 22137, 20286]
           PHercMANBp/20251222204911: volume 20251216152116: overlap_ratio 1.0 but axes [2] fall outside shape [17148, 12577, 12577]
           PHercMANBp/20251222204911: volume 20260427100434: overlap_ratio 1.0 but axes [2] fall outside shape [35024, 22137, 20286]
           PHercMANBp/20251220012955: volume 20260427100434: overlap_ratio 1.0 but axes [2] fall outside shape [35024, 22137, 20286]
           PHercMANBp/20251218211706: volume 20251216152116: overlap_ratio 1.0 but axes [2] fall outside shape [17148, 12577, 12577]
           ... 399 more (use --verbose)
[ok  ] coverage-volume-dangling     —          0  volume_coverage is keyed by a volume the sample does not publish
[FAIL] creation-info-inconsistent   #1436     29  an artifact deviates from its type's creation_info convention
           PHerc0332/volume/20251211183505: type 'lasagna' is the only 4/25 missing creation_info
           PHerc1299/volume/20260309130042: type 'lasagna' is the only 4/25 missing creation_info
           PHerc0139/volume/20260102150214: type 'lasagna' is the only 4/25 missing creation_info
           PHercParis4/volume/20260411134726: type 'lasagna' is the only 4/25 missing creation_info
           PHerc0500P2/segment/20250611171318: type 'obj' is the only 9/171 missing creation_info
           PHerc0500P2/segment/20250611171745: type 'obj' is the only 9/171 missing creation_info
           PHerc0800/segment/20251028222030: type 'obj' is the only 9/171 missing creation_info
           PHerc0800/segment/20251028225813: type 'obj' is the only 9/171 missing creation_info
           ... 21 more (use --verbose)
[ok  ] data-format-mixed            —          0  a sample publishes volumes in mixed integer widths
[FAIL] derived-from-dangling        #1504      3  creation.derived_from points at an id that does not resolve to its declared type
           PHerc0009B/volume/20250521125136: declared type 'volume', id 20250509053741 resolves only as scan
           PHerc0009B/volume/20250820154339: declared type 'volume', id 20250718080859 resolves only as scan
           PHerc0009B/segment/20250910185200: declared type 'volume', id 20250718080859 resolves only as scan
[ok  ] pixel-size-disagrees-with-scan #1381      0  volume pixel_size_um differs from the scan it was derived from
[ok  ] segment-dims-disagree        —          0  properties.width/height disagree with creation.metadata width/height
[FAIL] segment-predates-source      #1730     20  segment is dated before the scan its source volume was reconstructed from
           PHerc0814/20250928235954: scan 20251206184543 is 68 days newer than the segment
           PHerc0139/20250223000000: scan 20251205005141 is 285 days newer than the segment
           PHerc0139/20250108000004: scan 20251205005141 is 331 days newer than the segment
           PHerc0139/20250831000000: scan 20251205005141 is 96 days newer than the segment
           PHerc0139/20250108000002: scan 20251205005141 is 331 days newer than the segment
           PHerc0139/20250108000005: scan 20251205005141 is 331 days newer than the segment
           PHerc0139/20250108000003: scan 20251205005141 is 331 days newer than the segment
           PHerc0139/20250108000000: scan 20251205005141 is 331 days newer than the segment
           ... 12 more (use --verbose)
[ok  ] segment-volume-dangling      #1649      0  segment.original_volume_id is not a volume published for that sample
[ok  ] transform-target-dangling    —          0  properties.transforms[].to_volume_id does not resolve to a published volume
[ok  ] volume-scan-dangling         —          0  volume.scan_id does not resolve to a scan in the same sample
[FAIL] volume-shape-null            #1516      4  volumes publish properties.shape: null despite a level-0 .zarray shape
           PHerc0500P2/20250526151718: properties.shape is null
           PHerc0500P2/20250528085330: properties.shape is null
           PHerc0500P2/20250820143440: properties.shape is null
           PHerc0343P/20250521134555: properties.shape is null

463 finding(s) across 13 check(s)
```
