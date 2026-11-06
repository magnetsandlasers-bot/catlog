#!/usr/bin/env python3
"""Strip encoder-noise frames (TSSE/TENC) and stale COMM from rendered MP3s."""

import sys
from pathlib import Path
from mutagen.id3 import ID3


def tidy(files):
    changed = 0
    for f in files:
        try:
            t = ID3(str(f))
        except Exception as exc:
            print(f"  skip {f.name}: {exc}")
            continue
        removed = []
        for k in ("TSSE", "TENC", "COMM"):
            if t.getall(k):
                t.delall(k)
                removed.append(k)
        if removed:
            t.save(str(f), v2_version=4)
            changed += 1
            print(f"  {f.name}: removed {', '.join(removed)}")
    print(f"tidied {changed} of {len(files)} files")


if __name__ == "__main__":
    root = Path(sys.argv[1])
    files = sorted(p for p in root.glob("*.mp3") if not p.name.startswith("._"))
    tidy(files)
