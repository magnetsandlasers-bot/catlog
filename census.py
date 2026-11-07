#!/usr/bin/env python3
"""
Genre census. Read-only.

Counts every distinct TCON value across a music library, so the vocabulary
that is actually in use can be seen rather than assumed. Written after a run
over 13,090 files turned up 83 distinct values, several of which were the same
value spelled differently.

Points PIPELINE at a music tree, not at catlog-data -- this reads a finished
library, not an intake queue.

Usage:
    python3 census.py /mnt/woke_classical
    python3 census.py ~/Music --limit 500        # first 500 files only
    python3 census.py ~/Music --no-genre-only    # list files with no TCON
"""

import argparse
import sys
from collections import Counter
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after N files (0 = all)")
    ap.add_argument("--no-genre-only", action="store_true",
                    help="print the paths of files with no TCON")
    args = ap.parse_args()

    try:
        from mutagen.id3 import ID3
    except ImportError:
        print("ERROR: mutagen is not installed.")
        print("  sudo apt install python3-mutagen")
        print("  or: pip install mutagen")
        return 1

    root = Path(args.root)
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}")
        return 1

    counter = Counter()
    no_genre = []
    errors = 0
    seen = 0

    for p in sorted(root.rglob("*.mp3")):
        if p.name.startswith("._"):
            continue
        if args.limit and seen >= args.limit:
            break
        seen += 1
        try:
            t = ID3(str(p))
        except Exception:
            errors += 1
            continue
        f = t.get("TCON")
        if f is None:
            no_genre.append(p)
            continue
        try:
            counter[str(f.text[0]).strip()] += 1
        except Exception:
            errors += 1

    print(f"scanned {seen} files")
    print(f"  no genre : {len(no_genre)}")
    print(f"  errors   : {errors}")
    print(f"  distinct : {len(counter)}")
    print()
    for g, n in counter.most_common():
        print(f"{n:7d}  {g}")

    if args.no_genre_only and no_genre:
        print()
        print("FILES WITH NO GENRE")
        for p in no_genre:
            print(f"  {p}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
