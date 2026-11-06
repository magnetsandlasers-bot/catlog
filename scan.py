#!/usr/bin/env python3
"""
Read-only inventory scan of the classical intake directory.

Walks ~/catlog-data/intake, classifies each top-level item, and writes a report.
Changes nothing. No files are moved, renamed, or written outside reports/.

Usage:
    python3 ~/catlog-data/scan.py
    python3 ~/catlog-data/scan.py --intake /path/to/dir
"""

import argparse
import json
import os
import struct
import subprocess
import sys
from datetime import datetime
from pathlib import Path

INTAKE_DEFAULT = Path(os.environ.get("CATLOG_INTAKE", Path.home() / "catlog-data" / "intake"))
REPORT_ROOT = Path(os.environ.get("CATLOG_REPORTS", Path.home() / "catlog-data" / "reports"))

AUDIO_EXT = {
    ".mp3", ".flac", ".m4a", ".aac", ".wav", ".aiff", ".aif",
    ".ogg", ".opus", ".ape", ".wv", ".wma", ".dsf", ".dff", ".mka",
}
LOSSLESS_EXT = {".flac", ".wav", ".aiff", ".aif", ".ape", ".wv", ".dsf", ".dff"}
ARCHIVE_EXT = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
IGNORE_NAMES = {".DS_Store", "Thumbs.db"}
IGNORE_PREFIX = "._"

ART_GOOD_MIN = 600      # below this -> flag
ART_TARGET_MAX = 1280   # above this -> downscale


# ---------------------------------------------------------------- helpers

def jpeg_png_size(path):
    """(width, height) for JPEG or PNG without external tools. None if unknown."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:2] != b"\xff\xd8":
                return None
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
                # SOF0..SOF15 except DHT(c4) DAC(cc) and RSTn
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


def detect_cue_encoding(path):
    """Best-guess text encoding of a .cue file. Returns (encoding, confident)."""
    try:
        raw = path.read_bytes()[:8192]
    except Exception:
        return ("unreadable", False)
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return ("utf-16-bom", True)
    if raw.startswith(b"\xef\xbb\xbf"):
        return ("utf-8-bom", True)
    try:
        raw.decode("ascii")
        return ("ascii", True)
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("utf-8")
        return ("utf-8", True)
    except UnicodeDecodeError:
        pass
    # Non-UTF8: ambiguous between CP1251 / CP1252 / Shift-JIS. Report ambiguity.
    for enc in ("cp1251", "shift_jis", "cp1252"):
        try:
            raw.decode(enc)
            return (enc + " (ambiguous)", False)
        except UnicodeDecodeError:
            continue
    return ("unknown", False)


def read_cue(path):
    """Parse the parts of a .cue we care about."""
    enc, confident = detect_cue_encoding(path)
    base = enc.replace(" (ambiguous)", "").replace("-bom", "")
    if base == "utf-16-bom":
        base = "utf-16"
    try:
        text = path.read_text(encoding=base, errors="replace")
    except Exception:
        text = path.read_text(errors="replace")

    info = {"encoding": enc, "encoding_confident": confident,
            "tracks": 0, "files": [], "title": None,
            "performer": None, "rem": []}
    for line in text.splitlines():
        s = line.strip()
        up = s.upper()
        if up.startswith("FILE "):
            q = s.split('"')
            info["files"].append(q[1] if len(q) > 1 else s[5:].strip())
        elif up.startswith("TRACK "):
            info["tracks"] += 1
        elif up.startswith("TITLE "):
            q = s.split('"')
            val = q[1] if len(q) > 1 else s[6:].strip()
            if info["title"] is None:
                info["title"] = val
        elif up.startswith("PERFORMER "):
            q = s.split('"')
            val = q[1] if len(q) > 1 else s[10:].strip()
            if info["performer"] is None:
                info["performer"] = val
        elif up.startswith("REM ") and len(info["rem"]) < 40:
            info["rem"].append(s[4:])
    return info


def sniff_audio(path):
    """Format/bitrate/duration via mutagen. Returns dict."""
    out = {"format": None, "bitrate_kbps": None, "duration_s": None,
           "sample_rate": None, "channels": None, "error": None}
    try:
        from mutagen import File as MFile
        m = MFile(str(path), easy=False)
        if m is None:
            out["error"] = "unrecognised by mutagen"
            return out
        out["format"] = type(m).__name__
        info = getattr(m, "info", None)
        if info is not None:
            br = getattr(info, "bitrate", None)
            if br:
                out["bitrate_kbps"] = round(br / 1000)
            out["duration_s"] = round(getattr(info, "length", 0) or 0, 1)
            out["sample_rate"] = getattr(info, "sample_rate", None)
            out["channels"] = getattr(info, "channels", None)
    except Exception as exc:
        out["error"] = str(exc)[:120]
    return out


def embedded_art_sizes(path):
    """List of (description, width, height) for embedded pictures, best effort."""
    found = []
    try:
        from mutagen import File as MFile
        m = MFile(str(path))
        if m is None:
            return found
        tags = getattr(m, "tags", None)
        if tags is None:
            return found
        # ID3 APIC
        keys = []
        try:
            keys = list(tags.keys())
        except Exception:
            return found
        for k in keys:
            frame = tags.get(k)
            if k.startswith("APIC"):
                data = getattr(frame, "data", None)
                desc = getattr(frame, "desc", "") or "(embedded)"
                found.append((desc, data))
        # FLAC / Vorbis
        for k in keys:
            if k.lower() == "metadata_block_picture":
                from base64 import b64decode
                try:
                    from mutagen.flac import Picture
                    pic = Picture(b64decode(tags[k][0]))
                    found.append(("(flac picture)", None))
                    found[-1] = ("(flac picture)", None)
                    found[-1] = (f"(flac picture {pic.width}x{pic.height})", None)
                except Exception:
                    pass
    except Exception:
        pass
    return found


def archive_listing(path):
    """Return (count, names) of entries inside an archive via 7z."""
    try:
        res = subprocess.run(
            ["7z", "l", "-ba", "-slt", str(path)],
            capture_output=True, text=True, timeout=120,
        )
        if res.returncode not in (0, 1):
            return (None, [], res.stderr.strip()[:200])
        names = []
        for block in res.stdout.split("\n\n"):
            for line in block.splitlines():
                if line.startswith("Path = "):
                    names.append(line[7:].strip())
        return (len(names), names, None)
    except Exception as exc:
        return (None, [], str(exc)[:200])


def is_ignored(name):
    return name in IGNORE_NAMES or name.startswith(IGNORE_PREFIX)


# ---------------------------------------------------------------- classify

def classify_dir(root):
    """Classify a directory as a folder of tracks."""
    audio, images, cues, other = [], [], [], []
    subdirs = set()
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        if rel != ".":
            subdirs.add(rel.split(os.sep)[0])
        for fn in filenames:
            if is_ignored(fn):
                continue
            ext = Path(fn).suffix.lower()
            full = Path(dirpath) / fn
            if ext in AUDIO_EXT:
                audio.append(full)
            elif ext in IMAGE_EXT:
                images.append(full)
            elif ext == ".cue":
                cues.append(full)
            else:
                other.append(full)
    return audio, images, cues, other, sorted(subdirs)


def scan_item(entry, intake_root):
    """Produce a record for one top-level intake item."""
    rec = {
        "item": entry.name,
        "path": str(entry),
        "kind": None,
        "flags": [],
        "notes": [],
        "audio_files": 0,
        "total_bytes": 0,
        "formats": {},
        "bitrates": {},
        "artwork": [],
        "artwork_best": None,
        "cue": None,
        "tracks_per_disc_guess": None,
    }

    ext = entry.suffix.lower()

    # ---- archive
    if entry.is_file() and ext in ARCHIVE_EXT:
        rec["kind"] = "archive"
        count, names, err = archive_listing(entry)
        if err:
            rec["flags"].append(f"archive could not be listed: {err}")
        rec["notes"].append(f"{count if count is not None else '?'} entries")
        inner_audio = [n for n in names if Path(n).suffix.lower() in AUDIO_EXT]
        inner_cues = [n for n in names if Path(n).suffix.lower() == ".cue"]
        inner_imgs = [n for n in names if Path(n).suffix.lower() in IMAGE_EXT]
        rec["notes"].append(
            f"inside: {len(inner_audio)} audio, {len(inner_cues)} cue, "
            f"{len(inner_imgs)} image")
        inner_archives = [n for n in names
                          if Path(n).suffix.lower() in ARCHIVE_EXT]
        if inner_archives:
            rec["flags"].append(
                f"nested archives inside ({len(inner_archives)}) - needs multi-pass")
        if len(inner_audio) == 1 and inner_cues:
            rec["kind"] = "archive:image+cue"
        elif len(inner_audio) == 1:
            rec["kind"] = "archive:image_no_cue"
            rec["flags"].append("single audio file, no cue inside archive")
        elif len(inner_audio) == 0:
            rec["flags"].append("no audio files inside archive")
        return rec

    # ---- ISO / other disc images
    if entry.is_file() and ext in (".iso", ".img", ".bin", ".nrg", ".mdf"):
        rec["kind"] = "disc_image"
        rec["flags"].append(f"{ext} image - SACD/DVD extraction not supported in this pass")
        return rec

    # ---- loose audio file at top level
    if entry.is_file() and ext in AUDIO_EXT:
        rec["kind"] = "loose_file"
        rec["audio_files"] = 1
        rec["total_bytes"] = entry.stat().st_size
        a = sniff_audio(entry)
        rec["formats"][a["format"] or "unknown"] = 1
        if a["bitrate_kbps"]:
            rec["bitrates"][f"{a['bitrate_kbps']}k"] = 1
        sibs = [p for p in entry.parent.iterdir() if p.is_file()]
        cue_sibs = [p for p in sibs if p.suffix.lower() == ".cue"]
        if cue_sibs:
            rec["cue"] = str(cue_sibs[0])
            rec["kind"] = "image+cue"
            info = read_cue(cue_sibs[0])
            rec["notes"].append(f"cue: {info['tracks']} tracks, encoding {info['encoding']}")
            if not info["encoding_confident"]:
                rec["flags"].append(
                    f"cue encoding ambiguous ({info['encoding']}) - check titles")
        else:
            rec["flags"].append("single audio file with no cue - cannot split")
        return rec

    # ---- directory
    if entry.is_dir():
        audio, images, cues, other, subdirs = classify_dir(entry)
        rec["audio_files"] = len(audio)
        rec["total_bytes"] = sum(f.stat().st_size for f in audio if f.exists())
        if subdirs:
            rec["notes"].append(
                f"{len(subdirs)} subfolder(s) - possible multi-disc: "
                + ", ".join(subdirs[:6]))

        # formats / bitrates
        for f in audio[:400]:
            a = sniff_audio(f)
            fmt = a["format"] or "unknown"
            rec["formats"][fmt] = rec["formats"].get(fmt, 0) + 1
            if a["bitrate_kbps"]:
                key = f"{a['bitrate_kbps']}k"
                rec["bitrates"][key] = rec["bitrates"].get(key, 0) + 1

        # artwork
        for img in images:
            size = jpeg_png_size(img)
            rec["artwork"].append({
                "file": img.name,
                "width": size[0] if size else None,
                "height": size[1] if size else None,
            })
        if audio:
            emb = embedded_art_sizes(audio[0])
            for desc, _ in emb:
                rec["artwork"].append({"file": f"[embedded] {desc}",
                                       "width": None, "height": None})

        # cue
        if cues:
            info = read_cue(cues[0])
            rec["cue"] = str(cues[0])
            rec["notes"].append(
                f"cue present: {info['tracks']} tracks, encoding {info['encoding']}")
            if not info["encoding_confident"]:
                rec["flags"].append(
                    f"cue encoding ambiguous ({info['encoding']}) - check titles")

        # classify
        if len(audio) == 0:
            rec["kind"] = "folder:no_audio"
            rec["flags"].append("no audio files found")
        elif len(audio) == 1 and cues:
            rec["kind"] = "folder:image+cue"
        elif len(audio) == 1:
            rec["kind"] = "folder:image_no_cue"
            rec["flags"].append("single audio file, no cue - cannot split")
        else:
            rec["kind"] = "folder:tracks"
            if cues:
                cue_files = read_cue(cues[0])["files"]
                if len(cue_files) == len(audio):
                    rec["notes"].append(
                        "pre-split: one file per track, cue FILE count matches")
                else:
                    rec["flags"].append(
                        f"multiple audio files plus a cue with {len(cue_files)} FILE entr(y/ies) - possible redundancy")

        # artwork verdict
        good = [a for a in rec["artwork"]
                if a["width"] and a["height"]
                and min(a["width"], a["height"]) >= ART_GOOD_MIN]
        if not rec["artwork"]:
            rec["flags"].append("NO ARTWORK FOUND")
        elif not good:
            rec["flags"].append(
                f"artwork present but none reaches {ART_GOOD_MIN}px - needs attention")
        else:
            best = max(good, key=lambda a: (
                min(a["width"], a["height"]) / max(a["width"], a["height"]),
                max(a["width"], a["height"]),
            ))
            rec["artwork_best"] = best
            rec["artwork_best"] = best
            long_edge = max(best["width"], best["height"])
            if long_edge > ART_TARGET_MAX:
                rec["notes"].append(
                    f"artwork {best['width']}x{best['height']} will downscale to "
                    f"{ART_TARGET_MAX} long edge")
            else:
                rec["notes"].append(
                    f"artwork {best['width']}x{best['height']} kept as-is")

        # target format verdict
        if any(Path(f).suffix.lower() in LOSSLESS_EXT for f in audio):
            lossless = sum(1 for f in audio
                           if Path(f).suffix.lower() in LOSSLESS_EXT)
            rec["notes"].append(f"{lossless} lossless file(s) - transcode to 320")
        mp3_low = [k for k in rec["bitrates"] if k.endswith("k")
                   and int(k[:-1]) < 320]
        if mp3_low:
            rec["flags"].append(
                "MP3 below 320 present (" + ", ".join(mp3_low) + ") - will not upscale")

        if other:
            rec["notes"].append(
                f"{len(other)} non-audio file(s): "
                + ", ".join(sorted({p.suffix.lower() or p.name for p in other})[:8]))
        return rec

    rec["kind"] = "unclassified"
    rec["flags"].append("not a directory, archive, or known audio file")
    return rec


# ---------------------------------------------------------------- output

def fmt_bytes(n):
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def render(records, stamp, intake_root):
    lines = []
    w = lines.append
    w(f"INTAKE SCAN  {stamp}")
    w(f"source: {intake_root}")
    w(f"items: {len(records)}")
    w("")
    flagged = [r for r in records if r["flags"]]
    w(f"needs attention: {len(flagged)}")
    w("")
    w("=" * 72)
    for r in records:
        w("")
        w(f"[{r['kind']}]  {r['item']}")
        if r["audio_files"]:
            w(f"  audio: {r['audio_files']} file(s), {fmt_bytes(r['total_bytes'])}")
        if r["formats"]:
            w(f"  formats: " + ", ".join(
                f"{k}x{v}" for k, v in sorted(r["formats"].items())))
        if r["bitrates"]:
            w(f"  bitrates: " + ", ".join(
                f"{k}x{v}" for k, v in sorted(r["bitrates"].items())))
        for n in r["notes"]:
            w(f"  . {n}")
        for f in r["flags"]:
            w(f"  ! {f}")
    w("")
    w("=" * 72)
    w("SUMMARY OF FLAGS")
    if not flagged:
        w("  none")
    for r in flagged:
        for f in r["flags"]:
            w(f"  {r['item']}: {f}")
    w("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intake", default=str(INTAKE_DEFAULT))
    args = ap.parse_args()

    try:
        import mutagen  # noqa: F401
    except ImportError:
        print("ERROR: mutagen is not installed.")
        print("  sudo apt install python3-mutagen")
        print("  or: pip install mutagen")
        return 1

    intake = Path(args.intake)
    if not intake.is_dir():
        print(f"ERROR: intake directory not found: {intake}")
        return 1

    entries = sorted(
        [p for p in intake.iterdir() if not is_ignored(p.name)],
        key=lambda p: p.name.lower(),
    )
    if not entries:
        print(f"Nothing in {intake}. Drop albums in and re-run.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = REPORT_ROOT / f"scan-{stamp}"
    outdir.mkdir(parents=True, exist_ok=True)

    records = [scan_item(e, intake) for e in entries]

    text = render(records, stamp, intake)
    (outdir / "scan.txt").write_text(text, encoding="utf-8")
    (outdir / "scan.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

    print(text)
    print(f"report written: {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
