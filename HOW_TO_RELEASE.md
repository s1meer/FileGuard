# How to release a FileGuard update

## Step 1 — Make your changes
Edit any .py file. Fix bugs. Add formats. Improve scanner.

## Step 2 — Bump the version
In updater.py, change CURRENT_VERSION = "1.0.0" to "1.1.0"

## Step 3 — Commit and tag
  git add .
  git commit -m "v1.1.0 — describe what changed"
  git tag v1.1.0
  git push origin main --tags

## Step 4 — GitHub builds automatically
GitHub Actions builds the Mac .app within ~5 minutes.

## Step 5 — All users get it
Next time any user opens FileGuard, they see the update banner.
