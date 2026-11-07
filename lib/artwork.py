"""Artwork: measure, choose, and resize.

The subtle part is CHOOSING the cover. It is not the largest image in the
folder; booklet spreads are routinely bigger and are nothing like square:

    01.jpg  1412x2889   ratio 0.49   booklet spread
    02.jpg  1386x1797   ratio 0.77   booklet page
    03.jpg  1412x1451   ratio 0.97   the actual cover

Rank on squareness first, pixel count second.
"""

import struct
import subprocess
from pathlib import Path

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
MAX_EDGE = 1280
MIN_ACCEPTABLE = 600

# Filenames that usually denote the front cover, best first.
COVER_HINTS = ("cover", "front", "folder", "album", "case")
# Filenames that never are.
NEVER = ("back", "inlay", "disc", "cd", "spine", "tray", "matrix")


def dimensions(path):
    """(width, height) for JPEG/PNG/GIF using only the standard library."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:6] in (b"GIF87a", b"GIF89a"):
                return struct.unpack("<HH", head[6:10])
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
    """1.0 is square. Lower is more elongated."""
    if not w or not h:
        return 0.0
    return min(w, h) / max(w, h)


def target_size(w, h, max_edge=MAX_EDGE):
    """Downscale so the long edge fits. Never upscale."""
    if not w or not h:
        return (None, None)
    if max(w, h) <= max_edge:
        return (w, h)
    f = max_edge / max(w, h)
    nw, nh = round(w * f), round(h * f)
    nw -= nw % 2
    nh -= nh % 2
    return (nw, nh)


def score(path):
    """Rank an image as a cover candidate. Higher is better."""
    dim = dimensions(path)
    if not dim:
        return (0.0, 0)
    w, h = dim
    sq = squareness(w, h)
    name = Path(path).name.lower()

    bonus = 0.0
    for i, hint in enumerate(COVER_HINTS):
        if hint in name:
            bonus = 0.30 - (i * 0.04)
            break
    for hint in NEVER:
        if hint in name:
            bonus = -0.50
            break
    # numbered booklet pages 02-03.jpg are spreads, not covers
    if any(c.isdigit() for c in Path(path).stem) and "-" in Path(path).stem:
        bonus -= 0.20

    return (sq + bonus, max(w, h))


def candidates(folder):
    """All plausible cover images in a folder, best first."""
    folder = Path(folder)
    found = []
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXT:
            continue
        if p.name.startswith("._"):
            continue
        dim = dimensions(p)
        if not dim:
            continue
        found.append({
            "path": p,
            "width": dim[0],
            "height": dim[1],
            "squareness": round(squareness(*dim), 2),
            "score": score(p),
        })
    found.sort(key=lambda a: a["score"], reverse=True)
    return found


def pick(folder):
    """The best cover, or None. Flags anything below the acceptance floor."""
    for cand in candidates(folder):
        if min(cand["width"], cand["height"]) >= MIN_ACCEPTABLE:
            return cand
    return None


def prepare(src, dst, max_edge=MAX_EDGE):
    """Downscale to the target into dst. Returns (path, note)."""
    dim = dimensions(src)
    if not dim:
        return (None, "unreadable dimensions")
    w, h = dim
    tw, th = target_size(w, h, max_edge)
    if (tw, th) == (w, h):
        note = f"{w}x{h} kept as-is"
        vf = "null"
    else:
        note = f"{w}x{h} downscaled to {tw}x{th}"
        vf = f"scale={tw}:{th}:flags=lanczos"

    res = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(src), "-vf", vf, "-q:v", "3", str(dst)],
        capture_output=True, text=True, timeout=300)
    if res.returncode != 0 or not Path(dst).exists():
        return (None, f"conversion failed: {res.stderr[:200]}")
    return (Path(dst), note)
