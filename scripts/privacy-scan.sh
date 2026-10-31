#!/usr/bin/env bash
# Blocks personal and host data from entering this public repo (see the
# security rules). Checks only ADDED lines, file names, commit messages and
# authors, so old history does not keep failing. Two pattern sources:
#   1. generic patterns below (private IPs, LAN hosts, user paths, foreign
#      e-mails, token shapes): committed, contain no personal data;
#   2. .claude/private-terms.txt: the user's own names, places and hosts, one
#      extended regex per line, case-insensitive. Gitignored, never committed.
# A single line can be let through with the marker "privacy-scan: allow".
#   scripts/privacy-scan.sh --staged              staged changes (pre-commit)
#   scripts/privacy-scan.sh --message <file>      commit message (commit-msg)
#   scripts/privacy-scan.sh --commits <rev-list args>  outgoing commits (pre-push)
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

SELF=scripts/privacy-scan.sh
TERMS=.claude/private-terms.txt
EMPTY_TREE=$(git hash-object -t tree /dev/null)

# label<TAB>extended regex. Written so they do not match this file's own text.
GENERIC=$(cat <<'EOF'
private IPv4	(^|[^0-9.])(10\.[0-9]{1,3}|192\.168|172\.(1[6-9]|2[0-9]|3[01]))\.[0-9]{1,3}\.[0-9]{1,3}([^0-9.]|$)
LAN host name	[A-Za-z0-9-]+\.(lan|home|internal|fritz\.box)([^A-Za-z0-9.-]|$)
user home path	[A-Za-z]:[\\/]+Users[\\/]+[A-Za-z]|/home/[a-z][a-z0-9_-]+/|/Users/[A-Za-z]
e-mail address	[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z][A-Za-z]+
Anthropic key	sk-ant-[A-Za-z0-9_-]{10,}
JWT / HA token	eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}
private key	-----BEGIN [A-Z ]*PRIVATE KEY-----
GitHub token	gh[pousr]_[A-Za-z0-9]{30,}
EOF
)
# Matches of these kinds that are fine (public commit identity, placeholders).
OK_RE='^(forkent@icloud\.com|noreply@anthropic\.com|noreply@github\.com|.*@users\.noreply\.github\.com|.*@example\.(com|org|net|invalid)|.*example\.(lan|home|internal).*)$'

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
: >"$TMP/records"   # one record per candidate: <where>\x1f<text>

add() { local where=$1; while IFS= read -r l; do printf '%s\037%s\n' "$where" "$l"; done >>"$TMP/records"; }

# collect_diff <git diff args...>: file names and added lines.
collect_diff() {
  git diff --no-color --no-ext-diff -U0 "$@" | awk -v self="$SELF" '
    /^\+\+\+ b\// { f = substr($0, 7); printf "file name\037%s\n", f; next }
    /^\+\+\+ /    { f = ""; next }
    /^\+/         { if (f != "" && f != self) printf "%s\037%s\n", f, substr($0, 2) }' >>"$TMP/records"
}

case ${1:-} in
  --staged) collect_diff --cached ;;
  --message) grep -v '^#' "$2" | add "commit message" ;;
  --commits)
    shift
    for c in $(git rev-list "$@"); do
      p=$(git rev-parse -q --verify "$c^" || echo "$EMPTY_TREE")
      collect_diff "$p" "$c"
      git log -1 --format=%B "$c" | add "message of ${c:0:12}"
      git log -1 --format='%an <%ae>%n%cn <%ce>' "$c" | add "author of ${c:0:12}"
    done ;;
  *) echo "usage: $0 --staged | --message <file> | --commits <rev-list args>" >&2; exit 2 ;;
esac

printf '%s\n' "$GENERIC" >"$TMP/generic"
if [[ -f $TERMS ]]; then
  grep -Ev '^[[:space:]]*(#|$)' "$TERMS" >"$TMP/private" || true
else
  : >"$TMP/private"
  echo "privacy-scan: WARNING $TERMS missing, only generic patterns are checked" >&2
fi

# OK_RE goes through the environment: awk -v would eat its backslashes.
OK_RE=$OK_RE awk -F '\037' -v gen="$TMP/generic" -v priv="$TMP/private" '
  BEGIN {
    ok = ENVIRON["OK_RE"]
    if (ok == "") { print "privacy-scan: empty allow-list, refusing" > "/dev/stderr"; exit 2 }
    while ((getline l < gen) > 0) { split(l, a, "\t"); n++; lab[n] = a[1]; re[n] = a[2] }
    while ((getline l < priv) > 0) { m++; pre[m] = tolower(l) }
  }
  function hit(why) { printf "privacy-scan: %s: %s: %s\n", $1, why, substr($2, 1, 160) > "/dev/stderr"; hits++ }
  # true when some match of r in s is not an allowed placeholder
  function bad(s, r,   t) {
    while (match(s, r)) {
      t = substr(s, RSTART, RLENGTH); gsub(/^[^A-Za-z0-9]+|[^A-Za-z0-9]+$/, "", t)
      if (t !~ ok) return 1
      s = substr(s, RSTART + RLENGTH)
    }
    return 0
  }
  index($2, "privacy-scan: allow") { next }
  {
    for (i = 1; i <= n; i++) if (bad($2, re[i])) hit(lab[i])
    low = tolower($2)
    for (i = 1; i <= m; i++) if (low ~ pre[i]) { hit("private term (.claude/private-terms.txt)"); break }
  }
  END {
    if (hits) { printf "privacy-scan: %d hit(s). Remove the data or use invented data (see the security rules).\n", hits > "/dev/stderr"; exit 1 }
  }' "$TMP/records"
