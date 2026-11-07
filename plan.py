#!/usr/bin/env python3
"""
Stage 1 - PLAN. Builds an approval manifest for one album. Writes nothing else.

Reads a per-album metadata file (YAML-ish JSON) describing the album-level tags,
plus the CUE sheet(s) in the source folders, and emits a manifest listing every
output track with its computed start/duration and the exact tags to be written.

Nothing is encoded, split, or tagged at this stage.

Usage:
    python3 plan.py --meta ~/catlog-data/meta/borodin-prince-igor.json
    python3 plan.py --meta ... --intake /path/to/intake --manifest-root /path
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_INTAKE = Path(os.environ.get(
    "CATLOG_INTAKE", Path.home() / "catlog-data" / "intake"))
DEFAULT_MANIFEST_ROOT = Path(os.environ.get(
    "CATLOG_MANIFESTS", Path.home() / "catlog-data" / "manifests"))

AUDIO_EXT = {
    ".mp3", ".flac", ".m4a", ".aac", ".wav", ".aiff", ".aif",
    ".ogg", ".opus", ".ape", ".wv", ".wma", ".dsf", ".dff", ".mka",
}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}


# ------------------------------------------------------------------ misc

def msf_to_seconds(msf):
    m = re.match(r"(\d+):(\d+):(\d+)", msf.strip())
    if not m:
        return None
    mm, ss, ff = (int(x) for x in m.groups())
    return (mm * 60 + ss) + ff / 75.0


def sniff_text_encoding(path, limit=8192):
    raw = path.read_bytes()[:limit]
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        raw.decode("ascii")
        return "ascii"
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    return "cp1251"


def read_cue(path):
    enc = sniff_text_encoding(path)
    if enc == "ascii":
        enc = "utf-8"
    try:
        text = path.read_text(encoding=enc, errors="replace")
    except Exception:
        text = path.read_text(errors="replace")

    out = {"path": str(path), "encoding": enc, "files": [],
           "tracks": [], "title": None, "performer": None, "rem": []}
    cur = None
    cur_file = None
    for line in text.splitlines():
        s = line.strip()
        up = s.upper()
        if up.startswith("FILE "):
            q = s.split('"')
            out["files"].append(q[1] if len(q) > 1 else s[5:].strip())
            cur_file = out["files"][-1]
        elif up.startswith("TRACK "):
            parts = s.split()
            cur = {"number": int(parts[1]), "title": None, "index01": None, "file": cur_file}
            out["tracks"].append(cur)
        elif up.startswith("REM "):
            out["rem"].append(s[4:])
        elif up.startswith("TITLE "):
            q = s.split('"')
            val = q[1] if len(q) > 1 else s[6:].strip()
            if cur is None:
                out["title"] = val
            else:
                cur["title"] = val
        elif up.startswith("PERFORMER "):
            q = s.split('"')
            val = q[1] if len(q) > 1 else s[10:].strip()
            if cur is None:
                out["performer"] = val
        elif up.startswith("INDEX 01 ") and cur is not None:
            cur["index01"] = msf_to_seconds(s[9:])
    return out


def audio_duration(path):
    """Duration in seconds via ffprobe."""
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=120)
        return float(res.stdout.strip())
    except Exception:
        return None


def image_size(path):
    import struct
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
        if head[:2] != b"\xff\xd8":
            return None
        with open(path, "rb") as fh:
            fh.seek(2)
            while True:
                b = fh.read(1)
                if not b:
                    return None
                if b != b"\xff":
                    continue
                marker = fh.read(1)
                while marker == b"\xff":
                    marker = fh.read(1)
                if not marker:
                    return None
                code = marker[0]
                if code in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6,
                            0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    fh.read(3)
                    h, w = struct.unpack(">HH", fh.read(4))
                    return (w, h)
                seglen = struct.unpack(">H", fh.read(2))[0]
                if seglen < 2:
                    return None
                fh.seek(seglen - 2, 1)
    except Exception:
        return None


def target_size(w, h, max_edge=1280):
    """Downscale so the long edge is max_edge. Never upscale."""
    if not w or not h:
        return (None, None)
    if max(w, h) <= max_edge:
        return (w, h)
    f = max_edge / max(w, h)
    nw, nh = round(w * f), round(h * f)
    nw -= nw % 2
    nh -= nh % 2
    return (nw, nh)


def safe_filename(name):
    name = name.replace("/", "-").replace("\x00", "")
    name = re.sub(r"\s+", " ", name).strip()
    return name.rstrip(". ")


def normalize_act(name):
    m = re.match(r"^Act (\d+)", name)
    if m and name[m.end():m.end() + 1] == ":":
        return "Act " + m.group(1) + " -" + name[m.end() + 1:]
    return name


def safe_filename(name):
    name = name.replace(chr(0), "")
    for bad in (47, 92, 58, 63, 34, 42, 60, 62, 124, 8220, 8221):
        name = name.replace(chr(bad), "_")
    name = re.sub(r"\s+", " ", name).strip()
    return name.rstrip(". ")


# ------------------------------------------------------------------ plan

def scan_folder_tracks(folder):
    """Enumerate audio files in a folder as a synthetic cue-less track list."""
    names = sorted(p.name for p in folder.iterdir()
                   if p.is_file() and p.suffix.lower() in AUDIO_EXT
                   and not p.name.startswith("._"))
    tracks = []
    for i, name in enumerate(names, start=1):
        tracks.append({"number": i, "title": None, "file": name,
                       "index01": None})
    return {"files": names, "tracks": tracks, "title": None,
            "performer": None, "rem": [], "encoding": "n/a"}


def build(meta, intake, manifest_root):
    album = meta["album"]
    artist_dir = album["artist_folder"]
    album_dir = album["album_folder"]
    errors = []
    warnings = []

    artwork_path = None
    art_dim = None
    if album.get("artwork"):
        cand = intake / album["artwork"]
        if cand.is_file():
            artwork_path = cand
            art_dim = image_size(cand)
        else:
            errors.append(f"artwork not found: {album['artwork']}")

    if artwork_path is None:
        warnings.append("NO ARTWORK - will embed nothing")
    elif art_dim:
        w, h = art_dim
        tw, th = target_size(w, h)
        if min(w, h) < 600:
            warnings.append(
                f"artwork {w}x{h} is below the 600px floor")
        album["artwork_resize"] = {"from": f"{w}x{h}", "to": f"{tw}x{th}"}
    else:
        warnings.append("artwork dimensions unreadable")

    discs = []
    for d in meta["discs"]:
        disc_no = int(d["tpos"])
        if d.get("cue"):
            cue_path = intake / d["cue"]
            if not cue_path.is_file():
                errors.append(f"cue not found: {d['cue']}")
                continue
            cue = read_cue(cue_path)
            if not cue["files"]:
                errors.append(f"cue has no FILE line: {d['cue']}")
                continue
        elif d.get("folder"):
            cue_path = None
            src_dir = intake / d["folder"]
            if not src_dir.is_dir():
                errors.append(f"folder not found: {d['folder']}")
                continue
            cue = scan_folder_tracks(src_dir)
            if not cue["files"]:
                errors.append(f"no audio files in {d['folder']}")
                continue
        else:
            errors.append(f"disc {disc_no}: needs either cue or folder")
            continue
        base_dir = (cue_path.parent if cue_path
                    else (intake / d["folder"]))
        if len(cue["files"]) != 1:
            tracks = []
            total = 0.0
            for t in cue["tracks"]:
                tfile = t.get("file")
                if not tfile:
                    errors.append(f"disc {disc_no} track {t["number"]}: no FILE")
                    continue
                tsrc = base_dir / tfile
                if not tsrc.is_file():
                    errors.append(f"disc {disc_no}: missing {tfile}")
                    continue
                tlen = audio_duration(tsrc)
                if tlen is None:
                    errors.append(f"disc {disc_no}: cannot read {tfile}")
                    continue
                total += tlen
                mvnm = normalize_act((t["title"] or "").strip())
                ov = (d.get("tracks_override") or {}).get(str(t["number"])) or {}
                if ov.get("mvnm"):
                    mvnm = normalize_act(ov["mvnm"])
                tit1 = ov.get("tit1") or d.get("tit1") or album["tit1"]
                tpe1 = ov.get("tpe1") or album["tpe1"]
                roman = ov.get("roman") or ""
                lead = (roman + ". ") if roman else ""
                if mvnm:
                    tit2 = (tit1 + " " + lead + mvnm).strip()
                else:
                    # single-movement work: the work title IS the title
                    tit2 = tit1
                mvin = ov.get("mvin") or ""
                stem = mvnm or tit1.split(chr(8212))[0].strip()
                fname = f"{disc_no}-{t["number"]:02d} {safe_filename(stem)}.mp3"
                tracks.append({
                    "number": t["number"],
                    "filename": fname,
                    "mvnm": mvnm,
                    "mvin": mvin,
                    "tit1": tit1,
                    "tit2": tit2,
                    "tpe1": tpe1,
                    "work": d.get("work") or album.get("work"),
                    "start_s": 0.0,
                    "duration_s": round(tlen, 3),
                    "source": str(Path(base_dir.relative_to(intake)) / tfile),
                })
            discs.append({
                "tpos": disc_no,
                "tpos_total": len(meta["discs"]),
                "cue": str(cue_path.relative_to(intake)) if cue_path else None,
                "source": "(per-track files)",
                "source_duration_s": round(total, 3),
                "track_count": len(tracks),
                "tracks": tracks,
            })
            continue

        src = base_dir / cue["files"][0]
        if not src.is_file():
            # cue may reference the file by a different name
            alts = [p for p in base_dir.iterdir()
                    if p.suffix.lower() in AUDIO_EXT]
            if len(alts) == 1:
                warnings.append(
                    f"cue FILE '{cue['files'][0]}' not found, using {alts[0].name}")
                src = alts[0]
            else:
                errors.append(f"source audio not found for {d['cue']}")
                continue

        dur = audio_duration(src)
        if dur is None:
            errors.append(f"could not read duration of {src.name}")
            continue

        tracks = []
        prev_title = None
        for i, t in enumerate(cue["tracks"]):
            start = t["index01"]
            if start is None:
                start = 0.0
                warnings.append(f"disc {disc_no} track {t['number']}: no INDEX 01, using 0")
            nxt = None
            for later in cue["tracks"][i + 1:]:
                if later["index01"] is not None:
                    nxt = later["index01"]
                    break
            end = nxt if nxt is not None else dur
            length = round(end - start, 3)
            if length <= 0:
                errors.append(
                    f"disc {disc_no} track {t['number']}: non-positive duration")
                continue

            mvnm = normalize_act((t["title"] or "").strip())
            ov = (d.get("tracks_override") or {}).get(str(t["number"])) or {}
            if ov.get("mvnm"):
                mvnm = normalize_act(ov["mvnm"])
            tit1 = ov.get("tit1") or d.get("tit1") or album["tit1"]
            roman = ov.get("roman") or ""
            lead = (roman + ". ") if roman else ""
            tit2 = (tit1 + " " + lead + mvnm).strip()
            mvin = ov.get("mvin") or ""

            fname = f"{disc_no}-{t['number']:02d} {safe_filename(mvnm)}.mp3"

            tracks.append({
                "number": t["number"],
                "filename": fname,
                "mvnm": mvnm,
                "mvin": mvin,
                "tit1": tit1,
                "tit2": tit2,
                "work": d.get("work") or album.get("work"),
                "start_s": round(start, 3),
                "duration_s": length,
            })
            prev_title = mvnm

        covered = sum(t["duration_s"] for t in tracks)
        if abs(covered - dur) > 2.0:
            warnings.append(
                f"disc {disc_no}: tracks cover {covered:.1f}s of {dur:.1f}s "
                f"(diff {dur - covered:+.1f}s - tail audio may be dropped)")

        discs.append({
            "tpos": disc_no,
            "tpos_total": len(meta["discs"]),
            "cue": str(cue_path.relative_to(intake)) if cue_path else None,
            "source": str(src.relative_to(intake)),
            "source_duration_s": round(dur, 3),
            "track_count": len(tracks),
            "tracks": tracks,
        })

    manifest = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "album_slug": meta["slug"],
        "album": album,
        "artist_folder": artist_dir,
        "album_folder": album_dir,
        "destination": str(Path(artist_dir) / album_dir),
        "artwork": {
            "source": album.get("artwork"),
            "resize": album.get("artwork_resize"),
            "note": album.get("artwork_note", ""),
        },
        "discs": discs,
        "warnings": warnings,
        "errors": errors,
        "approved": False,
    }
    return manifest


def render_text(m):
    L = []
    w = L.append
    a = m["album"]
    w("=" * 74)
    w(f"ALBUM PLAN: {a['talb']}")
    w("=" * 74)
    w(f"destination: {m['destination']}")
    w("")
    w("ALBUM TAGS")
    for k in ("talb", "tpe2", "tpe1", "tcom", "tcon", "tdrc", "grp1"):
        if a.get(k):
            w(f"  {k.upper():6s} {a[k]}")
    w("")
    art = m["artwork"]
    if art.get("source"):
        rz = art.get("resize") or {}
        w(f"ARTWORK  {art['source']}")
        if rz:
            w(f"  resize {rz.get('from')} -> {rz.get('to')} (long edge 1280)")
        if art.get("note"):
            w(f"  note: {art['note']}")
    else:
        w("ARTWORK  none")
    w("")
    total = 0
    for d in m["discs"]:
        w(f"--- DISC {d['tpos']} of {d['tpos_total']}  "
          f"({d['track_count']} tracks, {d['source_duration_s'] / 60:.1f} min)")
        w(f"    source: {d['source']}")
        w(f"    {'#':>3}  {'start':>9}  {'dur':>8}  tit2")
        for t in d["tracks"]:
            mm, ss = divmod(t["start_s"], 60)
            dm, ds = divmod(t["duration_s"], 60)
            w(f"    {t['number']:>3}  {int(mm):02d}:{ss:05.2f}  "
              f"{int(dm):02d}:{ds:05.2f}  {t['tit2']}")
            total += t["duration_s"]
        w("")
    w(f"total audio: {total / 60:.1f} min across {len(m['discs'])} disc(s)")
    if m["warnings"]:
        w("")
        w("WARNINGS")
        for x in m["warnings"]:
            w(f"  ! {x}")
    if m["errors"]:
        w("")
        w("ERRORS - CANNOT RENDER")
        for x in m["errors"]:
            w(f"  x {x}")
    w("")
    w(f"approved: {m['approved']}   "
      f"(set 'approved': true in the JSON to render)")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--intake", default=str(DEFAULT_INTAKE))
    ap.add_argument("--manifest-root", default=str(DEFAULT_MANIFEST_ROOT))
    args = ap.parse_args()

    meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    intake = Path(args.intake)

    m = build(meta, intake, Path(args.manifest_root))

    outdir = Path(args.manifest_root) / meta["slug"]
    outdir.mkdir(parents=True, exist_ok=True)
    mpath = outdir / "manifest.json"

    # never silently overwrite an approved manifest
    if mpath.exists():
        try:
            old = json.loads(mpath.read_text(encoding="utf-8"))
        except Exception:
            old = {}
        if old.get("approved") and not m["approved"]:
            print(f"REFUSING: {mpath} is marked approved. "
                  f"Move it aside or re-approve explicitly.")
            return 1
        m["approved"] = bool(old.get("approved")) and not m["errors"]

    mpath.write_text(json.dumps(m, indent=2, ensure_ascii=False),
                     encoding="utf-8")

    print(render_text(m))
    print(f"manifest: {mpath}")
    return 1 if m["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
