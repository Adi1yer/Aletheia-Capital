# Workflow Reliability Enhancement: External Scheduler + Fallback Watchdog

## Overview

This enhancement makes daily trading workflows resilient to GitHub Actions schedule delays through a two-tier system:

1. **Primary (Recommended)**: External scheduler triggering `repository_dispatch`
2. **Fallback**: Internal GitHub Actions watchdog (also subject to delays)

The internal watchdog provides some resilience, but because it also uses GitHub Actions cron, it suffers from the same 5–14 hour delays. **For production reliability, configure the external scheduler.**

All existing gates (market window checks, same-day idempotency) remain active to prevent double-runs.

## What Changed

### Workflows Enhanced

- `daily-wheel-scan.yml` (Daily Wheel Scan & Rebalance)
- `wheel-options-daily.yml` (Wheel Options Daily Manage)
- `drip-daily-snapshot.yml` (Growth-Income-Drip Daily Snapshot)

### New Components

1. **Repository Dispatch Triggers**: Added to all three workflows
   - `trigger-daily-wheel-scan`
   - `trigger-wheel-options-daily`
   - `trigger-drip-daily-snapshot`
   - Can be triggered by external cron services (not subject to GitHub delays)
   - Can be triggered by the internal watchdog (as fallback)

2. **Fallback Watchdog Workflow**: `.github/workflows/daily-workflows-watchdog.yml`
   - Runs at 14:40, 16:10, 17:40, 19:10 UTC (staggered during market hours)
   - Checks if each workflow completed successfully today
   - Auto-dispatches missed workflows still within market windows
   - **Limitation**: Also uses GitHub Actions cron, subject to same delays
   - Sends email notifications only on failures or irrecoverable misses

3. **Dispatch Script**: `scripts/dispatch_missed_workflows.py`
   - Core watchdog logic: check → dispatch → notify
   - Respects all existing gates (market window, holidays, same-day markers)
   - Uses `gh` CLI for repository_dispatch triggers
   - Uses `GITHUB_TOKEN` which **can** trigger repository_dispatch (workflows triggered by repository_dispatch do not create recursive workflow runs, per [GitHub documentation](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#repository_dispatch))

## Setup Required by Aditya

### Primary (Recommended): External Scheduler

**This is the recommended approach** because external cron services are not subject to GitHub Actions delays.

#### Option A: Using cron-job.org (Recommended)

1. **Create a GitHub Fine-Grained Personal Access Token**:
   - Go to: https://github.com/settings/personal-access-tokens/new
   - Name: `Workflow Dispatcher Token`
   - Expiration: 1 year (or longer)
   - Repository access: Select this repository only
   - Permissions:
     - **Actions**: Read and write
   - Click "Generate token" and **copy it immediately**

2. **Configure cron-job.org**:
   - Sign up at https://cron-job.org (free tier is sufficient)
   - Create three jobs:

   **Job 1: Daily Wheel Scan**
   - Title: `Daily Wheel Scan Primary Trigger`
   - URL: `https://api.github.com/repos/OWNER/REPO/dispatches`
   - Schedule: `30 13 * * 1-5` (8:30 AM EDT / 9:30 AM EST, Mon-Fri)
   - Request Method: `POST`
   - Request Headers:
     ```
     Authorization: Bearer YOUR_PAT_TOKEN_HERE
     Accept: application/vnd.github+json
     X-GitHub-Api-Version: 2022-11-28
     ```
   - Request Body:
     ```json
     {"event_type":"trigger-daily-wheel-scan"}
     ```

   **Job 2: Wheel Options Daily Manage**
   - Title: `Wheel Options Primary Trigger`
   - URL: `https://api.github.com/repos/OWNER/REPO/dispatches`
   - Schedule: `0 16 * * 1-5` (11:00 AM EDT / 12:00 PM EST, Mon-Fri)
   - Same headers as above
   - Request Body:
     ```json
     {"event_type":"trigger-wheel-options-daily"}
     ```

   **Job 3: Growth-Income-Drip Daily Snapshot**
   - Title: `Drip Daily Snapshot Primary Trigger`
   - URL: `https://api.github.com/repos/OWNER/REPO/dispatches`
   - Schedule: `0 14 * * 1-5` (9:00 AM EDT / 10:00 AM EST, Mon-Fri)
   - Same headers as above
   - Request Body:
     ```json
     {"event_type":"trigger-drip-daily-snapshot"}
     ```

3. **Test the Setup**:
   ```bash
   # Replace YOUR_PAT and OWNER/REPO
   curl -X POST \
     -H "Authorization: Bearer YOUR_PAT" \
     -H "Accept: application/vnd.github+json" \
     -H "X-GitHub-Api-Version: 2022-11-28" \
     https://api.github.com/repos/OWNER/REPO/dispatches \
     -d '{"event_type":"trigger-daily-wheel-scan"}'
   
   # Check if workflow started:
   gh run list --workflow=daily-wheel-scan.yml --limit 5
   ```

#### Option B: Manual Dispatch via GitHub CLI

You can manually trigger any workflow on-demand:

```bash
# Dispatch wheel scan
gh api repos/OWNER/REPO/dispatches -X POST -f event_type=trigger-daily-wheel-scan

# Dispatch options manage
gh api repos/OWNER/REPO/dispatches -X POST -f event_type=trigger-wheel-options-daily

# Dispatch drip snapshot
gh api repos/OWNER/REPO/dispatches -X POST -f event_type=trigger-drip-daily-snapshot
```

Or use the GitHub UI:
- Go to Actions → Select workflow → Run workflow

## How It Works

### Two-Tier Defense

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: External Cron → repository_dispatch (Primary)│
│  • Independent trigger from external service           │
│  • NOT affected by GitHub Actions delays               │
│  • cron-job.org or similar external scheduler          │
│  • Reliable, deterministic timing                      │
└─────────────────────────────────────────────────────────┘
                         ↓ (if fails or not configured)
┌─────────────────────────────────────────────────────────┐
│  Layer 2: GitHub Cron Watchdog (Fallback)              │
│  • Runs at 14:40, 16:10, 17:40, 19:10 UTC             │
│  • Checks "already ran" markers                        │
│  • Checks market window                                │
│  • Auto-dispatches if missed & viable                  │
│  • ⚠️ ALSO subject to GitHub Actions delays            │
│  • Email only on failures or irrecoverable misses      │
└─────────────────────────────────────────────────────────┘
```

**Note**: The GitHub Cron slots in the individual workflows (5 for wheel, 5 for drip, 4 for options) remain as additional fallback layers, but are also subject to delays.

### Why External Scheduler is Primary

The internal watchdog and existing GitHub cron slots **all use GitHub Actions schedule triggers**, which means they all suffer from the same 5–14 hour delays that caused the original problem.

**External cron services** (like cron-job.org) run independently and are not subject to GitHub's delays, making them the most reliable trigger mechanism.

### repository_dispatch and GITHUB_TOKEN

The `repository_dispatch` event is explicitly exempt from GitHub's workflow recursion rules. Per [GitHub documentation](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#repository_dispatch):

> Workflows triggered by `repository_dispatch` do not create recursive workflow runs.

This means:
- External scheduler can trigger via PAT → works ✓
- Internal watchdog can trigger via `GITHUB_TOKEN` → works ✓
- No risk of infinite loops or recursion

### Gate Protection (Prevents Double-Runs)

Every trigger path goes through these gates:

1. **Holiday Gate**: Is today an NYSE trading day?
2. **Market Window Gate**: Are we within the workflow's execution window?
3. **Same-Day Idempotency Gate**: Did this workflow already run successfully today?
4. **Money-Path-Inert Gate** (NEW): For wheel/options workflows only:
   - Is the workflow enabled in the registry?
   - Is `ENABLE_PUT_OPERATIONS` set to block CSP opens?
   - Is `ENABLE_COVERED_CALLS` set to block CC opens?

These gates are checked for:
- GitHub cron triggers
- repository_dispatch triggers
- workflow_dispatch (manual) triggers
- Watchdog-initiated triggers

**Result**: Multiple simultaneous triggers are safe. Only one will execute. Money-path workflows (wheel Scan, options Manage) will NOT dispatch when disabled or when board puts NO-GO or CC HOLD gates are active.

## Money-Path-Inert Safety

**Critical**: The watchdog will NOT dispatch wheel Scan or options Manage workflows when:

1. **Workflow disabled in registry**: The workflow account is marked disabled
2. **Puts NO-GO gate active**: `ENABLE_PUT_OPERATIONS` env var is unset, "0", or "false"
3. **CC HOLD gate active**: `ENABLE_COVERED_CALLS` env var is unset, "0", or "false"

This ensures the watchdog cannot accidentally trigger money-path workflows during board holds or when workflows are intentionally disabled. Drip workflow (no options trading) is not affected by puts/CC gates.

When a workflow is blocked by these gates, the watchdog:
- Skips dispatch with a clear reason logged
- Sends email notification explaining which gate blocked it
- Continues checking other workflows normally

**Example**: If you set `ENABLE_PUT_OPERATIONS=0` in repository secrets to block CSP opens, the watchdog will not dispatch wheel Scan or options Manage, even if they missed their cron slots.

## Testing

### Test Watchdog Locally

```bash
# Dry-run check (no actual dispatch)
poetry run python scripts/dispatch_missed_workflows.py \
  --repo "OWNER/REPO" \
  --dry-run

# Force check specific workflow (ignore already-ran marker)
poetry run python scripts/dispatch_missed_workflows.py \
  --repo "OWNER/REPO" \
  --force-wheel \
  --dry-run
```

### Test Gates

```bash
# Run gate tests
poetry run pytest tests/test_workflow_gates.py -v

# Test market window check
poetry run python scripts/check_market_window.py --workflow wheel

# Test already-ran check
poetry run python scripts/should_run_daily_scan.py --check-already-ran --track wheel
```

### Test Repository Dispatch (Manual)

```bash
# Trigger a workflow manually
gh api repos/OWNER/REPO/dispatches \
  -X POST \
  -f event_type=trigger-daily-wheel-scan

# Watch for the run to start
gh run watch
```

## Monitoring

### Check Watchdog Status

```bash
# View recent watchdog runs
gh run list --workflow=daily-workflows-watchdog.yml --limit 10

# View watchdog logs
gh run view --workflow=daily-workflows-watchdog.yml --log
```

### Check Workflow Status

```bash
# Check if today's workflows ran
poetry run python scripts/should_run_daily_scan.py --check-already-ran --track wheel
poetry run python scripts/should_run_daily_scan.py --check-already-ran --track options
poetry run python scripts/should_run_daily_scan.py --check-already-ran --track drip
```

### Email Notifications

The watchdog sends email notifications **only on failures**:
- Workflows that were missed and **outside** recovery window (cannot be recovered)
- Workflows that were missed and dispatch **failed**

**No email is sent** when:
- Workflows already completed successfully
- Workflows were missed but successfully auto-dispatched

Recipients: Uses existing `RECIPIENT_EMAIL` secret

## Troubleshooting

### Watchdog Not Dispatching

1. Check if workflow already ran:
   ```bash
   poetry run python scripts/should_run_daily_scan.py \
     --check-already-ran --track wheel
   ```

2. Check market window:
   ```bash
   poetry run python scripts/check_market_window.py --workflow wheel
   ```

3. Force manual dispatch:
   ```bash
   gh workflow run daily-workflows-watchdog.yml \
     -f force_check_wheel=true
   ```

### Repository Dispatch Not Working

1. Verify token permissions:
   - Token must have `actions:write` scope
   - Token must be valid and not expired

2. Check API call:
   ```bash
   curl -X POST \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Accept: application/vnd.github+json" \
     https://api.github.com/repos/OWNER/REPO/dispatches \
     -d '{"event_type":"trigger-daily-wheel-scan"}' \
     -v
   ```

3. Check workflow runs:
   ```bash
   gh run list --workflow=daily-wheel-scan.yml --limit 5
   ```

### Double-Run Concerns

**This cannot happen.** Every execution path checks:
- Already-ran marker (`wheel_daily_completed_et.txt`, etc.)
- If marker exists for today → skip execution

To verify gate behavior:
```bash
# Run tests
poetry run pytest tests/test_workflow_gates.py::test_same_day_idempotency -v
```

## Architecture Notes

### Why This Approach?

**Problem**: GitHub Actions cron triggers delay 5–14 hours on free tier.

**Solution**: Use external cron service (not subject to GitHub delays) as primary trigger.

**Evaluated Options**:
1. ✓ **External repository_dispatch + internal watchdog fallback** (CHOSEN)
   - External trigger: reliable, not subject to GitHub delays
   - Internal watchdog: provides fallback (but also subject to delays)
   - repository_dispatch: exempt from recursion rules, safe for watchdog to use
   - Maximum reliability

2. ✗ Watchdog only (internal GitHub cron)
   - Subject to same delays as the problem it's trying to solve
   - Not a real solution

3. ✗ More GitHub cron slots only
   - Already tried (5+ slots), still delays

### Benefits

- **External Primary**: Not affected by GitHub Actions delays
- **Self-Healing Fallback**: Internal watchdog attempts recovery
- **Safe**: All existing gates prevent double-runs
- **Observable**: Email notifications (failures only) + GitHub Actions logs
- **Flexible**: Can use any external cron service
- **Non-Invasive**: No changes to trading logic

### Workflow Windows

| Workflow | GitHub Cron Slots | Watchdog Checks (UTC) | Watchdog Checks (EDT/EST) | Market Cutoff |
|----------|-------------------|----------------------|---------------------------|---------------|
| Wheel Scan | 11:00-19:00 UTC (5 slots) | 14:40, 16:10, 17:40, 19:10 | 10:40a, 12:10p, 1:40p, 3:10p / 9:40a, 11:10a, 12:40p, 2:10p | 15:30 ET |
| Options Manage | 14:00-20:00 UTC (4 slots) | 14:40, 16:10, 17:40, 19:10 | 10:40a, 12:10p, 1:40p, 3:10p / 9:40a, 11:10a, 12:40p, 2:10p | 15:55 ET |
| Drip Snapshot | 12:00-20:00 UTC (5 slots) | 14:40, 16:10, 17:40, 19:10 | 10:40a, 12:10p, 1:40p, 3:10p / 9:40a, 11:10a, 12:40p, 2:10p | 16:00 ET |

**Note**: Watchdog times work for both EDT (Mar-Nov, UTC-4) and EST (Nov-Mar, UTC-5), ensuring all checks occur before the earliest cutoff (3:10p EDT / 2:10p EST < 3:30p ET wheel cutoff).
