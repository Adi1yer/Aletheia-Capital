# Workflow Reliability Enhancement: Watchdog & External Trigger System

## Overview

This enhancement makes daily trading workflows resilient to GitHub Actions schedule delays through a three-tier reliability system:

1. **Primary**: Multiple staggered cron slots (already present, preserved)
2. **Secondary**: Auto-dispatching watchdog that monitors and recovers missed runs
3. **Tertiary**: `repository_dispatch` triggers for external schedulers (optional)

All existing gates (market window checks, same-day idempotency) remain active to prevent double-runs.

## What Changed

### Workflows Enhanced

- `daily-wheel-scan.yml` (Daily Wheel Scan & Rebalance)
- `wheel-options-daily.yml` (Wheel Options Daily Manage)
- `drip-daily-snapshot.yml` (Growth-Income-Drip Daily Snapshot)

### New Components

1. **Watchdog Workflow**: `.github/workflows/daily-workflows-watchdog.yml`
   - Runs at 19:00 and 21:00 UTC (2-3 PM and 4-5 PM ET)
   - Checks if each workflow completed successfully today
   - Auto-dispatches any missed workflows still within market windows
   - Sends email notifications

2. **Dispatch Script**: `scripts/dispatch_missed_workflows.py`
   - Core watchdog logic: check → dispatch → notify
   - Respects all existing gates (market window, holidays, same-day markers)
   - Uses `gh` CLI for repository_dispatch triggers

3. **Repository Dispatch Triggers**: Added to all three workflows
   - `trigger-daily-wheel-scan`
   - `trigger-wheel-options-daily`
   - `trigger-drip-daily-snapshot`

## Setup Required by Aditya

### 1. No Setup Required for Watchdog (Auto-Healing)

The watchdog runs automatically and requires no setup:
- It uses the existing `GITHUB_TOKEN` (automatic)
- Email notifications use existing secrets (`RECIPIENT_EMAIL`, `SMTP_*`)
- It's already configured in the workflows

**The system is now self-healing by default.**

### 2. Optional: External Scheduler for Ultimate Reliability

For maximum reliability, you can add an external cron service as a backup trigger.

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
   - Title: `Daily Wheel Scan Backup Trigger`
   - URL: `https://api.github.com/repos/OWNER/REPO/dispatches`
   - Schedule: `30 13 * * 1-5` (8:30/9:30 AM ET, Mon-Fri)
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
   - Title: `Wheel Options Backup Trigger`
   - URL: `https://api.github.com/repos/OWNER/REPO/dispatches`
   - Schedule: `0 16 * * 1-5` (11:00 AM/12:00 PM ET, Mon-Fri)
   - Same headers as above
   - Request Body:
     ```json
     {"event_type":"trigger-wheel-options-daily"}
     ```

   **Job 3: Growth-Income-Drip Daily Snapshot**
   - Title: `Drip Daily Snapshot Backup Trigger`
   - URL: `https://api.github.com/repos/OWNER/REPO/dispatches`
   - Schedule: `0 14 * * 1-5` (9:00/10:00 AM ET, Mon-Fri)
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

### Multi-Layer Defense

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: Multiple GitHub Cron Slots (Primary)         │
│  • 5 slots for wheel (11:00-19:00 UTC)                 │
│  • 5 slots for drip (12:00-20:00 UTC)                  │
│  • 4 slots for options (14:00-20:00 UTC)               │
└─────────────────────────────────────────────────────────┘
                         ↓ (if all fail)
┌─────────────────────────────────────────────────────────┐
│  Layer 2: Watchdog Auto-Dispatch (Secondary)           │
│  • Runs at 19:00 and 21:00 UTC                         │
│  • Checks "already ran" markers                        │
│  • Checks market window                                │
│  • Auto-dispatches if missed & viable                  │
│  • Sends email notification                            │
└─────────────────────────────────────────────────────────┘
                         ↓ (if still fails)
┌─────────────────────────────────────────────────────────┐
│  Layer 3: External Cron (Optional Tertiary)            │
│  • Independent trigger from external service           │
│  • Not affected by GitHub Actions delays               │
│  • Falls back to same gates (no double-runs)           │
└─────────────────────────────────────────────────────────┘
```

### Gate Protection (Prevents Double-Runs)

Every trigger path goes through these gates:

1. **Holiday Gate**: Is today an NYSE trading day?
2. **Market Window Gate**: Are we within the workflow's execution window?
3. **Same-Day Idempotency Gate**: Did this workflow already run successfully today?

These gates are checked for:
- GitHub cron triggers
- repository_dispatch triggers
- workflow_dispatch (manual) triggers
- Watchdog-initiated triggers

**Result**: Multiple simultaneous triggers are safe. Only one will execute.

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

The watchdog sends email notifications for:
- Workflows that were missed and auto-dispatched
- Workflows that were missed but outside recovery window

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

**Evaluated Options**:
1. ✓ **Watchdog + repository_dispatch** (CHOSEN)
   - Self-contained, auto-healing
   - No external dependencies required
   - External trigger available as optional backup
   - Maximum reliability without complexity

2. ✗ Repository dispatch only with required external cron
   - Adds external dependency
   - Requires token management
   - Not self-healing

### Benefits

- **Zero Configuration**: Works out of the box with watchdog
- **Self-Healing**: Automatically recovers from GitHub delays
- **Safe**: All existing gates prevent double-runs
- **Observable**: Email notifications + GitHub Actions logs
- **Flexible**: Optional external trigger for ultimate control
- **Non-Invasive**: No changes to trading logic

### Workflow Windows

| Workflow | Primary Slots | Watchdog Checks | Market Cutoff |
|----------|---------------|-----------------|---------------|
| Wheel Scan | 11:00-19:00 UTC | 19:00, 21:00 UTC | 15:30 ET |
| Options Manage | 14:00-20:00 UTC | 19:00, 21:00 UTC | 15:55 ET |
| Drip Snapshot | 12:00-20:00 UTC | 19:00, 21:00 UTC | 16:00 ET |

The watchdog runs between primary slots and cutoff times, providing recovery window without risking late execution.
