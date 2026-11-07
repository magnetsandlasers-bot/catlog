"""CUE sheets, folder enumerations, and text encodings.

CUE parsing was previously duplicated in two scripts with subtly different
behaviour. This is the one copy.
"""

import re
from pathlib import Path

AUDIO_EXT = {
    ".mp3", ".flac", ".m4a", ".aac", ".wav", ".aiff", ".aif",
    ".ogg", ".opus", ".ape", ".wv", ".wma", ".dsf", ".dff", ".mka",
}

IGNORE_NAMES = {".DS_Store", "Thumbs.db"}
IGNORE_PREFIX = "._"


def ignored(name):
    """AppleDouble and OS metadata files that must never be treated as music."""
    return name in IGNORE_NAMES or name.startswith(IGNORE_PREFIX)


def sniff_text_encoding(path, limit=8192):
    """Best guess at a text file's encoding.

    Russian and Japanese rips are frequently CP1251 or Shift-JIS with no
    declaration. ASCII and UTF-8 are unambiguous; legacy single-byte and
    double-byte encodings are not, so the answer carries a confidence flag.
    """
    raw = Path(path).read_bytes()[:limit]
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return ("utf-16", True)
    if raw.startswith(b"\xef\xbb\xbf"):
        return ("utf-8-sig", True)
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

    # Ambiguous. Prefer CP1251 when the result looks like Cyrillic, which is
    # the common case for this library's Russian-sourced rips.
    for enc in ("cp1251", "koi8_r", "shift_jis", "cp1252"):
        try:
            dec = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        cyr = sum(1 for ch in dec if "\u0400" <= ch <= "\u04ff")
        if cyr > len(dec) * 0.05:
            return (enc, True)
        return (enc, False)
    return ("unknown", False)


def msf_to_seconds(msf):
    """CUE minutes:seconds:frames (75 fps) to float seconds."""
    m = re.match(r"(\d+):(\d+):(\d+)", msf.strip())
    if not m:
        return None
    mm, ss, ff = (int(x) for x in m.groups())
    return (mm * 60 + ss) + ff / 75.0


def read_cue(path):
    """Parse a CUE sheet into files, tracks, and album-level metadata.

    Each track records which FILE it belongs to, so a cue with one FILE and a
    cue with one FILE per track are both handled from the same parse.
    """
    path = Path(path)
    enc, confident = sniff_text_encoding(path)
    if enc in ("ascii", "utf-8-sig"):
        enc = "utf-8"
    try:
        text = path.read_text(encoding=enc, errors="replace")
    except Exception:
        text = path.read_text(errors="replace")

    out = {"path": str(path), "encoding": enc, "encoding_confident": confident,
           "files": [], "tracks": [], "title": None, "performer": None,
           "rem": []}
    cur = None
    cur_file = None

    for line in text.splitlines():
        s = line.strip()
        up = s.upper()
        if up.startswith("FILE "):
            q = s.split('"')
            name = q[1] if len(q) > 1 else s[5:].strip()
            out["files"].append(name)
            cur_file = name
        elif up.startswith("TRACK "):
            parts = s.split()
            cur = {"number": int(parts[1]), "title": None,
                   "index01": None, "index00": None, "file": cur_file}
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
        elif up.startswith("INDEX 00 ") and cur is not None:
            cur["index00"] = msf_to_seconds(s[9:])
        elif up.startswith("INDEX 01 ") and cur is not None:
            cur["index01"] = msf_to_seconds(s[9:])

    for i, t in enumerate(out["tracks"]):
        nxt = None
        for later in out["tracks"][i + 1:]:
            if later["index01"] is not None:
                nxt = later["index01"]
                break
        if t["index01"] is not None and nxt is not None:
            t["duration"] = nxt - t["index01"]
        else:
            t["duration"] = None
        if t["index00"] is not None and t["index01"] is not None:
            t["pregap"] = t["index01"] - t["index00"]
        else:
            t["pregap"] = None

    return out


def scan_folder_tracks(folder):
    """Enumerate audio files in a folder as a synthetic cue-less track list.

    Used when a release ships loose tracks with no CUE. Files are sorted by
    name, so the naming must sort into playing order.
    """
    folder = Path(folder)
    names = sorted(
        p.name for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_EXT and not ignored(p.name)
    )
    tracks = [{"number": i, "title": None, "file": name, "index01": None,
               "index00": None, "duration": None, "pregap": None}
              for i, name in enumerate(names, start=1)]
    return {"path": str(folder), "encoding": "n/a", "encoding_confident": True,
            "files": names, "tracks": tracks, "title": None,
            "performer": None, "rem": []}
