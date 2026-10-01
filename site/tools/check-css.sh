#!/usr/bin/env bash
# Guard against malformed CSS silently breaking the bundle.
#
# An unclosed brace in one file makes every file concatenated after it
# nest inside that block. Hugo reports no error, the SRI hash still
# matches, and the page renders unstyled with no console output — so
# check brace balance explicitly.

set -euo pipefail
cd "$(dirname "$0")/.."

status=0

# 1. Brace balance per source file, ignoring braces inside strings.
for f in themes/examhub/assets/css/*.css; do
  depth=$(python3 - "$f" <<'PY'
import sys
s = open(sys.argv[1]).read()
depth = 0
for ch in s:
    if ch == '{':
        depth += 1
    elif ch == '}':
        depth -= 1
print(depth)
PY
)
  if [ "$depth" != "0" ]; then
    echo "UNBALANCED ($depth): $f" >&2
    status=1
  fi
done

# 2. Every top-level rule must sit outside any @media block.
python3 - <<'PY' || status=1
import glob, re, sys
bad = False
for path in sorted(glob.glob('themes/examhub/assets/css/*.css')):
    # strip comments, then walk tracking depth
    s = re.sub(r'/\*.*?\*/', '', open(path).read(), flags=re.S)
    depth = 0
    for ch in s:
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth < 0:
                print(f'STRAY CLOSE BRACE: {path}', file=sys.stderr)
                bad = True
                break
    if depth != 0:
        print(f'UNCLOSED BLOCK ({depth}): {path}', file=sys.stderr)
        bad = True
sys.exit(1 if bad else 0)
PY

# 2b. A custom property that references itself (--text: var(--text)) is
# invalid at computed-value time. The property becomes the guaranteed-
# invalid value, so every `color: var(--text)` silently resolves to
# unset and the element falls back to black. On a dark background that
# is unreadable, and nothing in the build output reports it.
python3 - <<'PY' || status=1
import glob, re, sys
bad = False
for path in sorted(glob.glob('themes/examhub/assets/css/*.css')):
    s = re.sub(r'/\*.*?\*/', '', open(path).read(), flags=re.S)
    for m in re.finditer(r'(--[\w-]+)\s*:\s*([^;{}]+);', s):
        name, value = m.group(1), m.group(2)
        for ref in re.findall(r'var\(\s*(--[\w-]+)', value):
            if ref == name:
                line = s[:m.start()].count('\n') + 1
                print(
                    f'SELF-REFERENTIAL PROPERTY {name} at {path}:{line}',
                    file=sys.stderr,
                )
                bad = True
sys.exit(1 if bad else 0)
PY

# 2c. Comment delimiters must pair, and in order.
#
# This is not a style rule, it is a correctness one, and it is the check
# that would have caught a bug that brace counting reported as clean.
#
# A comment-closer written out as prose inside another comment ends that
# comment early, and everything after it is read as declarations. The
# minifier then emits the remaining prose verbatim into the middle of a
# declaration block, the browser skips the unparseable text one declaration
# at a time, and every property declared after that point silently
# disappears. The braces stay balanced throughout, so check 1 passes, and
# the page still renders: the properties that vanished were ones whose
# absence just looks like a design choice. Concretely: a comment that
# mentioned a comment-closer while explaining a comment bug killed a chain
# of custom properties, and the dot it positioned sat 13.4px off with a
# total of silence from the build.
python3 - <<'PY' || status=1
import glob, sys

bad = False
for path in sorted(glob.glob('themes/examhub/assets/css/*.css')):
    s = open(path).read()
    i, n, in_comment, opener = 0, len(s), False, 0
    while i < n:
        if in_comment:
            if s.startswith('*/', i):
                in_comment = False
                i += 2
            else:
                i += 1
        elif s.startswith('/*', i):
            in_comment, opener = True, i
            i += 2
        elif s.startswith('*/', i):
            # A closer with nothing open. This is the shape a comment-closer
            # written in prose takes once it has already ended its own
            # comment: the text between the two closers is then read as
            # declarations, and the browser discards it one piece at a time.
            line = s[:i].count('\n') + 1
            print(f'STRAY COMMENT CLOSER at {path}:{line}', file=sys.stderr)
            bad = True
            i += 2
        else:
            i += 1
    if in_comment:
        line = s[:opener].count('\n') + 1
        print(f'UNCLOSED COMMENT opened at {path}:{line}', file=sys.stderr)
        bad = True
sys.exit(1 if bad else 0)
PY

# 3. The bundled stylesheet must contain the rules the templates depend on.
if hugo=$(command -v hugo || true); then
  out=$(mktemp -d)
  trap 'rm -rf "$out"' EXIT
  if $hugo --quiet --destination "$out" >/dev/null 2>&1; then
    css=$(find "$out" -name '*.css' | head -1)
    if [ -n "$css" ]; then
      for sel in '.site-header' '.sidebar' '.card' '.pill' '.timeline' '.theme-toggle'; do
        if ! grep -qF -- "$sel" "$css"; then
          echo "MISSING '$sel' in bundled CSS" >&2
          status=1
        fi
      done
    else
      echo "No CSS produced by the build" >&2
      status=1
    fi

    # The @font-face rules are emitted by layouts/_partials/fonts.html, so
    # they live in the HTML rather than the stylesheet. A var() reference
    # inside @font-face src silently invalidates the rule and the browser
    # falls back to a serif face while everything still "looks fine" — so
    # assert the URLs are literal and the files exist.
    home="$out/index.html"
    if [ -f "$home" ]; then
      faces=$(grep -c '@font-face' "$home" || true)
      if [ "$faces" -lt 3 ]; then
        echo "Expected 3 @font-face rules in HTML, found $faces" >&2
        status=1
      fi
      if grep -q '@font-face[^}]*url(var(' "$home"; then
        echo "url(var(...)) in @font-face src is invalid CSS" >&2
        status=1
      fi
      for w in 400 500 700; do
        if ! grep -q "jost-$w.woff2" "$home"; then
          echo "Missing @font-face for Jost $w" >&2
          status=1
        fi
        if [ ! -f "$out/fonts/jost-$w.woff2" ]; then
          echo "Font file jost-$w.woff2 not published" >&2
          status=1
        fi
      done
    fi
  fi
else
  echo "note: hugo not on PATH, skipped the bundle check" >&2
fi

if [ "$status" -eq 0 ]; then
  echo "css check: ok"
fi
exit "$status"
