# Deterministic Alignment Offset Contract

## Finding

`deterministic_promote_and_align()` translates raw planView coordinates into
the manual-reference CRS. The current map-of-record has a nonzero source
header offset:

```text
x = 832671.676 m
y = 5458671.104 m
hdg = 0
```

The previous implementation rejected that map unless an environment override
was set. That override was unsafe: it retained the source X/Y offset in an
output whose geometry had already been translated into the target CRS, so a
consumer applying the header offset would shift it a second time.

## Contract

For translation-only deterministic alignment:

1. Parse finite source header offset values; malformed values fail closed.
2. Reject nonzero header rotation because this implementation does not rotate
   planView coordinates.
3. Translate planView geometry into the target CRS.
4. Write the target CRS to `<header><geoReference>`.
5. Reset output header X/Y offset to zero.
6. Refresh output header bounds and remove source geometry-freeze attestation,
   because transformed geometry is not the frozen source artifact.

Z offset remains unchanged because this operation does not transform vertical
coordinates.

## Governed Offline Probe

The pinned map was read without modification and produced a disposable derived
artifact. Its output had target Grid0828 georeference, zero X/Y offset, no
freeze attestation, and 197,397 translated geometry starts. The derived file
was removed after inspection.

The real Grid0828 bbox overlap check passed. This proves the new horizontal
frame contract and its bounded overlap condition only. It does not certify the
resulting derived artifact for CARLA or establish any thesis metric.

## Verification

- Focused alignment, registration, and geo-alignment tests: `51 passed`.
- Full non-sparse offline suite: `5949 passed, 82 skipped, 0 failed`.
- No CARLA process or RPC was used.
- The map-of-record remained SHA256
  `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798`.
