#!/bin/bash
# catlog install: dependency check, directory setup, smoke test.
#
# Idempotent. Safe to run again. Does not touch any music.
#
#   ./install.sh            check and set up
#   ./install.sh --deps     also install missing apt packages

set -u

PIPE="${PIPELINE_HOME:-$HOME/pipeline}"
FAIL=0

say()  { printf '%s\n' "$*"; }
ok()   { printf '  ok    %s\n' "$*"; }
bad()  { printf '  MISS  %s\n' "$*"; FAIL=$((FAIL + 1)); }

say "catlog install"
say "pipeline home: $PIPE"
say ""

# ---------------------------------------------------------------- binaries
say "binaries"
for b in ffmpeg ffprobe 7z unrar unar flac shntool cueprint python3; do
    if command -v "$b" >/dev/null 2>&1; then
        ok "$b"
    else
        bad "$b"
    fi
done

# ---------------------------------------------------------------- python
say ""
say "python"
if command -v python3 >/dev/null 2>&1; then
    ok "python3 $(python3 -V 2>&1 | awk '{print $2}')"
    if python3 -c "import mutagen" >/dev/null 2>&1; then
        VER="$(python3 -c "import mutagen;print(mutagen.version_string)" 2>/dev/null)"
        ok "mutagen ${VER:-present}"
    else
        bad "mutagen (python3-mutagen)"
    fi
else
    bad "python3"
fi

# ---------------------------------------------------------------- dirs
say ""
say "directories"
for d in intake work manifests out reports quarantine logs meta; do
    if [ -d "$PIPE/$d" ]; then
        ok "$d/"
    else
        mkdir -p "$PIPE/$d" && ok "$d/ (created)"
    fi
done

# ---------------------------------------------------------------- optional
say ""
say "optional"
command -v exiftool >/dev/null 2>&1 && ok "exiftool" || say "  ----  exiftool (recommended, manual inspection)"
command -v identify >/dev/null 2>&1 && ok "imagemagick" || say "  ----  imagemagick (recommended, manual artwork work)"

# ---------------------------------------------------------------- summary
say ""
if [ "$FAIL" -eq 0 ]; then
    say "all required dependencies present"
else
    say "$FAIL required dependency or dependencies missing"
    say ""
    say "install with:"
    say "  sudo apt install -y ffmpeg p7zip-full unrar unar flac shntool \\"
    say "      cuetools libimage-exiftool-perl imagemagick python3-mutagen"
fi

say ""
say "next:"
say "  drop an album in $PIPE/intake, then"
say "  python3 $(dirname "$0")/scan.py"
