"""Writing and reading the ID3 frames this library uses.

Frame names are the raw ID3 names because that is what the code reads and
writes. Note that TIT1 and GRP1 both render as "Grouping" in exiftool: TIT1 is
the work, GRP1 is the literal string Classical.
"""

from pathlib import Path

REQUIRED = ["TIT1", "TIT2", "TPE1", "TPE2", "TALB", "TCOM",
            "TCON", "TDRC", "TRCK", "GRP1"]

# ffmpeg and various rippers leave noise in these.
CLEAR = ("COMM", "TSSE", "TENC")


def write(path, album, track, cover=None):
    """Write the frames for one track. Returns (ok, error)."""
    from mutagen.id3 import (ID3, TIT1, TIT2, TPE1, TPE2, TALB, TCOM,
                             TCON, TDRC, TRCK, TPOS, GRP1, MVNM, MVIN, APIC)
    try:
        try:
            tags = ID3(str(path))
        except Exception:
            tags = ID3()

        for frame in CLEAR:
            tags.delall(frame)

        tags.add(TIT1(encoding=3, text=track["tit1"]))
        tags.add(TIT2(encoding=3, text=track["tit2"]))
        tags.add(TPE1(encoding=3, text=track.get("tpe1") or album["tpe1"]))
        tags.add(TPE2(encoding=3, text=album["tpe2"]))
        tags.add(TALB(encoding=3, text=album["talb"]))
        tags.add(TCOM(encoding=3, text=track.get("tcom") or album["tcom"]))
        tags.add(TCON(encoding=3, text=album["tcon"]))
        tags.add(TDRC(encoding=3, text=album["tdrc"]))
        tags.add(TRCK(encoding=3, text=str(track["number"])))
        if track.get("tpos"):
            tags.add(TPOS(encoding=3, text=track["tpos"]))
        tags.add(GRP1(encoding=3, text=album.get("grp1", "Classical")))
        if track.get("mvnm"):
            tags.add(MVNM(encoding=3, text=track["mvnm"]))
        if track.get("mvin"):
            tags.add(MVIN(encoding=3, text=track["mvin"]))
        if cover and Path(cover).exists():
            tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover",
                          data=Path(cover).read_bytes()))

        tags.save(str(path), v2_version=4)
        return (True, "")
    except Exception as exc:
        return (False, str(exc)[:200])


def read(path):
    """Read back the frames, plus cover size and ID3 version."""
    from mutagen.id3 import ID3
    out = {}
    try:
        t = ID3(str(path))
        for k in REQUIRED + ["MVNM", "MVIN", "TPOS"]:
            f = t.get(k)
            if f is not None:
                try:
                    out[k] = str(f.text[0])
                except Exception:
                    out[k] = str(f)
        apic = t.getall("APIC")
        out["_pictures"] = len(apic)
        out["_picture_kb"] = len(apic[0].data) // 1024 if apic else 0
        out["_version"] = ".".join(str(x) for x in t.version)
    except Exception as exc:
        out["_error"] = str(exc)[:200]
    return out


def tidy(path):
    """Strip encoder noise from an already-tagged file. Returns frames removed."""
    from mutagen.id3 import ID3
    try:
        t = ID3(str(path))
    except Exception:
        return []
    removed = []
    for frame in CLEAR:
        if t.getall(frame):
            t.delall(frame)
            removed.append(frame)
    if removed:
        t.save(str(path), v2_version=4)
    return removed
