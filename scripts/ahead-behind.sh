#!/bin/bash
# git-ahead-behind - Check ahead/behind status for git repos and submodules
# Usage: git-ahead-behind [N] [OPTIONS] [REPO_PATH]...
# Options:
#   -n, --count N    Number of branches to show (default: 10)
#   --sort MODE      Sort branches by "divergence" or "newest" (default: divergence)
#   --newest         Shortcut for --sort newest
#   --base REF       Compare branches against REF instead of the repo default branch
#   --local-vs-origin Compare each branch against its configured upstream
#   --submodules     Include submodules in checks
#   -h, --help       Show this help message

# Show help if requested
show_help() {
  cat << 'EOF'
git-ahead-behind - Check ahead/behind status for git repos and submodules
Usage: git-ahead-behind [N] [OPTIONS] [REPO_PATH]...

Options:
  N                Positional shortcut for branch count, e.g. git-ahead-behind 5
  -n, --count N    Number of branches to show (default: 10)
  --sort MODE      Sort branches by "divergence" or "newest" (default: divergence)
  --newest         Shortcut for --sort newest
  --base REF       Compare branches against REF instead of the repo default branch.
                   Unqualified names like "main" or "dev" prefer origin/<name>
                   when available, matching GitHub-style branch comparison.
                   Examples: --base main, --base dev, --base origin/main
  --local-vs-origin
  --upstream
  --for-each       Compare each branch against its configured upstream.
                   This is the previous local-vs-origin behavior.
  --submodules     Include submodules in checks
  --exit-on-divergence
                   Exit 2 when any repo has a divergent branch (for CI gates).
                   Divergence alone exits 0 by default.
  -h, --help       Show this help message

Exit codes:
  0  Every repo was inspected successfully (drift may still be reported)
  1  At least one repo could not be inspected (not a repo root, fetch failed,
     base ref unresolvable) — the report is NOT a clean bill of health
  2  --exit-on-divergence was passed and at least one repo is divergent

Comparison behavior:
  Default mode compares every branch against the repo's GitHub default branch
  when available, then falls back to origin/HEAD, origin/dev, origin/main,
  dev, or main.

Examples:
  git-ahead-behind                     # Top 10 branches vs repo default branch
  git-ahead-behind 5                   # Top 5 branches vs repo default branch
  git-ahead-behind 5 --newest          # Top 5 newest branches vs repo default branch
  git-ahead-behind 5 --base main       # Top 5 branches compared against origin/main
  git-ahead-behind 5 --base dev        # Top 5 branches compared against origin/dev
  git-ahead-behind 5 --local-vs-origin # Old behavior: each branch vs its upstream
  git-ahead-behind --submodules        # Top 10 in current dir + all submodules
  git-ahead-behind -n 3 . Backend/     # Top 3 branches in current dir and Backend/
  git-ahead-behind Backend/ --submodules  # Backend + its submodules

Status Icons:
  ⬆️  Ahead of comparison branch/ref
  ⬇️  Behind comparison branch/ref
  🔄  Both ahead and behind
  ✅  Synced with comparison branch/ref
  ❓  No upstream configured, only relevant with --local-vs-origin
  ❌  Not a git repository
  ⚠️  Fetch failed
  💎  Working tree has uncommitted changes

PRs column:
  0 = no open PRs
  1 (#123) = one open PR
  1 (#123D) = one draft PR
  2 (#123,#124D) = multiple open/draft PRs
EOF
  exit 0
}

# Parse command line arguments
N=10
SORT_MODE="divergence"
COMPARE_MODE="base"
BASE_REF=""
SUBMODULES=false
EXIT_ON_DIVERGENCE=false
REPOS=()

# Resolved once per repo in the main loop, then reused by every branch lookup.
# Plain global (not an assoc array) so pipeline subshells inherit it.
REPO_BASE_REF=""
# Set whenever a comparison could not be computed; gates the "all up to date" line.
COUNT_ERRORS=0
GH_WARNED=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      show_help
      ;;
    -n|--count)
      if [[ $# -lt 2 ]]; then
        echo "Error: --count requires a numeric argument" >&2
        exit 1
      fi
      N="$2"
      if ! [[ "$N" =~ ^[0-9]+$ ]]; then
        echo "Error: --count must be a positive integer" >&2
        exit 1
      fi
      shift 2
      ;;
    --sort)
      if [[ $# -lt 2 ]]; then
        echo "Error: --sort requires one of: divergence, newest" >&2
        exit 1
      fi
      case "$2" in
        divergence|divergent)
          SORT_MODE="divergence"
          ;;
        newest|recent|date)
          SORT_MODE="newest"
          ;;
        *)
          echo "Error: Unknown sort mode '$2'. Use: divergence or newest" >&2
          exit 1
          ;;
      esac
      shift 2
      ;;
    --newest|--recent)
      SORT_MODE="newest"
      shift
      ;;
    --base)
      if [[ $# -lt 2 ]]; then
        echo "Error: --base requires a branch or ref argument" >&2
        exit 1
      fi
      COMPARE_MODE="base"
      BASE_REF="$2"
      shift 2
      ;;
    --local-vs-origin|--upstream|--for-each)
      COMPARE_MODE="upstream"
      shift
      ;;
    --submodules)
      SUBMODULES=true
      shift
      ;;
    --exit-on-divergence)
      EXIT_ON_DIVERGENCE=true
      shift
      ;;
    -*)
      echo "Error: Unknown option $1" >&2
      exit 1
      ;;
    *)
      if [[ "$1" =~ ^[0-9]+$ ]] && [[ "$N" == "10" ]] && [[ ${#REPOS[@]} -eq 0 ]]; then
        N="$1"
      else
        REPOS+=("$1")
      fi
      shift
      ;;
  esac
done

# Default to current directory if no repos specified
if [[ ${#REPOS[@]} -eq 0 ]]; then
  REPOS=(".")
fi

case "$SORT_MODE" in
  divergence)
    SORT_LABEL="divergence"
    ;;
  newest)
    SORT_LABEL="newest commit"
    ;;
esac

case "$COMPARE_MODE" in
  base)
    if [[ -n "$BASE_REF" ]]; then
      COMPARE_LABEL="$BASE_REF"
    else
      COMPARE_LABEL="default branch"
    fi
    ;;
  upstream)
    COMPARE_LABEL="each branch upstream"
    ;;
esac

# Function to resolve the repo default branch, preferring GitHub's configured default branch
resolve_default_base_ref() {
  local path="$1"
  local origin_head default_branch candidate

  if command -v gh >/dev/null 2>&1 && git -C "$path" remote get-url origin 2>/dev/null | grep -qi 'github.com'; then
    default_branch=$(cd "$path" && gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name' 2>/dev/null || echo "")
    if [[ -n "$default_branch" ]] && git -C "$path" rev-parse --verify "origin/$default_branch^{commit}" >/dev/null 2>&1; then
      echo "origin/$default_branch"
      return 0
    fi
    # An empty answer means auth/rate-limit failure, not "no default branch";
    # say so instead of silently changing the comparison basis below.
    if [[ -z "$default_branch" ]]; then
      echo "⚠️  gh repo view failed for $path; falling back to origin/HEAD guess" >&2
    fi
  fi

  origin_head=$(git -C "$path" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || echo "")
  if [[ -n "$origin_head" ]]; then
    echo "$origin_head"
    return 0
  fi

  for candidate in origin/dev origin/main dev main; do
    if git -C "$path" rev-parse --verify "$candidate^{commit}" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done

  echo ""
  return 1
}

# Function to normalize --base arguments like "main" to "origin/main" when available
normalize_base_ref() {
  local path="$1"
  local requested_ref="$2"

  if [[ -z "$requested_ref" ]]; then
    resolve_default_base_ref "$path"
    return
  fi

  # Explicit refs should be honored exactly as typed.
  case "$requested_ref" in
    HEAD|FETCH_HEAD|MERGE_HEAD|ORIG_HEAD|refs/*|*/*)
      if git -C "$path" rev-parse --verify "$requested_ref^{commit}" >/dev/null 2>&1; then
        echo "$requested_ref"
        return 0
      fi
      ;;
  esac

  # Unqualified branch names like "main" or "dev" should behave like GitHub:
  # prefer the remote branch when origin/<name> exists.
  if [[ "$requested_ref" != */* ]] && git -C "$path" rev-parse --verify "origin/$requested_ref^{commit}" >/dev/null 2>&1; then
    echo "origin/$requested_ref"
    return 0
  fi

  if git -C "$path" rev-parse --verify "$requested_ref^{commit}" >/dev/null 2>&1; then
    echo "$requested_ref"
    return 0
  fi

  if git -C "$path" rev-parse --verify "origin/$requested_ref^{commit}" >/dev/null 2>&1; then
    echo "origin/$requested_ref"
    return 0
  fi

  # Returning the unresolved name would make rev-list fail silently and the
  # "|| echo 0 0" fallback report a false 0↑ 0↓. Signal failure instead.
  echo ""
  return 1
}

# Function to resolve the compare ref for a repo, reusing the per-repo cache.
# Without the cache this fires one `gh repo view` per branch per repo.
resolve_compare_ref() {
  local path="$1"

  if [[ -n "$REPO_BASE_REF" ]]; then
    echo "$REPO_BASE_REF"
    return 0
  fi

  normalize_base_ref "$path" "$BASE_REF"
}

# Function to return the comparison label for a repo
get_compare_label() {
  local path="$1"
  local compare_ref

  if [[ "$COMPARE_MODE" == "upstream" ]]; then
    echo "upstream"
    return 0
  fi

  compare_ref=$(resolve_compare_ref "$path") || compare_ref=""
  if [[ -n "$compare_ref" ]]; then
    echo "$compare_ref"
  else
    echo "default branch"
  fi
}

# Function to get ahead/behind counts for a branch using the selected comparison mode
get_branch_counts() {
  local path="$1"
  local branch="$2"
  local upstream="$3"
  local compare_ref

  if [[ "$COMPARE_MODE" == "upstream" ]]; then
    if [[ -z "$upstream" ]]; then
      echo "0 0"
      return 0
    fi
    compare_ref="$upstream"
  else
    compare_ref=$(resolve_compare_ref "$path") || compare_ref=""
    if [[ -z "$compare_ref" ]]; then
      echo "WARN: base ref '${BASE_REF:-<repo default>}' does not resolve in $path" >&2
      COUNT_ERRORS=1
      # Numeric so callers doing $((ahead + behind)) still work; the non-zero
      # return is what distinguishes "cannot compute" from "identical".
      echo "0 0"
      return 1
    fi
  fi

  local counts
  if ! counts=$(git -C "$path" rev-list --left-right --count "$branch...$compare_ref" 2>/dev/null); then
    echo "WARN: cannot compare $branch...$compare_ref in $path" >&2
    COUNT_ERRORS=1
    echo "0 0"
    return 1
  fi
  printf '%s\n' "$counts"
}

# Function to process a single repository
process_repo() {
  local path="$1"
  local display_path="$2"
  local branch upstream counts ahead behind total dirty status_icon compare_label
  local toplevel rel mode

  # Check if path is a git repo
  if ! git -C "$path" rev-parse --git-dir >/dev/null 2>&1; then
    echo -e "$display_path\t❌ Not a git repo"
    return 1
  fi

  # An uninitialized submodule is an empty directory: git discovery walks UP and
  # silently resolves to the PARENT repo, so the parent's branches get reported
  # under the submodule's heading. Detect it via the 160000 gitlink so ordinary
  # subdirectory arguments (which also aren't repo roots) still work.
  toplevel=$(git -C "$path" rev-parse --show-toplevel 2>/dev/null)
  if [[ -n "$toplevel" && "$(realpath "$path" 2>/dev/null)" != "$toplevel" ]]; then
    rel=$(realpath --relative-to="$toplevel" "$path" 2>/dev/null)
    mode=$(git -C "$toplevel" ls-files --stage -- "$rel" 2>/dev/null | awk '{print $1}')
    if [[ "$mode" == "160000" ]]; then
      echo -e "$display_path\t❌ Uninitialized submodule (resolves to parent $toplevel) - run: git submodule update --init $rel"
      return 1
    fi
  fi

  # Fetch latest remote data
  if ! git -C "$path" fetch --quiet --all --prune 2>/dev/null; then
    echo -e "$display_path\t⚠️ Fetch failed"
    return 1
  fi

  # Get current branch
  branch=$(git -C "$path" symbolic-ref --short HEAD 2>/dev/null || git -C "$path" rev-parse --short HEAD 2>/dev/null)
  if [[ -z "$branch" ]]; then
    echo -e "$display_path\t❌ Could not determine branch"
    return 1
  fi

  # Check working tree status
  dirty=""
  if [[ -n "$(git -C "$path" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
    dirty=" 💎"
  fi

  upstream=$(git -C "$path" rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>/dev/null || echo "")
  if [[ "$COMPARE_MODE" == "upstream" && -z "$upstream" ]]; then
    echo -e "$display_path ($branch)\t❓ No upstream$dirty"
    return 0
  fi

  if ! counts=$(get_branch_counts "$path" "$branch" "$upstream"); then
    echo -e "$display_path ($branch)\t❌ Cannot compare against ${BASE_REF:-repo default branch}$dirty"
    return 1
  fi
  read -r ahead behind <<< "$counts"
  total=$((ahead + behind))
  compare_label=$(get_compare_label "$path")

  # Determine status icon
  if [[ $ahead -gt 0 ]] && [[ $behind -gt 0 ]]; then
    status_icon="🔄"
  elif [[ $ahead -gt 0 ]]; then
    status_icon="⬆️"
  elif [[ $behind -gt 0 ]]; then
    status_icon="⬇️"
  else
    status_icon="✅"
  fi

  echo -e "$display_path ($branch)\t$status_icon $ahead↑ $behind↓ vs $compare_label$dirty"

  if [[ $total -gt 0 ]]; then
    return 2
  fi

  return 0
}

# Function to format open GitHub PRs associated with a branch
format_branch_prs() {
  local path="$1"
  local branch="$2"
  local pr_lines pr_count pr_list

  if ! command -v gh >/dev/null 2>&1; then
    echo "-"
    return 0
  fi

  if ! git -C "$path" remote get-url origin 2>/dev/null | grep -qi 'github.com'; then
    echo "-"
    return 0
  fi

  local gh_rc=0
  pr_lines=$(
    cd "$path" && gh pr list --state open --head "$branch" --json number,isDraft --jq '.[] | "#" + (.number | tostring) + (if .isDraft then "D" else "" end)' 2>/dev/null
  ) || gh_rc=$?

  # A failed call must not be rendered as "0 open PRs".
  if [[ $gh_rc -ne 0 ]]; then
    if [[ "$GH_WARNED" != true ]]; then
      echo "⚠️  gh pr list failed in $path (auth or rate limit?); PR counts shown as ?" >&2
      GH_WARNED=true
    fi
    echo "?"
    return 0
  fi

  if [[ -z "$pr_lines" ]]; then
    echo "0"
    return 0
  fi

  pr_count=$(printf "%s\n" "$pr_lines" | sed '/^$/d' | wc -l | tr -d ' ')
  pr_list=$(printf "%s\n" "$pr_lines" | paste -sd, -)
  echo "$pr_count ($pr_list)"
}

# Function to show top N branches in a repo
show_top_branches() {
  local path="$1"
  local display_path="$2"
  local branch upstream counts ahead behind total commit_unix commit_date prs compare_label

  compare_label=$(get_compare_label "$path")
  echo -e "\n📁 $display_path"
  echo "Compare: $compare_label"

  if [[ "$SORT_MODE" == "newest" ]]; then
    printf "%-44s %12s %8s %8s %8s %-24s\n" "Branch" "Updated" "Ahead" "Behind" "Total" "PRs"
    printf "%-44s %12s %8s %8s %8s %-24s\n" "------" "-------" "-----" "------" "-----" "---"

    git -C "$path" for-each-ref --sort=-committerdate --format='%(committerdate:unix) %(committerdate:short) %(refname:short) %(upstream:short)' refs/heads/ | while read -r commit_unix commit_date branch upstream; do
      if [[ "$COMPARE_MODE" == "upstream" && -z "$upstream" ]]; then
        counts="0 0"
      else
        counts=$(get_branch_counts "$path" "$branch" "$upstream")
      fi
      read -r ahead behind <<< "$counts"
      total=$((ahead + behind))
      printf "%s\t%s\t%s\t%d\t%d\t%d\n" "$commit_unix" "$commit_date" "$branch" "$ahead" "$behind" "$total"
    done | sort -t $'\t' -k1,1nr | head -n "$N" | while IFS=$'\t' read -r commit_unix commit_date branch ahead behind total; do
      prs=$(format_branch_prs "$path" "$branch")
      printf "%-44s %12s %8d %8d %8d %-24s\n" "$branch" "$commit_date" "$ahead" "$behind" "$total" "$prs"
    done
  else
    printf "%-44s %12s %8s %8s %8s %-24s\n" "Branch" "Updated" "Ahead" "Behind" "Total" "PRs"
    printf "%-44s %12s %8s %8s %8s %-24s\n" "------" "-------" "-----" "------" "-----" "---"

    git -C "$path" for-each-ref --format='%(committerdate:short) %(refname:short) %(upstream:short)' refs/heads/ | while read -r commit_date branch upstream; do
      if [[ "$COMPARE_MODE" == "upstream" && -z "$upstream" ]]; then
        continue
      fi
      counts=$(get_branch_counts "$path" "$branch" "$upstream")
      read -r ahead behind <<< "$counts"
      total=$((ahead + behind))
      printf "%d\t%s\t%s\t%d\t%d\n" "$total" "$commit_date" "$branch" "$ahead" "$behind"
    done | sort -t $'\t' -k1,1nr | head -n "$N" | while IFS=$'\t' read -r total commit_date branch ahead behind; do
      prs=$(format_branch_prs "$path" "$branch")
      printf "%-44s %12s %8d %8d %8d %-24s\n" "$branch" "$commit_date" "$ahead" "$behind" "$total" "$prs"
    done
  fi
}

# Function to check if any local branch in a repo is divergent from the selected comparison ref
repo_has_divergent_branch() {
  local path="$1"
  local branch upstream counts ahead behind total

  while read -r branch upstream; do
    if [[ "$COMPARE_MODE" == "upstream" && -z "$upstream" ]]; then
      continue
    fi

    counts=$(get_branch_counts "$path" "$branch" "$upstream")
    read -r ahead behind <<< "$counts"
    total=$((ahead + behind))

    if [[ $total -gt 0 ]]; then
      return 0
    fi
  done < <(git -C "$path" for-each-ref --format='%(refname:short) %(upstream:short)' refs/heads/)

  return 1
}

# Main execution
echo -e "🔍 Checking ${#REPOS[@]} repo(s), top $N branches by $SORT_LABEL, ahead/behind vs $COMPARE_LABEL:"
echo "================================================================================"

# Collect all repos (including submodules)
summary_failed=0
all_repos=()
for repo in "${REPOS[@]}"; do
  if [[ ! -d "$repo" ]]; then
    echo "⚠️ Skipping non-directory: $repo" >&2
    summary_failed=$((summary_failed + 1))
    continue
  fi
  # Add main repo
  all_repos+=("$repo")
  # Add submodules if enabled
  if [[ "$SUBMODULES" = true ]]; then
    if [[ -f "$repo/.gitmodules" ]]; then
      while IFS= read -r mod_path; do
        mod_path=$(realpath "$repo/$mod_path" 2>/dev/null)
        if [[ -d "$mod_path" ]]; then
          all_repos+=("$mod_path")
        fi
      done < <(git -C "$repo" config --file .gitmodules --get-regexp 'submodule\..*\.path' 2>/dev/null | awk '{print $2}')
    fi
  fi
done

# Deduplicate repos
declare -A seen
unique_repos=()
for repo in "${all_repos[@]}"; do
  if [[ -z "${seen[$repo]}" ]]; then
    seen[$repo]=1
    unique_repos+=("$repo")
  fi
done

# Process each unique repo
summary_divergent=0
for repo in "${unique_repos[@]}"; do
  # Get display path relative to original repo if possible
  display_path="$repo"
  for original_repo in "${REPOS[@]}"; do
    if [[ "$repo" == "$original_repo"/* ]] && [[ "$repo" != "$original_repo" ]]; then
      display_path="$original_repo/${repo#$original_repo/} (submodule)"
      break
    fi
  done

  # Process repo summary
  REPO_BASE_REF=""
  repo_status_output=$(process_repo "$repo" "$display_path")
  repo_status_code=$?
  echo "$repo_status_output"

  # 1 = not a repo root / fetch failed / no branch / base ref unresolvable: the
  # refs on disk are stale or absent, so no drift conclusion from them is valid.
  # 2 = current branch is divergent, a normal result — keep going.
  if [[ $repo_status_code -eq 1 ]]; then
    summary_failed=$((summary_failed + 1))
    echo "   ↳ skipping branch table for $display_path: repo could not be inspected" >&2
    continue
  fi

  # Resolve the compare ref once per repo, after process_repo's fetch has landed,
  # so every branch row below shares one value and one gh round-trip.
  if [[ "$COMPARE_MODE" == "base" ]]; then
    REPO_BASE_REF=$(normalize_base_ref "$repo" "$BASE_REF") || REPO_BASE_REF=""
  fi

  if repo_has_divergent_branch "$repo"; then
    summary_divergent=$((summary_divergent + 1))
  fi

  # Show top branches if divergence exists
  if [[ "$N" -gt 0 ]]; then
    show_top_branches "$repo" "$display_path"
  fi
done

# Final summary
echo -e "\n📊 SUMMARY: $summary_divergent/${#unique_repos[@]} repos have divergence (ahead or behind)"
if [[ $summary_failed -gt 0 ]]; then
  echo "❌ $summary_failed repo(s) could not be inspected — this report is NOT a clean bill of health" >&2
  exit 1
fi
if [[ $COUNT_ERRORS -ne 0 ]]; then
  echo "❌ One or more branch comparisons could not be computed — results are incomplete" >&2
  exit 1
fi
if [[ $summary_divergent -eq 0 ]]; then
  echo "✅ All repos are up to date!"
  exit 0
fi

if [[ "$EXIT_ON_DIVERGENCE" == true ]]; then
  exit 2
fi
exit 0
