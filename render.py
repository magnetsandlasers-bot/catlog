#!/usr/bin/env python3
"""
Stage 2 - RENDER. Splits, encodes to MP3 320, tags, and embeds artwork.

Refuses to run unless the manifest says "approved": true.

Reads manifests/<slug>/manifest.json, writes finished MP3s to
out/<Artist Folder>/<Album Folder>/ and a report to reports/<slug>/.

The Artwork is downscaled once (long edge <= 1280, never upscaled) and the
same image is embedded in every track.

Usage:
    python3 render.py --slug borodin-prince-igor-tchakarov
    python3 render.py --slug ... --dry-run
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

INTAKE = Path(os.environ.get(
    "PIPELINE_INTAKE", Path.home() / "pipeline" / "intake"))
OUT_ROOT = Path(os.environ.get(
    "PIPELINE_OUT", Path.home() / "pipeline" / "out"))
MANIFEST_ROOT = Path(os.environ.get(
    "PIPELINE_MANIFESTS", Path.home() / "pipeline" / "manifests"))
REPORT_ROOT = Path(os.environ.get(
    "PIPELINE_REPORTS", Path.home() / "pipeline" / "reports"))
WORK_ROOT = Path(os.environ.get(
    "PIPELINE_WORK", Path.home() / "pipeline" / "work"))

LAME_BITRATE = "320k"


def sh(cmd, timeout=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def make_artwork(manifest, workdir, log):
    """Downscale the chosen artwork into workdir. Returns (path, note)."""
    art = manifest.get("artwork", {})
    src = art.get("source")
    if not src:
        log.append("ARTWORK: none specified")
        return (None, "none")
    src_path = INTAKE / src
    if not src_path.is_file():
        log.append(f"ARTWORK: source missing: {src}")
        return (None, "missing")

    resize = art.get("resize") or {}
    to = resize.get("to")
    dst = workdir / "cover.jpg"

    if to and "x" in str(to):
        w, h = to.split("x")
        vf = f"scale={w}:{h}:flags=lanczos"
    else:
        vf = "scale='min(1280,iw)':-2:flags=lanczos"

    res = sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
              "-i", str(src_path), "-vf", vf, "-q:v", "3", str(dst)])
    if res.returncode != 0 or not dst.exists():
        log.append(f"ARTWORK: conversion failed: {res.stderr[:300]}")
        return (None, "conversion failed")

    kb = dst.stat().st_size // 1024
    log.append(f"ARTWORK: {src.split('/')[-1]} -> {to} ({kb} KB)")
    return (dst, "ok")


def encode_track(src, dst, start, dur, log):
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.3f}", "-i", str(src),
        "-t", f"{dur:.3f}",
        "-map_metadata", "-1", "-vn",
        "-c:a", "libmp3lame", "-b:a", LAME_BITRATE,
        "-compression_level", "0",
        "-id3v2_version", "4", "-write_id3v1", "0",
        str(dst),
    ]
    res = sh(cmd, timeout=1800)
    if res.returncode != 0 or not dst.exists():
        log.append(f"  ENCODE FAILED {dst.name}: {res.stderr[:200]}")
        return False
    return True


def tag_track(path, meta, cover_path, log):
    from mutagen.id3 import (ID3, TIT1, TIT2, TPE1, TPE2, TALB, TCOM,
                             TCON, TDRC, TRCK, TPOS, GRP1, MVNM, MVIN, APIC)
    try:
        try:
            tags = ID3(str(path))
        except Exception:
            tags = ID3()
        tags.delall("COMM")
        tags.delall("TSSE")   # "Lavf..." encoder noise from ffmpeg
        tags.delall("TENC")
        tags.add(TIT1(encoding=3, text=meta["tit1"]))
        tags.add(TIT2(encoding=3, text=meta["tit2"]))
        tags.add(TPE1(encoding=3, text=meta["tpe1"]))
        tags.add(TPE2(encoding=3, text=meta["tpe2"]))
        tags.add(TALB(encoding=3, text=meta["talb"]))
        tags.add(TCOM(encoding=3, text=meta["tcom"]))
        tags.add(TCON(encoding=3, text=meta["tcon"]))
        tags.add(TDRC(encoding=3, text=meta["tdrc"]))
        tags.add(TRCK(encoding=3, text=str(meta["trck"])))
        tags.add(TPOS(encoding=3, text=meta["tpos"]))
        tags.add(GRP1(encoding=3, text=meta["grp1"]))
        if meta.get("mvnm"):
            tags.add(MVNM(encoding=3, text=meta["mvnm"]))
        if meta.get("mvin"):
            tags.add(MVIN(encoding=3, text=meta["mvin"]))
        if cover_path and cover_path.exists():
            tags.add(APIC(
                encoding=3, mime="image/jpeg", type=3, desc="Cover",
                data=cover_path.read_bytes()))
        tags.save(str(path), v2_version=4)
        return True
    except Exception as exc:
        log.append(f"  TAG FAILED {path.name}: {exc}")
        return False


def verify(path):
    """Read back what we wrote."""
    from mutagen.id3 import ID3
    out = {}
    try:
        tags = ID3(str(path))
        for k in ("TIT1", "TIT2", "TPE1", "TPE2", "TALB", "TCOM",
                  "TCON", "TDRC", "TRCK", "TPOS", "GRP1", "MVNM"):
            f = tags.get(k)
            if f is not None:
                try:
                    out[k] = str(f.text[0])
                except Exception:
                    out[k] = str(f)
        apic = tags.getall("APIC")
        if apic:
            kb = len(apic[0].data) // 1024
            out["APIC"] = f"{apic[0].mime} {kb}KB"
        out["_version"] = ".".join(str(x) for x in tags.version)
    except Exception as exc:
        out["_error"] = str(exc)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-unapproved", action="store_true")
    args = ap.parse_args()

    mpath = MANIFEST_ROOT / args.slug / "manifest.json"
    if not mpath.is_file():
        print(f"ERROR: no manifest at {mpath}")
        return 1
    m = json.loads(mpath.read_text(encoding="utf-8"))

    if m.get("errors"):
        print("ERROR: manifest has errors:")
        for e in m["errors"]:
            print(f"  x {e}")
        return 1
    if (not m.get("approved") and not args.allow_unapproved
            and not args.dry_run):
        print("REFUSING: manifest is not approved.")
        print(f"Edit {mpath} and set \"approved\": true, then re-run.")
        return 1

    a = m["album"]
    dest = OUT_ROOT / a["artist_folder"] / a["album_folder"]

    print(f"ALBUM   {a['talb']}")
    print(f"DEST    {dest}")
    print(f"MODE    {'dry run' if args.dry_run else 'RENDER'}")
    print()

    if args.dry_run:
        for d in m["discs"]:
            print(f"disc {d['tpos']}: {d['track_count']} tracks "
                  f"from {d['source']}")
            for t in d["tracks"]:
                print(f"  {t['filename']}  "
                      f"{t['start_s']:.2f}s +{t['duration_s']:.2f}s")
        return 0

    workdir = WORK_ROOT / args.slug
    workdir.mkdir(parents=True, exist_ok=True)
    reportdir = REPORT_ROOT / (
        f"render-{args.slug}-" + time.strftime("%Y%m%d-%H%M%S"))
    reportdir.mkdir(parents=True, exist_ok=True)

    log = []
    log.append(f"ALBUM: {a['talb']}")
    log.append(f"DEST:  {dest}")
    log.append("")

    cover, art_note = make_artwork(m, workdir, log)
    if not cover:
        log.append("WARNING: rendering with NO artwork")

    dest.mkdir(parents=True, exist_ok=True)
    disc_total = len(m["discs"])
    counts = {"ok": 0, "fail": 0}

    for d in m["discs"]:
        log.append(f"--- disc {d['tpos']}/{disc_total}")
        disc_src = INTAKE / d["source"]
        if not any(t.get("source") for t in d["tracks"]) and not disc_src.is_file():
            log.append(f"  SOURCE MISSING: {d['source']}")
            counts["fail"] += d["track_count"]
            continue
        for t in d["tracks"]:
            dst = dest / t["filename"]
            track_src = INTAKE / (t.get("source") or d["source"])
            ok = encode_track(track_src, dst, t["start_s"], t["duration_s"], log)
            if not ok:
                counts["fail"] += 1
                continue
            meta = {
                "tit1": t["tit1"], "tit2": t["tit2"],
                "tpe1": a["tpe1"], "tpe2": a["tpe2"], "talb": a["talb"],
                "tcom": a["tcom"], "tcon": a["tcon"], "tdrc": a["tdrc"],
                "trck": t["number"],
                "tpos": f"{d['tpos']}/{disc_total}",
                "grp1": a["grp1"], "mvnm": t["mvnm"],
                "mvin": t.get("mvin", ""),
            }
            if not tag_track(dst, meta, cover, log):
                counts["fail"] += 1
                continue
            counts["ok"] += 1
            log.append(f"  ok  {t['filename']}")

    # save the cover alongside the album for Kodi/other tools
    if cover and cover.exists():
        shutil.copy2(cover, dest / "cover.jpg")
        log.append("")
        log.append("cover.jpg copied into album folder")

    # verification pass
    log.append("")
    log.append("VERIFICATION")
    log.append(f"  files written: {counts['ok']}, failures: {counts['fail']}")
    sample = None
    for d in m["discs"]:
        if d["tracks"]:
            sample = dest / d["tracks"][0]["filename"]
            break
    if sample and sample.exists():
        v = verify(sample)
        log.append(f"  sample: {sample.name}")
        for k, val in v.items():
            log.append(f"    {k:9s} {val}")

    total_bytes = sum(p.stat().st_size for p in dest.glob("*.mp3"))
    log.append(f"  total size: {total_bytes / 1e6:.1f} MB")

    text = "\n".join(log)
    (reportdir / "render.txt").write_text(text, encoding="utf-8")
    print(text)
    print()
    print(f"report: {reportdir / 'render.txt'}")
    return 0 if counts["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
