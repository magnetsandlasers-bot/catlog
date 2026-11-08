"""Turning a metadata file plus source folders into an approval manifest.

The manifest is the contract between planning and rendering. Nothing is
encoded until a human has looked at one and set "approved": true.
"""

import json
from pathlib import Path

from . import artwork, audio, cues, naming


def _resolve_source(disc, intake):
    """Work out where a disc's audio lives: one image, many files, or a folder.

    Returns (cue_dict, base_dir, cue_path_or_None, error).
    """
    if disc.get("cue"):
        cue_path = intake / disc["cue"]
        if not cue_path.is_file():
            return (None, None, None, f"cue not found: {disc['cue']}")
        cue = cues.read_cue(cue_path)
        if not cue["files"]:
            return (None, None, None, f"cue has no FILE line: {disc['cue']}")
        return (cue, cue_path.parent, cue_path, None)

    if disc.get("folder"):
        src_dir = intake / disc["folder"]
        if not src_dir.is_dir():
            return (None, None, None, f"folder not found: {disc['folder']}")
        cue = cues.scan_folder_tracks(src_dir)
        if not cue["files"]:
            return (None, None, None, f"no audio files in {disc['folder']}")
        return (cue, src_dir, None, None)

    return (None, None, None,
            f"disc {disc.get('tpos')}: needs either 'cue' or 'folder'")


def _track_from_parts(album, disc, override, number, mvnm, tit1, roman, mvin,
                      start, length, source, disc_no, tpos_total):
    """Assemble one track record from already-resolved pieces."""
    mvnm = naming.normalize_act(mvnm or "")
    tit2 = naming.title_tag(tit1, mvnm, roman)
    stem = naming.filename_stem(mvnm, tit1)
    return {
        "number": number,
        "filename": naming.track_filename(disc_no, number, stem, tpos_total),
        "mvnm": mvnm,
        "mvin": mvin,
        "roman": roman,
        "tit1": tit1,
        "tit2": tit2,
        "tpe1": override.get("tpe1") or album["tpe1"],
        "tcom": override.get("tcom") or album["tcom"],
        "tpos": naming.tpos_tag(disc_no, tpos_total),
        "start_s": round(start, 3),
        "duration_s": round(length, 3),
        "source": source,
    }


def build(meta, intake):
    """Build a manifest dict from a metadata dict. Writes nothing."""
    album = dict(meta["album"])
    intake = Path(intake)
    errors = []
    warnings = []

    # ---- artwork
    art_src = None
    if album.get("artwork"):
        cand = intake / album["artwork"]
        if cand.is_file():
            art_src = cand
        else:
            errors.append(f"artwork not found: {album['artwork']}")
    if art_src is None and not album.get("artwork"):
        warnings.append("no artwork specified")

    art_dim = None
    if art_src:
        art_dim = artwork.dimensions(art_src)
        if art_dim:
            w, h = art_dim
            tw, th = artwork.target_size(w, h)
            album["artwork_resize"] = {"from": f"{w}x{h}", "to": f"{tw}x{th}"}
            if min(w, h) < artwork.MIN_ACCEPTABLE:
                warnings.append(
                    f"artwork {w}x{h} is below the {artwork.MIN_ACCEPTABLE}px floor")
        else:
            warnings.append("artwork dimensions unreadable")

    # ---- discs
    tpos_total = len(meta["discs"])
    discs = []
    for disc in meta["discs"]:
        disc_no = int(disc["tpos"])
        cue, base_dir, cue_path, err = _resolve_source(disc, intake)
        if err:
            errors.append(err)
            continue

        overrides = disc.get("tracks_override") or {}

        # Many FILE lines, or a folder: one file per track, no cutting.
        if len(cue["files"]) != 1:
            tracks = []
            total = 0.0
            for t in cue["tracks"]:
                name = t.get("file")
                if not name:
                    errors.append(f"disc {disc_no} track {t['number']}: no FILE")
                    continue
                src = base_dir / name
                if not src.is_file():
                    errors.append(f"disc {disc_no}: missing {name}")
                    continue
                length = audio.duration(src)
                if length is None:
                    errors.append(f"disc {disc_no}: cannot read {name}")
                    continue
                total += length

                ov = overrides.get(str(t["number"])) or {}
                tit1 = ov.get("tit1") or disc.get("tit1") or album["tit1"]
                tracks.append(_track_from_parts(
                    album, disc, ov, t["number"],
                    ov.get("mvnm", t.get("title")),
                    tit1, ov.get("roman") or "", ov.get("mvin") or "",
                    0.0, length, str(Path(base_dir.relative_to(intake)) / name),
                    disc_no, tpos_total))

            discs.append({
                "tpos": disc_no,
                "tpos_total": tpos_total,
                "cue": str(cue_path.relative_to(intake)) if cue_path else None,
                "folder": disc.get("folder"),
                "source": "(one file per track)",
                "source_duration_s": round(total, 3),
                "track_count": len(tracks),
                "tracks": tracks,
            })
            continue

        # One FILE: a disc image to be cut at the index points.
        src = base_dir / cue["files"][0]
        if not src.is_file():
            alts = [p for p in base_dir.iterdir()
                    if p.suffix.lower() in cues.AUDIO_EXT
                    and not cues.ignored(p.name)]
            if len(alts) == 1:
                warnings.append(
                    f"cue FILE '{cue['files'][0]}' not found, using {alts[0].name}")
                src = alts[0]
            else:
                errors.append(f"source audio not found for {disc['cue']}")
                continue

        total = audio.duration(src)
        if total is None:
            errors.append(f"could not read duration of {src.name}")
            continue

        tracks = []
        for i, t in enumerate(cue["tracks"]):
            start = t["index01"] if t["index01"] is not None else 0.0
            if t["index01"] is None:
                warnings.append(
                    f"disc {disc_no} track {t['number']}: no INDEX 01, using 0")
            nxt = None
            for later in cue["tracks"][i + 1:]:
                if later["index01"] is not None:
                    nxt = later["index01"]
                    break
            end = nxt if nxt is not None else total
            length = end - start
            if length <= 0:
                errors.append(
                    f"disc {disc_no} track {t['number']}: non-positive duration")
                continue

            ov = overrides.get(str(t["number"])) or {}
            tit1 = ov.get("tit1") or disc.get("tit1") or album["tit1"]
            tracks.append(_track_from_parts(
                album, disc, ov, t["number"],
                ov.get("mvnm", t.get("title")),
                tit1, ov.get("roman") or "", ov.get("mvin") or "",
                start, length, str(src.relative_to(intake)),
                disc_no, tpos_total))

        covered = sum(t["duration_s"] for t in tracks)
        if abs(covered - total) > 2.0:
            warnings.append(
                f"disc {disc_no}: tracks cover {covered:.1f}s of {total:.1f}s "
                f"({total - covered:+.1f}s unaccounted)")

        discs.append({
            "tpos": disc_no,
            "tpos_total": tpos_total,
            "cue": str(cue_path.relative_to(intake)) if cue_path else None,
            "source": str(src.relative_to(intake)),
            "source_duration_s": round(total, 3),
            "track_count": len(tracks),
            "tracks": tracks,
        })

    # ---- consistency checks on the tag rules
    for d in discs:
        for t in d["tracks"]:
            for field in ("tit1", "tit2"):
                if naming.has_upper_work_number(t[field]):
                    warnings.append(
                        f"{t['filename']}: {field} uses 'No.' - should be 'no.'")

    return {
        "generated": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "slug": meta["slug"],
        "album": album,
        "artist_folder": album["artist_folder"],
        "album_folder": album["album_folder"],
        "destination": str(Path(album["artist_folder"]) / album["album_folder"]),
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


def write(manifest, root):
    """Persist a manifest. Refuses to silently overwrite an approved one."""
    outdir = Path(root) / manifest["slug"]
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "manifest.json"

    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            old = {}
        if old.get("approved") and not manifest.get("approved"):
            return (None, "existing manifest is approved; move it aside first")
        manifest["approved"] = bool(old.get("approved")) and not manifest["errors"]

    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return (path, None)


def load(root, slug):
    path = Path(root) / slug / "manifest.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def approve(root, slug):
    """Flip the gate. Returns the path."""
    path = Path(root) / slug / "manifest.json"
    m = json.loads(path.read_text(encoding="utf-8"))
    m["approved"] = True
    path.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def summary(manifest):
    """Human-readable plan, for reading before approval."""
    L = []
    w = L.append
    a = manifest["album"]
    w(f"ALBUM   {a['talb']}")
    w(f"DEST    {manifest['destination']}")
    w("")
    for k in ("tpe2", "tpe1", "tcom", "tcon", "tdrc"):
        if a.get(k):
            w(f"  {k.upper():5s} {a[k]}")
    art = manifest["artwork"]
    if art.get("source"):
        rz = art.get("resize") or {}
        w(f"  ART   {art['source']}")
        if rz:
            w(f"        {rz.get('from')} -> {rz.get('to')}")
    else:
        w("  ART   none")
    w("")
    total = 0
    for d in manifest["discs"]:
        w(f"  disc {d['tpos']}/{d['tpos_total']}  "
          f"{d['track_count']} tracks  {d['source_duration_s'] / 60:.1f} min")
        for t in d["tracks"]:
            w(f"    {t['number']:2d}  {t['tit2']}")
            total += t["duration_s"]
        w("")
    w(f"  total {total / 60:.1f} min")
    if manifest["warnings"]:
        w("")
        w("  WARNINGS")
        for x in manifest["warnings"]:
            w(f"    ! {x}")
    if manifest["errors"]:
        w("")
        w("  ERRORS - cannot render")
        for x in manifest["errors"]:
            w(f"    x {x}")
    w("")
    w(f"  approved: {manifest['approved']}")
    return "\n".join(L)
