#!/usr/bin/env bash
# PreToolUse nudge — PR review feedback and merge guard.
#
# Replaces the earlier prompt-type merge guard, which evaluated an LLM
# condition on EVERY Bash call (the "if" field is not part of the hook
# schema and was silently ignored), blocking unrelated commands and
# spending an API call per misfire. This version is fully deterministic.
#
# Four triggers, one script. A hook invocation can return only ONE
# decision, and `grep -Eq` matches its pattern ANYWHERE in the command
# string, so a compound command (`gh pr comment ... && gh pr merge ...`)
# can match several triggers at once. They are therefore evaluated
# STRONGEST-FIRST — blocking branches before informational ones — so a
# blocking decision always wins regardless of where its subcommand sits
# in the chain. File order == priority order:
#
# 1. GH PR VIEW REDIRECT (deny): fires before `gh pr view --comments`.
#    DENIES the call — it misses review-body comments and suppressed
#    co-pilot reviews. Redirects to the `gh api` method.
#
# 2. MERGE GUARD (ask): fires before `gh pr merge`. BLOCKS until the user
#    confirms all review comments are addressed. Tells the agent to use
#    `gh api` (not `gh pr view --comments`) to check.
#
# 3. REPLY NUDGE (informational): fires before `gh pr comment`,
#    `gh pr review`, or `gh api ...pulls/*/comments -X POST`. Reminds the
#    agent to verify claims against the code and sign the reply on
#    Adam's behalf.
#
# 4. READ COMMENTS NUDGE (informational): fires before
#    `gh api ...pulls/*/comments` (GET). Reminds the agent to also check
#    the reviews and issue-comments endpoints for suppressed co-pilot
#    reviews.
#
# Adapted from 10110TasteslikegoodPlaza/.claude/hooks/
# pretooluse-pr-review-nudge.sh (the revised guard).
#
# Every gh pattern is anchored to a command position (line start or
# after ; & | ( or $() so the phrase inside quoted prose -- e.g. a
# commit message discussing these commands -- cannot false-positive.
#
# Fail-open: any error exits 0 so a transient failure never blocks.
set -uo pipefail
trap 'exit 0' ERR

payload="$(cat)"
tool_name="$(printf '%s' "$payload" | jq -r '.tool_name // empty' 2>/dev/null || true)"

[ "$tool_name" = "Bash" ] || exit 0

cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"

# ===================================================================
# BLOCKING branches first — a match here must win over the informational
# nudges below even when the triggering subcommand is chained after one.
# ===================================================================

# --- gh pr view --comments redirect (wrong tool) — DENY ---
# Single regex so the --comments/-c flag is scoped to THIS `gh pr view`
# invocation: `[^&|;]*` cannot cross a command separator, so a later
# `bash -c` / `grep -c` in a compound command no longer false-positives.
if printf '%s' "$cmd" | grep -Eq '(^|[;&|(]|\$\()[[:space:]]*gh[[:space:]]+pr[[:space:]]+view[[:space:]]([^&|;]*[[:space:]])?(--comments|-c)([[:space:]]|$)'; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Use gh api instead -- gh pr view --comments misses review-body comments and suppressed co-pilot reviews","additionalContext":"WRONG TOOL: `gh pr view --comments` only shows issue-style comments, NOT inline review comments or suppressed co-pilot reviews. Use ALL THREE gh api endpoints (add `--paginate` to each so nothing past page 1 is missed): `gh api --paginate repos/{owner}/{repo}/pulls/{number}/comments` (inline diff comments), `gh api --paginate repos/{owner}/{repo}/issues/{number}/comments` (top-level conversation comments), and `gh api --paginate repos/{owner}/{repo}/pulls/{number}/reviews` (submitted review summaries -- prose feedback in a review `.body` with no inline comments appears in NONE of the others; check both `.body` and `.state`)."}}
JSON
  exit 0
fi

# --- Merge guard — ASK (blocks until user confirms) ---
if printf '%s' "$cmd" | grep -Eq '(^|[;&|(]|\$\()[[:space:]]*gh[[:space:]]+pr[[:space:]]+merge([[:space:]]|$)'; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"Merge guard: have all review comments been addressed?","additionalContext":"STOP -- you are about to merge a PR. Before merging, you MUST check for unanswered review comments. Use ALL THREE endpoints (add `--paginate` to each so nothing past page 1 is missed): `gh api --paginate repos/{owner}/{repo}/pulls/{number}/comments` (inline diff comments), `gh api --paginate repos/{owner}/{repo}/issues/{number}/comments` (top-level conversation comments), AND `gh api --paginate repos/{owner}/{repo}/pulls/{number}/reviews` (submitted review summaries -- a COMMENTED/CHANGES_REQUESTED review can carry prose feedback in its `.body` with no inline comments, invisible to the other two endpoints; check both `.body` and `.state`). This is where suppressed co-pilot reviews hide. NOT `gh pr view --comments`, which misses all of these. Every comment must be addressed with either a fix commit or a concrete technical rebuttal. If any comment is unanswered, deny this merge and address it first."}}
JSON
  exit 0
fi

# ===================================================================
# INFORMATIONAL nudges — only reached when no blocking branch matched.
# ===================================================================

# --- Reply nudge (gh pr comment/review) ---
if printf '%s' "$cmd" | grep -Eq '(^|[;&|(]|\$\()[[:space:]]*gh[[:space:]]+pr[[:space:]]+(comment|review)([[:space:]]|$)'; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"You are about to post a reply to PR review feedback. Per the PR workflow rules: if you have not already this turn, invoke the superpowers:receiving-code-review skill and evaluate this feedback with technical rigor -- verify each claim against the code, then either push a fix commit or give a concrete technical rebuttal (never performative agreement, never silently ignore). End the reply with the attribution line: _Replied by Claude on Adam's behalf_"}}
JSON
  exit 0
fi

# --- Reply nudge (gh api ...pulls/*/comments POST) ---
if printf '%s' "$cmd" | grep -Eq '(^|[;&|(]|\$\()[[:space:]]*gh[[:space:]]+api[[:space:]]' \
  && printf '%s' "$cmd" | grep -Eq 'pulls/[0-9]+/comments' \
  && printf '%s' "$cmd" | grep -Eq '(-X[[:space:]]*POST|--method[[:space:]]*POST|-f[[:space:]]|-F[[:space:]]|--field[[:space:]]|--input[[:space:]])'; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"You are about to post a reply to PR review feedback via gh api. Per the PR workflow rules: if you have not already this turn, invoke the superpowers:receiving-code-review skill and evaluate this feedback with technical rigor -- verify each claim against the code, then either push a fix commit or give a concrete technical rebuttal (never performative agreement, never silently ignore). End the reply with the attribution line: _Replied by Claude on Adam's behalf_"}}
JSON
  exit 0
fi

# --- Reading PR comments (load receiving-code-review skill) ---
if printf '%s' "$cmd" | grep -Eq '(^|[;&|(]|\$\()[[:space:]]*gh[[:space:]]+api[[:space:]]' \
  && printf '%s' "$cmd" | grep -Eq 'pulls/[0-9]+/comments' \
  && ! printf '%s' "$cmd" | grep -Eq '(-X[[:space:]]*POST|--method[[:space:]]*POST|-f[[:space:]]|-F[[:space:]]|--field[[:space:]]|--input[[:space:]])'; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"You are reading PR review comments via the correct API method (gh api). If you have not already this turn, invoke the superpowers:receiving-code-review skill before responding to any feedback. This endpoint only returns inline diff comments -- also check `gh api --paginate repos/{owner}/{repo}/issues/{number}/comments` for top-level PR comments AND `gh api --paginate repos/{owner}/{repo}/pulls/{number}/reviews` for submitted review summaries (a COMMENTED/CHANGES_REQUESTED review can carry prose feedback in its `.body` with no inline comments; check both `.body` and `.state`). Add `--paginate` so feedback past page 1 is not missed. This is where suppressed co-pilot reviews hide -- they are real reviews that should be evaluated with the same rigor."}}
JSON
  exit 0
fi

exit 0
