#!/usr/bin/env python3
"""
Stage 3 - DELIVER. Verifies a rendered album, then optionally copies it.

Checks before anything is copied:
  - every track in the manifest exists
  - every track is MP3 at roughly 320 kbps
  - every track has the expected tags
  - TIT1 and TIT2 match what was planned
  - every track carries exactly one embedded cover
  - the album cover is within 1280 on the long edge

With --copy it then copies the album into PIPELINE_OUT, which is the
library-shaped output tree. Without --copy it only reports.

If the rendered album is already inside PIPELINE_OUT, it verifies in place and
skips the copy step.

Usage:
    python3 deliver.py --slug borodin-prince-igor-tchakarov
    python3 deliver.py --slug borodin-prince-igor-tchakarov --copy
"""

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

DEST_ROOT = Path(os.environ.get("PIPELINE_OUT",
                                Path.home() / "pipeline" / "out"))
MANIFEST_ROOT = Path(os.environ.get("PIPELINE_MANIFESTS",
                                    Path.home() / "pipeline" / "manifests"))
LOCAL_OUT = Path(os.environ.get("PIPELINE_LOCAL_OUT", str(DEST_ROOT)))

REQUIRED = ["TIT1", "TIT2", "TPE1", "TPE2", "TALB", "TCOM",
            "TCON", "TDRC", "TRCK", "TPOS", "GRP1"]

BITRATE_MIN = 300000
BITRATE_MAX = 340000
DURATION_TOLERANCE_S = 1.5


def probe(path):
    """Container and stream facts via ffprobe."""
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name,bit_rate,sample_rate,channels",
         "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=120)
    try:
        d = json.loads(res.stdout)
        st = (d.get("streams") or [{}])[0]
        return {
            "codec": st.get("codec_name"),
            "bitrate": int(st.get("bit_rate") or 0),
            "rate": st.get("sample_rate"),
            "ch": st.get("channels"),
            "dur": float((d.get("format") or {}).get("duration") or 0),
        }
    except Exception:
        return {}


def tags_of(path):
    """Read back the frames this pipeline writes."""
    from mutagen.id3 import ID3
    out = {}
    try:
        t = ID3(str(path))
        for k in REQUIRED + ["MVNM", "MVIN"]:
            f = t.get(k)
            if f is not None:
                try:
                    out[k] = str(f.text[0])
                except Exception:
                    out[k] = str(f)
        apic = t.getall("APIC")
        out["_apic"] = len(apic)
        out["_apic_kb"] = len(apic[0].data) // 1024 if apic else 0
        out["_version"] = ".".join(str(x) for x in t.version)
    except Exception as exc:
        out["_error"] = str(exc)
    return out


def jpeg_size_bytes(data):
    """Width and height from JPEG bytes, no external tools."""
    try:
        i = 2
        while i < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            code = data[i + 1]
            if code in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6,
                        0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return (w, h)
            seglen = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + seglen
    except Exception:
        return None
    return None


def verify_album(src_dir, expected):
    """Return a list of problems. Empty list means clean."""
    problems = []
    ok = 0

    for t in expected:
        p = src_dir / t["filename"]
        if not p.is_file():
            problems.append("MISSING " + t["filename"])
            continue

        info = probe(p)
        if info.get("codec") != "mp3":
            problems.append(f"{t['filename']}: codec {info.get('codec')}")
        br = info.get("bitrate", 0)
        if not (BITRATE_MIN <= br <= BITRATE_MAX):
            problems.append(
                f"{t['filename']}: bitrate {br} (want ~320000)")
        if info.get("rate") != "44100":
            problems.append(
                f"{t['filename']}: sample rate {info.get('rate')}")
        got = info.get("dur", 0)
        want = t["duration_s"]
        if abs(got - want) > DURATION_TOLERANCE_S:
            problems.append(
                f"{t['filename']}: duration {got:.1f}s vs {want:.1f}s planned")

        tg = tags_of(p)
        for k in REQUIRED:
            if k not in tg:
                problems.append(f"{t['filename']}: missing {k}")
        if tg.get("TIT1") != t["tit1"]:
            problems.append(f"{t['filename']}: TIT1 does not match plan")
        if tg.get("TIT2") != t["tit2"]:
            problems.append(f"{t['filename']}: TIT2 does not match plan")
        if tg.get("_apic", 0) != 1:
            problems.append(
                f"{t['filename']}: {tg.get('_apic', 0)} embedded images")
        ok += 1

    cover = src_dir / "cover.jpg"
    art_dim = None
    if cover.is_file():
        art_dim = jpeg_size_bytes(cover.read_bytes())
        if art_dim and max(art_dim) > 1280:
            problems.append(
                f"cover.jpg {art_dim[0]}x{art_dim[1]} exceeds 1280 long edge")
    else:
        problems.append("cover.jpg missing from album folder")

    return problems, ok, art_dim


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--local-root", default=str(LOCAL_OUT),
                    help="where the render wrote (default PIPELINE_LOCAL_OUT)")
    ap.add_argument("--dest-root", default=str(DEST_ROOT),
                    help="library-shaped output tree (default PIPELINE_OUT)")
    ap.add_argument("--copy", action="store_true",
                    help="copy into the output tree after verifying")
    args = ap.parse_args()

    mpath = MANIFEST_ROOT / args.slug / "manifest.json"
    if not mpath.is_file():
        print(f"ERROR: no manifest at {mpath}")
        return 1
    m = json.loads(mpath.read_text(encoding="utf-8"))
    a = m["album"]

    src_dir = Path(args.local_root) / a["artist_folder"] / a["album_folder"]
    dst_dir = Path(args.dest_root) / a["artist_folder"] / a["album_folder"]
    in_place = src_dir.resolve() == dst_dir.resolve()

    if not src_dir.is_dir():
        print(f"ERROR: rendered album not found: {src_dir}")
        return 1

    expected = [t for d in m["discs"] for t in d["tracks"]]
    print(f"VERIFYING {len(expected)} tracks in {src_dir}")
    print()

    problems, ok, art_dim = verify_album(src_dir, expected)

    if expected:
        first = src_dir / expected[0]["filename"]
        if first.is_file():
            t0 = tags_of(first)
            print("ALBUM TAGS (from first track)")
            for k in ("TALB", "TIT1", "TPE2", "TPE1", "TCOM", "TCON",
                      "TDRC", "GRP1"):
                print(f"  {k:5s} {t0.get(k, '<missing>')}")
            print(f"  APIC  {t0.get('_apic_kb')} KB, id3 {t0.get('_version')}")
            if art_dim:
                print(f"  cover {art_dim[0]}x{art_dim[1]}")
            print()

    total = sum(p.stat().st_size for p in src_dir.glob("*.mp3"))
    print(f"tracks verified: {ok}/{len(expected)}")
    print(f"total size: {total / 1e6:.1f} MB")

    if problems:
        print()
        print(f"PROBLEMS ({len(problems)})")
        for x in problems[:60]:
            print(f"  x {x}")
        if len(problems) > 60:
            print(f"  ... {len(problems) - 60} more")
        if args.copy:
            print()
            print("REFUSING TO COPY while problems remain.")
        return 1

    print()
    print("ALL CHECKS PASSED")

    if in_place:
        print("album is already in the output tree, nothing to copy")
        return 0

    if not args.copy:
        print("(not copying - pass --copy to deliver)")
        return 0

    dst_dir.parent.mkdir(parents=True, exist_ok=True)
    if dst_dir.exists():
        print(f"destination exists, replacing: {dst_dir}")
        shutil.rmtree(dst_dir)
    shutil.copytree(src_dir, dst_dir)
    n = len(list(dst_dir.glob("*")))
    print(f"COPIED {n} files to {dst_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
