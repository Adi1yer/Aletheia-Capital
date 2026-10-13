# Workflow Reliability Setup - Quick Start for Aditya

## ✅ What's Already Working (Zero Setup Required)

The **self-healing watchdog** is now active and requires no setup:

- Monitors all three daily workflows automatically
- Auto-dispatches missed runs within market windows
- Sends email notifications using existing secrets
- **You don't need to do anything for this to work**

## 📋 Optional: External Scheduler for Maximum Reliability

For ultimate reliability, you can add an external cron service as a backup:

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
   - **Title**: `Daily Wheel Scan Backup Trigger`
   - **URL**: `https://api.github.com/repos/Adi1yer/Aletheia-Capital/dispatches`
   - **Schedule**: `30 13 * * 1-5` (8:30/9:30 AM ET, Mon-Fri)
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
   - **Title**: `Wheel Options Backup Trigger`
   - **URL**: `https://api.github.com/repos/Adi1yer/Aletheia-Capital/dispatches`
   - **Schedule**: `0 16 * * 1-5` (11:00 AM/12:00 PM ET, Mon-Fri)
   - **Request Method**: `POST`
   - **Same headers as Job 1**
   - **Request Body**:
     ```json
     {"event_type":"trigger-wheel-options-daily"}
     ```

4. Create **Job 3: Growth-Income-Drip Daily Snapshot**
   - **Title**: `Drip Daily Snapshot Backup Trigger`
   - **URL**: `https://api.github.com/repos/Adi1yer/Aletheia-Capital/dispatches`
   - **Schedule**: `0 14 * * 1-5` (9:00/10:00 AM ET, Mon-Fri)
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

## 🛡️ Safety Guarantees

**Double-runs are impossible** because all triggers (cron, watchdog, external) check:
1. Is today an NYSE trading day?
2. Are we within the workflow's execution window?
3. Did this workflow already run successfully today?

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

- **Minimum**: Do nothing — watchdog works automatically
- **Recommended**: Add external cron for maximum reliability (15 minutes setup)
- **Safety**: All gates prevent double-runs regardless of trigger source
- **Monitoring**: Email notifications + GitHub Actions logs

Full documentation: `docs/workflow-reliability-setup.md`
