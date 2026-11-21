#!/usr/bin/env bash
#
# PreCompact hook — keep capture-worthy findings alive through compaction.
#
# The Stop hook nudges a capture when the session ends, but a long session
# compacts first: everything found before the compaction is reduced to a
# summary, and a fix that is not in the summary is gone before Stop fires.
# Claude Code uses a PreCompact hook's stdout as extra instructions for that
# summary, so this asks the summary to carry those findings forward. The Stop
# hook's capture (or a manual /wiki-capture --quick) then still has them.
#
# It never blocks compaction (always exit 0) and prints nothing when disabled.

cat >/dev/null  # drain the payload; nothing in it changes the instructions

case "${WIKI_PRECOMPACT_CAPTURE:-${WIKI_STOP_CAPTURE:-${HIVEMIND_CAPTURE:-}}}" in
  false|0|off|no) exit 0 ;;
esac

cat <<'EOF'
Keep wiki-capture candidates. Before the rest of the summary, add a section
titled "Wiki capture candidates" listing every non-obvious finding from the
conversation so far: bugs and their root causes, workarounds that took
investigation, surprising library or tool behavior, and decisions with their
reasons. Give each one or two sentences with the exact file paths, commands,
error text and versions involved, so it can be saved with /wiki-capture --quick
later. Leave out routine steps. If there are none, write "none".
EOF
exit 0
