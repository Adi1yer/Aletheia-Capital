# Run profiles

Profiles merge defaults from [`config/run_profiles.json`](../config/run_profiles.json) into `run_config`.

```bash
poetry run python weekly_scan_rebalancing.py --run-profile dev-smoke --no-broker
poetry run python weekly_scan_rebalancing.py --run-profile ci-full --execute
```

| Profile | Tickers | Agents | Execute | Broker required |
|---------|---------|--------|---------|-----------------|
| `ci-full` | 500 | tiered | yes | yes |
| `dev-smoke` | 10 | core | no | no |
| `research` | 100 | tiered | no | no |

CLI flags override profile values after merge.
