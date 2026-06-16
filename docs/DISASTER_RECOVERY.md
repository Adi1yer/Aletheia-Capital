# Disaster Recovery

## Scope

Recovery for:
- `data/scan_cache`
- `data/performance`
- policy/weights artifacts

## Recovery Steps

1. Restore latest `data/scan_cache` from remote backup (S3 if configured).
2. Restore `data/performance` (ledgers, calibration, policy artifacts).
3. Verify integrity checksums where available.
4. Run dry replay on the latest run ID.
5. Compare replay decision diff against baseline.
6. Resume scheduled workflows after operator sign-off.

## Rollback Policy

- Promote only from candidate artifacts with backup snapshot available.
- If post-promotion metrics regress, restore `policy_calibration.prev.*.json`.

