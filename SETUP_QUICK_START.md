# Workflow Reliability Setup - Quick Start for Aditya

## ⚠️ Important: Watchdog Limitation

The internal **watchdog also uses GitHub Actions cron**, so it suffers from the same 5–14 hour delays as the workflows it monitors. It provides a fallback layer, but **for production reliability, configure the external scheduler**.

## 📋 Primary (Recommended): External Scheduler

External cron services (like cron-job.org) are **not affected by GitHub Actions delays**, making them the most reliable solution.

### Step 1: Create GitHub Fine-Grained PAT

1. Visit: https://github.com/settings/personal-access-tokens/new
2. Configure:
   - **Name**: `Workflow Dispatcher Token`
   - **Expiration**: 1 year
   - **Repository access**: Only select `Adi1yer/Aletheia-Capital`
   - **Permissions**: 
     - Actions: **Read and write**
3. Click **Generate token** and **copy it immediately** (you won't see it again)

### Step 2: Configure cron-job.org

1. Sign up at https://cron-job.org (free tier works)

2. Create **Job 1: Daily Wheel Scan**
   - **Title**: `Daily Wheel Scan Primary Trigger`
   - **URL**: `https://api.github.com/repos/Adi1yer/Aletheia-Capital/dispatches`
   - **Schedule**: `30 13 * * 1-5` (8:30 AM EDT / 9:30 AM EST, Mon-Fri)
   - **Request Method**: `POST`
   - **Request Headers**:
     ```
     Authorization: Bearer YOUR_PAT_TOKEN_HERE
     Accept: application/vnd.github+json
     X-GitHub-Api-Version: 2022-11-28
     ```
   - **Request Body**:
     ```json
     {"event_type":"trigger-daily-wheel-scan"}
     ```

3. Create **Job 2: Wheel Options Daily Manage**
   - **Title**: `Wheel Options Primary Trigger`
   - **URL**: `https://api.github.com/repos/Adi1yer/Aletheia-Capital/dispatches`
   - **Schedule**: `0 16 * * 1-5` (11:00 AM EDT / 12:00 PM EST, Mon-Fri)
   - **Request Method**: `POST`
   - **Same headers as Job 1**
   - **Request Body**:
     ```json
     {"event_type":"trigger-wheel-options-daily"}
     ```

4. Create **Job 3: Growth-Income-Drip Daily Snapshot**
   - **Title**: `Drip Daily Snapshot Primary Trigger`
   - **URL**: `https://api.github.com/repos/Adi1yer/Aletheia-Capital/dispatches`
   - **Schedule**: `0 14 * * 1-5` (9:00 AM EDT / 10:00 AM EST, Mon-Fri)
   - **Request Method**: `POST`
   - **Same headers as Job 1**
   - **Request Body**:
     ```json
     {"event_type":"trigger-drip-daily-snapshot"}
     ```

### Step 3: Test the Setup

```bash
# Test manually with your PAT
curl -X POST \
  -H "Authorization: Bearer YOUR_PAT" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/Adi1yer/Aletheia-Capital/dispatches \
  -d '{"event_type":"trigger-daily-wheel-scan"}'

# Check if workflow started
gh run list --workflow=daily-wheel-scan.yml --limit 5
```

## 🔄 Fallback: Internal Watchdog

An internal watchdog runs at 14:40, 16:10, 17:40, and 19:10 UTC as a fallback layer:
- Monitors all three workflows
- Auto-dispatches missed runs still within market windows
- Sends email notifications **only on failures**
- **Limitation**: Also uses GitHub Actions cron, subject to same delays

This provides some resilience, but **external scheduler is still recommended for production reliability**.

## 📋 Technical Notes

### repository_dispatch and GITHUB_TOKEN

Per [GitHub documentation](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#repository_dispatch), workflows triggered by `repository_dispatch` **do not create recursive workflow runs**. This means:
- External scheduler can trigger via PAT → ✓ works
- Internal watchdog can trigger via `GITHUB_TOKEN` → ✓ works  
- No risk of infinite loops

### Email Notifications

Emails are sent **only on failures**:
- Workflow missed and outside recovery window
- Workflow missed and dispatch failed

**No email** when workflows succeed or are successfully auto-dispatched.

## 🛡️ Safety Guarantees

**Double-runs are impossible** because all triggers (cron, watchdog, external) check:
1. Is today an NYSE trading day?
2. Are we within the workflow's execution window?
3. Did this workflow already run successfully today?
4. **NEW**: For wheel/options only: Is the workflow enabled and are board gates open?

**Money-path-inert protection**: The watchdog will NOT dispatch wheel Scan or options Manage when:
- Workflow is disabled in the registry
- `ENABLE_PUT_OPERATIONS` is not set (puts NO-GO gate)
- `ENABLE_COVERED_CALLS` is not set (CC HOLD gate)

This ensures the watchdog cannot accidentally fire money-path workflows during board holds.

If any check fails → workflow skips execution.

## 📊 Monitoring

Check if workflows ran today:
```bash
poetry run python scripts/should_run_daily_scan.py --check-already-ran --track wheel
poetry run python scripts/should_run_daily_scan.py --check-already-ran --track options
poetry run python scripts/should_run_daily_scan.py --check-already-ran --track drip
```

View watchdog activity:
```bash
gh run list --workflow=daily-workflows-watchdog.yml --limit 10
```

## 🎯 Summary

- **Recommended**: Set up external cron (15 minutes) — not subject to GitHub delays
- **Fallback**: Internal watchdog provides backup (but also subject to delays)
- **Safety**: All gates prevent double-runs regardless of trigger source
- **Monitoring**: Email notifications (failures only) + GitHub Actions logs

Full documentation: `docs/workflow-reliability-setup.md`
