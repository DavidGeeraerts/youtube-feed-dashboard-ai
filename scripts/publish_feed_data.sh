#!/usr/bin/env bash
# Commit assets/data and push it onto the latest origin branch.
#
# The job may have checked out an older SHA. This rebases that data commit
# onto origin/<branch> and retries the push. A conflict, or a rebase that
# leaves JSON invalid, is resolved by checking out the upstream tip and
# running the feed fetch again so stored days and the fresh fetch are merged.
#
# Usage: publish_feed_data.sh <branch> [remote]
# Writes sha=<commit> to $GITHUB_OUTPUT when that variable is set.

set -euo pipefail

branch="${1:?branch name required}"
remote="${2:-origin}"
max_attempts="${PUBLISH_MAX_ATTEMPTS:-4}"
retry_sleep="${PUBLISH_RETRY_SLEEP:-2}"

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

write_sha() {
  local sha
  sha="$(git rev-parse HEAD)"
  echo "Feed data commit: ${sha}"
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "sha=${sha}" >> "${GITHUB_OUTPUT}"
  fi
}

json_is_valid() {
  python3 - << 'PY'
import json
import pathlib
import sys

root = pathlib.Path("assets/data")
ok = True
if root.exists():
    for path in root.rglob("*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"invalid JSON after rebase: {path}: {exc}", file=sys.stderr)
            ok = False
sys.exit(0 if ok else 1)
PY
}

commit_if_needed() {
  git add -- assets/data
  if git diff --staged --quiet; then
    return 2
  fi
  git commit -m "Update YouTube feed data"
}

rebase_in_progress() {
  [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]
}

# Drop a conflicted rebase, move to the upstream tip, and fetch again.
# fetch_feeds.py merges the new feed into the day files already on that tip.
regenerate() {
  git rebase --abort >/dev/null 2>&1 || true
  git reset --hard "${remote}/${branch}"
  python3 scripts/fetch_feeds.py
  commit_if_needed
}

run_regenerate() {
  set +e
  regenerate
  local status=$?
  set -e
  if [ "${status}" -eq 2 ]; then
    return 2
  fi
  if [ "${status}" -ne 0 ]; then
    exit "${status}"
  fi
  return 0
}

run_commit() {
  set +e
  commit_if_needed
  local status=$?
  set -e
  if [ "${status}" -eq 2 ]; then
    return 2
  fi
  if [ "${status}" -ne 0 ]; then
    exit "${status}"
  fi
  return 0
}

current="$(git rev-parse --abbrev-ref HEAD)"
if [ "${current}" != "${branch}" ]; then
  git checkout -B "${branch}"
fi

if ! run_commit; then
  echo "No data changes to commit."
  write_sha
  exit 0
fi

attempt=1
while [ "${attempt}" -le "${max_attempts}" ]; do
  git fetch "${remote}" "${branch}"
  if ! git pull --rebase "${remote}" "${branch}"; then
    if ! rebase_in_progress; then
      echo "git pull --rebase failed before a rebase started." >&2
      exit 1
    fi
    echo "Rebase onto ${remote}/${branch} conflicted; regenerating feed data."
    if ! run_regenerate; then
      echo "Upstream already has this feed data."
      write_sha
      exit 0
    fi
  elif ! json_is_valid; then
    echo "Rebase left invalid JSON; regenerating feed data."
    if ! run_regenerate; then
      echo "Upstream already has this feed data."
      write_sha
      exit 0
    fi
  fi

  if git push "${remote}" "HEAD:${branch}"; then
    write_sha
    exit 0
  fi

  echo "Push rejected (attempt ${attempt} of ${max_attempts}); retrying."
  attempt=$((attempt + 1))
  if [ "${attempt}" -le "${max_attempts}" ] && [ "${retry_sleep}" != "0" ]; then
    sleep $((attempt * retry_sleep))
  fi
done

echo "Failed to push feed data to ${remote}/${branch}." >&2
exit 1
