#!/usr/bin/env python3
"""
Deep inspection of one intake item. Read-only.

Unlike scan.py (which summarises the whole intake), this dumps everything
about a single album so decisions can be made: full archive listings, every
CUE track with computed durations, every image with its aspect ratio, text
encoding of cues and EAC logs, and embedded-cuesheet detection.

Usage:
    python3 ~/catlog-data/inspect.py "ABprinceET.part1.rar"
    python3 ~/catlog-data/inspect.py "Schubert - Alban Berg Quartett"
    python3 ~/catlog-data/inspect.py --all
"""

import argparse
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

INTAKE = Path(os.environ.get("CATLOG_INTAKE",
                            Path.home() / "catlog-data" / "intake"))

AUDIO_EXT = {
    ".mp3", ".flac", ".m4a", ".aac", ".wav", ".aiff", ".aif",
    ".ogg", ".opus", ".ape", ".wv", ".wma", ".dsf", ".dff", ".mka",
}
ARCHIVE_EXT = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
IGNORE_NAMES = {".DS_Store", "Thumbs.db"}
IGNORE_PREFIX = "._"


# ------------------------------------------------------------------ text

def sniff_text_encoding(path, limit=8192):
    """Return (encoding, confident) for a text file."""
    raw = path.read_bytes()[:limit]
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
    # Ambiguous single/double-byte legacy encodings. Check for Cyrillic range
    # which is the common case for Russian rips.
    best = None
    for enc in ("cp1251", "koi8_r", "shift_jis", "cp1252"):
        try:
            dec = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        cyr = sum(1 for ch in dec if "\u0400" <= ch <= "\u04ff")
        if cyr > len(dec) * 0.05:
            return (enc + " (likely, cyrillic)", True)
        if best is None:
            best = enc
    return ((best or "unknown") + " (ambiguous)", False)


# ------------------------------------------------------------------ images

def image_size(path):
    """(width, height) for JPEG/PNG/GIF, else None."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
        if head[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", head[6:10])
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


def squareness(w, h):
    """1.0 = perfectly square. Lower = more elongated."""
    if not w or not h:
        return 0.0
    return min(w, h) / max(w, h)


# ------------------------------------------------------------------ cue

def parse_cue(path):
    """Full CUE parse with per-track timings and computed durations."""
    enc, confident = sniff_text_encoding(path)
    base = enc.replace(" (likely, cyrillic)", "").replace(" (ambiguous)", "")
    base = base.replace("-bom", "")
    if base == "utf-16-bom":
        base = "utf-16"
    try:
        text = path.read_text(encoding=base, errors="replace")
    except Exception:
        text = path.read_text(errors="replace")

    def msf_to_frames(msf):
        m = re.match(r"(\d+):(\d+):(\d+)", msf.strip())
        if not m:
            return None
        mm, ss, ff = (int(x) for x in m.groups())
        return (mm * 60 + ss) * 75 + ff

    out = {
        "encoding": enc, "encoding_confident": confident,
        "album_title": None, "album_performer": None,
        "catalog": None, "rem": [], "files": [], "tracks": [],
    }
    cur = None
    for line in text.splitlines():
        s = line.strip()
        up = s.upper()
        if up.startswith("REM "):
            out["rem"].append(s[4:])
        elif up.startswith("CATALOG "):
            out["catalog"] = s[8:].strip()
        elif up.startswith("FILE "):
            q = s.split('"')
            out["files"].append(q[1] if len(q) > 1 else s[5:].strip())
        elif up.startswith("TRACK "):
            parts = s.split()
            cur = {"number": int(parts[1]) if len(parts) > 1 else None,
                   "title": None, "performer": None,
                   "index00": None, "index01": None,
                   "pregap_frames": None}
            out["tracks"].append(cur)
        elif cur is not None:
            if up.startswith("TITLE "):
                q = s.split('"')
                cur["title"] = q[1] if len(q) > 1 else s[6:].strip()
            elif up.startswith("PERFORMER "):
                q = s.split('"')
                cur["performer"] = q[1] if len(q) > 1 else s[10:].strip()
            elif up.startswith("INDEX 00 "):
                cur["index00"] = msf_to_frames(s[9:])
            elif up.startswith("INDEX 01 "):
                cur["index01"] = msf_to_frames(s[9:])
        if s.upper().startswith("TITLE ") and cur is None:
            q = s.split('"')
            out["album_title"] = q[1] if len(q) > 1 else s[6:].strip()
        if s.upper().startswith("PERFORMER ") and cur is None:
            q = s.split('"')
            out["album_performer"] = q[1] if len(q) > 1 else s[10:].strip()

    # durations from INDEX 01 boundaries
    for i, t in enumerate(out["tracks"]):
        start = t["index01"]
        nxt = None
        for later in out["tracks"][i + 1:]:
            if later["index01"] is not None:
                nxt = later["index01"]
                break
        if start is not None and nxt is not None:
            t["duration_frames"] = nxt - start
        else:
            t["duration_frames"] = None
        if t["index00"] is not None and t["index01"] is not None:
            t["pregap_frames"] = t["index01"] - t["index00"]
    return out


def frames_to_msf(fr):
    if fr is None:
        return "?"
    mm, rem = divmod(fr, 60 * 75)
    ss, ff = divmod(rem, 75)
    return f"{mm}:{ss:02d}.{ff:02d}"


# ------------------------------------------------------------------ audio

def audio_props(path):
    out = {"format": None, "bitrate_kbps": None, "duration_s": None,
           "sample_rate": None, "channels": None, "bits": None,
           "embedded_cuesheet": False, "tags": {}, "error": None}
    try:
        from mutagen import File as MFile
        m = MFile(str(path))
        if m is None:
            out["error"] = "mutagen does not recognise this file"
            return out
        out["format"] = type(m).__name__
        info = getattr(m, "info", None)
        if info is not None:
            br = getattr(info, "bitrate", None)
            out["bitrate_kbps"] = round(br / 1000) if br else None
            out["duration_s"] = round(getattr(info, "length", 0) or 0, 1)
            out["sample_rate"] = getattr(info, "sample_rate", None)
            out["channels"] = getattr(info, "channels", None)
            out["bits"] = getattr(info, "bits_per_sample", None)
        tags = getattr(m, "tags", None)
        if tags:
            try:
                for k in list(tags.keys()):
                    if k.upper().startswith("CUESHEET") or k.upper() == "CUESHEET":
                        out["embedded_cuesheet"] = True
                    if isinstance(k, str) and k.upper() in (
                            "TITLE", "ARTIST", "ALBUM", "DATE", "GENRE",
                            "TIT2", "TPE1", "TALB", "TDRC", "TCON", "TIT1"):
                        v = tags[k]
                        out["tags"][k] = str(v)[:120]
            except Exception:
                pass
    except Exception as exc:
        out["error"] = str(exc)[:150]
    return out


# ------------------------------------------------------------------ archive

def archive_entries(path):
    """List entries via 7z. Returns (entries, error)."""
    try:
        res = subprocess.run(
            ["7z", "l", "-slt", "-ba", str(path)],
            capture_output=True, text=True, timeout=300,
        )
    except Exception as exc:
        return (None, str(exc)[:200])
    if res.returncode not in (0, 1):
        return (None, (res.stderr or res.stdout).strip()[:400])
    entries = []
    cur = {}
    for line in res.stdout.splitlines():
        if not line.strip():
            if cur:
                entries.append(cur)
                cur = {}
            continue
        if " = " in line:
            k, v = line.split(" = ", 1)
            cur[k.strip()] = v.strip()
    if cur:
        entries.append(cur)
    return (entries, None)


# ------------------------------------------------------------------ report

def dump_item(entry, lines):
    w = lines.append
    path = entry if entry.is_absolute() else INTAKE / entry.name
    name = path.name

    w("=" * 78)
    w(f"ITEM: {name}")
    w("=" * 78)

    if not path.exists():
        w("  !! does not exist")
        return

    ext = path.suffix.lower()

    # ---------------- archive
    if path.is_file() and ext in ARCHIVE_EXT:
        size = path.stat().st_size
        w(f"archive: {size / 1e6:.1f} MB")
        m = re.match(r"^(.*?)\.part(\d+)\.rar$", path.name, re.I)
        if m:
            w(f"  multi-volume RAR: set '{m.group(1)}', this is part {m.group(2)}")
            siblings = sorted(path.parent.glob(f"{m.group(1)}.part*.rar"))
            w(f"  sibling volumes present: {len(siblings)}")
            for s in siblings:
                w(f"    {s.name}  {s.stat().st_size / 1e6:.1f} MB")
        entries, err = archive_entries(path)
        if err:
            w(f"  !! listing failed: {err}")
            return
        w(f"  entries: {len(entries)}")
        by_ext = {}
        total = 0
        for e in entries:
            nm = e.get("Path", "")
            sz = e.get("Size") or "0"
            try:
                sz = int(sz)
            except ValueError:
                sz = 0
            total += sz
            pe = Path(nm).suffix.lower()
            by_ext.setdefault(pe, []).append((nm, sz))
        w(f"  uncompressed total: {total / 1e6:.1f} MB")
        w("")
        for pe in sorted(by_ext, key=lambda x: (-len(by_ext[x]), x)):
            group = by_ext[pe]
            label = pe if pe else "(no extension)"
            w(f"  -- {label}  x{len(group)}")
            show = group if len(group) <= 8 else group[:8]
            for nm, sz in show:
                w(f"       {sz / 1e6:9.2f} MB  {nm}")
            if len(group) > 8:
                w(f"       ... {len(group) - 8} more")
        audio = [e for e in entries
                 if Path(e.get("Path", "")).suffix.lower() in AUDIO_EXT]
        cues = [e for e in entries
                if Path(e.get("Path", "")).suffix.lower() == ".cue"]
        w("")
        w(f"  audio files: {len(audio)}")
        for e in audio:
            w(f"    {e.get('Path')}  ({e.get('Size', '?')} bytes)")
        if cues:
            w(f"  cue files: {len(cues)}")
            for e in cues:
                w(f"    {e.get('Path')}")
        return

    # ---------------- directory
    if path.is_dir():
        audio, images, cues, logs, others = [], [], [], [], []
        for dirpath, dirnames, filenames in os.walk(path):
            for fn in filenames:
                if fn in IGNORE_NAMES or fn.startswith(IGNORE_PREFIX):
                    continue
                f = Path(dirpath) / fn
                e = f.suffix.lower()
                if e in AUDIO_EXT:
                    audio.append(f)
                elif e in IMAGE_EXT:
                    images.append(f)
                elif e == ".cue":
                    cues.append(f)
                elif e == ".log":
                    logs.append(f)
                else:
                    others.append(f)

        w(f"audio files: {len(audio)}")
        for a in sorted(audio):
            p = audio_props(a)
            w(f"  {a.name}")
            w(f"    {p['format']}  {p['duration_s']}s  "
              f"{p['sample_rate']}Hz  {p['channels']}ch  "
              f"{p['bits'] or '?'}bit  {p['bitrate_kbps'] or '?'}kbps")
            if p["error"]:
                w(f"    !! {p['error']}")
            if p["embedded_cuesheet"]:
                w("    NOTE: file carries an EMBEDDED CUESHEET tag")
            for k, v in p["tags"].items():
                w(f"    tag {k} = {v}")

        if images:
            w("")
            w(f"images: {len(images)}")
            for im in sorted(images):
                sz = im.stat().st_size
                dim = image_size(im)
                if dim:
                    w_, h_ = dim
                    sq = squareness(w_, h_)
                    note = ""
                    if sq >= 0.95:
                        note = "  <- near-square, likely front cover"
                    elif sq <= 0.75:
                        note = "  <- elongated, likely booklet/spread"
                    w(f"  {im.name:28s} {w_:5d}x{h_:<5d} sq={sq:.2f} "
                      f"{sz / 1e6:6.2f} MB{note}")
                else:
                    w(f"  {im.name:28s} dimensions unread "
                      f"{sz / 1e6:6.2f} MB")

        if cues:
            w("")
            for c in sorted(cues):
                info = parse_cue(c)
                w(f"CUE: {c.name}")
                w(f"  encoding: {info['encoding']}"
                  f"{'' if info['encoding_confident'] else '  <- UNSURE, verify titles'}")
                w(f"  album title: {info['album_title']}")
                w(f"  album performer: {info['album_performer']}")
                w(f"  catalog: {info['catalog']}")
                w(f"  referenced files: {', '.join(info['files']) or 'none'}")
                if info["rem"]:
                    w(f"  rem: {'; '.join(info['rem'][:6])}")
                w(f"  tracks: {len(info['tracks'])}")
                w(f"    {'#':>3}  {'start':>8}  {'dur':>8}  {'gap':>6}  title")
                for t in info["tracks"]:
                    w(f"    {t['number']:>3}  {frames_to_msf(t['index01']):>8}  "
                      f"{frames_to_msf(t.get('duration_frames')):>8}  "
                      f"{frames_to_msf(t.get('pregap_frames')):>6}  "
                      f"{t['title']}")
                total_fr = sum(t.get("duration_frames") or 0
                               for t in info["tracks"])
                w(f"  total from cue: {frames_to_msf(total_fr)}")

        if logs:
            w("")
            for lg in sorted(logs):
                enc, conf = sniff_text_encoding(lg)
                w(f"LOG: {lg.name}  encoding: {enc}"
                  f"{'' if conf else '  <- UNSURE'}")

        if others:
            w("")
            w(f"other files: {[o.name for o in others]}")
        return

    # ---------------- loose file
    w(f"file: {path.stat().st_size / 1e6:.1f} MB")
    if ext in AUDIO_EXT:
        p = audio_props(path)
        for k, v in p.items():
            if k != "tags":
                w(f"  {k}: {v}")
        for k, v in p["tags"].items():
            w(f"  tag {k} = {v}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("items", nargs="*", help="item names inside intake")
    ap.add_argument("--all", action="store_true", help="inspect every item")
    args = ap.parse_args()

    if not INTAKE.is_dir():
        print(f"ERROR: {INTAKE} not found")
        return 1

    if args.all:
        targets = sorted(p for p in INTAKE.iterdir()
                         if p.name not in IGNORE_NAMES
                         and not p.name.startswith(IGNORE_PREFIX))
    elif args.items:
        targets = [Path(i) if Path(i).is_absolute() else INTAKE / i
                   for i in args.items]
    else:
        print("Give one or more item names, or --all")
        return 1

    lines = []
    for t in targets:
        dump_item(t, lines)
        lines.append("")
    text = "\n".join(lines)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
