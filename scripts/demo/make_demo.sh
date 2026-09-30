#!/usr/bin/env sh
# Regenerate the README demo: docs/demo.cast and docs/demo.gif.
#
# The recording wipes a handful of throwaway files that record.py creates in
# a fresh temporary directory (HOME and XDG_STATE_HOME point there too) and
# removes afterwards. Nothing else on the machine is touched.
#
# Requirements: Linux or macOS, the package's runtime dependencies, and either
# agg (https://github.com/asciinema/agg) or `pip install pyte pillow` plus the
# DejaVu fonts (Noto Color Emoji is optional) for render_gif.py.
set -eu

cd "$(dirname "$0")/../.."
PYTHON="${PYTHON:-python3}"

"$PYTHON" scripts/demo/record.py --out docs/demo.cast
# Every screen of the recording must be free of repaint leftovers.
"$PYTHON" scripts/demo/check_cast.py docs/demo.cast

if [ "${USE_AGG:-auto}" != "no" ] && command -v agg >/dev/null 2>&1; then
    agg --idle-time-limit 2.5 --font-size 15 --last-frame-duration 4 docs/demo.cast docs/demo.gif
    echo "wrote docs/demo.gif with agg"
else
    "$PYTHON" scripts/demo/render_gif.py docs/demo.cast docs/demo.gif
fi
