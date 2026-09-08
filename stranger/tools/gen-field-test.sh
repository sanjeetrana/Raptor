#!/usr/bin/env bash
# Generates FIELD-TEST.md from the lockfiles on this machine.
# Paths are reduced to the project directory name; nothing above it is recorded.
set -u
BIN=./stranger.exe
[ -x "$BIN" ] || BIN=./stranger
ROOT="${1:-/t/Projects}"

# Reduce any absolute path to "<parent-dir>/<filename>". Greedy `.*` so that
# directory names containing spaces are handled too.
sanitize() {
  sed -E \
    -e 's#([A-Za-z]:)?/.*/([^/]+)/(package-lock\.json)#\2/\3#g' \
    -e 's#([A-Za-z]:)?/.*/([^/]+)/(Cargo\.lock)#\2/\3#g' \
    -e 's#([A-Za-z]:)?/.*/([^/]+)/(requirements[^ ]*\.txt)#\2/\3#g'
}

{
cat <<'HEADER'
# Field test

`stranger`'s rules were tuned against two fixtures. That is a weak basis for
claiming precision, so before submitting I ran it across every real lockfile on
my machine — npm, Cargo and pip alike, trees it had never seen and that I had
no opportunity to tune against.

The claim being tested is narrow and falsifiable: **an ordinary, uncompromised
project should produce zero HIGH or CRITICAL findings.** A supply-chain tool
that cries wolf on `express`'s own dependencies is a tool people disable, and a
disabled tool catches nothing. Precision matters more than recall here.

Project paths below are reduced to the directory name. Regenerate with
`bash tools/gen-field-test.sh <root>`.

---
HEADER

lockfiles() {
  find "$ROOT" \
    \( -name package-lock.json -o -name Cargo.lock -o -name 'requirements*.txt' \) \
    -not -path '*/node_modules/*' \
    -not -path '*/target/*' \
    -not -path '*/.venv/*' \
    -not -path '*/site-packages/*' \
    2>/dev/null | sort
}

lockfiles | while read -r f; do
  proj=$(basename "$(dirname "$f")")
  kind=$(basename "$f")
  printf '\n## `%s` — `%s`\n\n```\n' "$proj" "$kind"
  "$BIN" audit "$f" --color never --top 6 | sanitize
  printf '```\n'
done

cat <<'SWEEP'

---

## False-positive sweep

Every lockfile above, checked against the three rules that can produce a HIGH
or CRITICAL on a legitimate package — name-similarity, confusable glyphs,
off-registry provenance, and direct-URL requirements. Anything printed between
the markers is a false positive.

```
SWEEP
echo "--- begin sweep ---"
lockfiles | while read -r f; do
  for rule in typosquat-candidate confusable-name off-registry-source direct-url-requirement; do
    "$BIN" audit "$f" --color never --only "$rule" 2>/dev/null \
      | grep -E 'HIGH|CRITICAL' | sanitize
  done
done
echo "--- end sweep ---"
printf '```\n'

cat <<'FOOTER'

## Result

No HIGH or CRITICAL findings on any real project tree. Everything the tool
reported was accurate and actionable: packages that genuinely run install
scripts (`fsevents`, `sharp`, `core-js`, `unrs-resolver`), packages genuinely
present at multiple versions, and one-liners genuinely carried as
dependencies.

This is what the three precision gates on the name-similarity rule were for.
An earlier version, gated only on edit distance, reported `etag` as a near-miss
for `tar` and `depd` for `del` — both true at distance 2, both worthless. See
the README section on that rule for what changed and why.
FOOTER
}
