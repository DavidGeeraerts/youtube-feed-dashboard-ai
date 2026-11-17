#!/usr/bin/env bash
# Local git simulation of the feed-data push. No network and no YouTube.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
publish="${root}/scripts/publish_feed_data.sh"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

git_quiet() {
  local repo="$1"
  shift
  git -C "${repo}" -c user.name="Test" -c user.email="test@example.com" "$@"
}

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_eq() {
  local actual="$1"
  local expected="$2"
  local label="$3"
  if [ "${actual}" != "${expected}" ]; then
    fail "${label}: expected [${expected}] got [${actual}]"
  fi
}

# origin starts at an older main. The clone commits new feed data from that
# base while origin gains both a docs commit and a conflicting day file.
setup_repos() {
  local origin="$1"
  local clone="$2"
  mkdir -p "${origin}" "${clone}"
  git_quiet "${origin}" init --bare -b main
  git_quiet "${clone}" init -b main
  git_quiet "${clone}" remote add origin "${origin}"
  mkdir -p "${clone}/assets/data" "${clone}/scripts"
  printf '%s\n' '{"marker":"base","days":["2026-11-01"]}' > "${clone}/assets/data/index.json"
  printf '%s\n' '# dashboard' > "${clone}/README.md"
  cat > "${clone}/scripts/fetch_feeds.py" << 'PY'
import json
import pathlib
path = pathlib.Path("assets/data/index.json")
path.write_text(json.dumps({"marker": "regenerated", "days": ["2026-11-01", "2026-11-02"]}) + "\n", encoding="utf-8")
print("regenerated feed data")
PY
  git_quiet "${clone}" add README.md assets scripts
  git_quiet "${clone}" commit -m "Initial dashboard"
  git_quiet "${clone}" push origin main
}

test_rebase_non_data_commit() {
  local origin="${work}/origin-docs.git"
  local clone="${work}/clone-docs"
  setup_repos "${origin}" "${clone}"

  # Move origin forward without touching feed data.
  git_quiet "${clone}" checkout -B main
  printf '%s\n' 'docs only' >> "${clone}/README.md"
  git_quiet "${clone}" add README.md
  git_quiet "${clone}" commit -m "Update README"
  git_quiet "${clone}" push origin main

  # Stale checkout, as in a re-run of an older workflow SHA.
  git_quiet "${clone}" checkout -q HEAD~1
  printf '%s\n' '{"marker":"fresh","days":["2026-11-01","2026-11-09"]}' > "${clone}/assets/data/index.json"

  (
    cd "${clone}"
    PUBLISH_RETRY_SLEEP=0 bash "${publish}" main origin
  )

  local marker
  marker="$(git --git-dir="${origin}" show main:assets/data/index.json)"
  assert_eq "${marker}" '{"marker":"fresh","days":["2026-11-01","2026-11-09"]}' "docs race keeps the fresh feed file"
  git --git-dir="${origin}" show main:README.md | grep -q "docs only" || fail "rebase dropped the upstream README"
  echo "ok: rebase onto a non-data commit"
}

test_data_conflict_regenerates() {
  local origin="${work}/origin-data.git"
  local clone="${work}/clone-data"
  setup_repos "${origin}" "${clone}"

  printf '%s\n' '{"marker":"upstream","days":["2026-11-01","2026-11-02"]}' > "${clone}/assets/data/index.json"
  git_quiet "${clone}" add assets/data/index.json
  git_quiet "${clone}" commit -m "Update YouTube feed data"
  git_quiet "${clone}" push origin main

  git_quiet "${clone}" checkout -q HEAD~1
  printf '%s\n' '{"marker":"stale-fetch","days":["2026-11-01"]}' > "${clone}/assets/data/index.json"

  (
    cd "${clone}"
    PUBLISH_RETRY_SLEEP=0 bash "${publish}" main origin
  )

  local marker
  marker="$(git --git-dir="${origin}" show main:assets/data/index.json)"
  assert_eq "${marker}" '{"marker": "regenerated", "days": ["2026-11-01", "2026-11-02"]}' "conflict regenerates from upstream plus a new fetch"
  echo "ok: data conflict regenerates"
}

test_no_changes() {
  local origin="${work}/origin-noop.git"
  local clone="${work}/clone-noop"
  setup_repos "${origin}" "${clone}"
  local before after
  before="$(git --git-dir="${origin}" rev-parse main)"
  (
    cd "${clone}"
    PUBLISH_RETRY_SLEEP=0 bash "${publish}" main origin
  )
  after="$(git --git-dir="${origin}" rev-parse main)"
  assert_eq "${after}" "${before}" "clean tree does not push"
  echo "ok: no changes"
}

test_rebase_non_data_commit
test_data_conflict_regenerates
test_no_changes
echo "publish feed data tests passed"
