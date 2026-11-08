"""Audio probing and embedded tag inspection."""

import subprocess
from pathlib import Path


def duration(path):
    """Duration in seconds via ffprobe, or None."""
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=120)
        return float(res.stdout.strip())
    except Exception:
        return None


def sniff(path):
    """Format, bitrate, duration, sample rate and channel count via mutagen."""
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
            for k in list(tags.keys()):
                ku = str(k).upper()
                if ku.startswith("CUESHEET"):
                    out["embedded_cuesheet"] = True
                if ku in ("TITLE", "ARTIST", "ALBUM", "DATE", "GENRE",
                          "TIT2", "TPE1", "TALB", "TDRC", "TCON", "TIT1"):
                    try:
                        out["tags"][k] = str(tags[k])[:160]
                    except Exception:
                        pass
    except Exception as exc:
        out["error"] = str(exc)[:150]
    return out


def probe_stream(path):
    """Codec, bitrate, sample rate, channels and duration, for verification."""
    import json
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
            "channels": st.get("channels"),
            "duration": float((d.get("format") or {}).get("duration") or 0),
        }
    except Exception:
        return {}


def encode(src, dst, start=0.0, length=None, bitrate="320k"):
    """Encode one range to MP3 CBR.

    -map_metadata -1 discards everything the source carried, so no stale tags
    survive into the output. ID3v2.4, and no ID3v1 block.
    """
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-ss", f"{start:.3f}", "-i", str(src)]
    if length is not None:
        cmd += ["-t", f"{length:.3f}"]
    cmd += ["-map_metadata", "-1", "-vn",
            "-c:a", "libmp3lame", "-b:a", bitrate, "-ar", "44100",
            "-compression_level", "0",
            "-id3v2_version", "4", "-write_id3v1", "0",
            str(dst)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if res.returncode != 0 or not Path(dst).exists():
        return (False, (res.stderr or "").strip()[:300])
    return (True, "")
