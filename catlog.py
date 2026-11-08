"""catlog -- classical music ingestion.

    python3 catlog.py                  what is in intake, and what needs a decision
    python3 catlog.py inspect ITEM     everything about one intake item
    python3 catlog.py plan SLUG        write a manifest for approval
    python3 catlog.py approve SLUG     open the gate
    python3 catlog.py render SLUG      split, encode, tag, into out/
    python3 catlog.py verify SLUG      check every track
    python3 catlog.py tidy SLUG        strip encoder noise from finished files
    python3 catlog.py census PATH      genre vocabulary in a finished library

SLUG may be a slug, or "all" to act on every album with a metadata file.

Paths default under ~/catlog-data and can be overridden with CATLOG_INTAKE,
CATLOG_OUT, CATLOG_MANIFESTS, CATLOG_REPORTS, CATLOG_WORK, CATLOG_META.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import artwork, audio, cues, manifest as mf, naming, tagging

DATA = Path(os.environ.get("CATLOG_DATA", Path.home() / "catlog-data"))
INTAKE = Path(os.environ.get("CATLOG_INTAKE", DATA / "intake"))
MANIFESTS = Path(os.environ.get("CATLOG_MANIFESTS", DATA / "manifests"))
OUT = Path(os.environ.get("CATLOG_OUT", DATA / "out"))
REPORTS = Path(os.environ.get("CATLOG_REPORTS", DATA / "reports"))
WORK = Path(os.environ.get("CATLOG_WORK", DATA / "work"))
META = Path(os.environ.get("CATLOG_META", DATA / "meta"))

BITRATE_MIN = 300000
BITRATE_MAX = 340000
DURATION_TOLERANCE = 1.5


# ---------------------------------------------------------------- helpers

def need_mutagen():
    try:
        import mutagen  # noqa: F401
        return True
    except ImportError:
        print("ERROR: mutagen is not installed.")
        print("  sudo apt install python3-mutagen")
        return False


def slugs(requested):
    """Resolve a slug argument to a list.

    'all' means every album with a metadata file. The slug is read from inside
    the JSON, because the filename and the slug are not always the same.
    """
    if requested != "all":
        return [requested]
    found = []
    for p in sorted(META.glob("*.json")):
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        found.append(meta.get("slug", p.stem))
    return found


def human(n):
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}T"


def intake_items():
    if not INTAKE.is_dir():
        return []
    return sorted(p for p in INTAKE.iterdir() if not cues.ignored(p.name))


# ---------------------------------------------------------------- status

def cmd_status(args):
    """The default action: what came in, and what needs deciding."""
    items = intake_items()
    print(f"INTAKE  {INTAKE}")
    if not items:
        print("  empty")
    else:
        print(f"  {len(items)} item(s)")
        for p in items:
            if p.is_dir():
                n = sum(1 for f in p.rglob("*")
                        if f.is_file() and f.suffix.lower() in cues.AUDIO_EXT
                        and not cues.ignored(f.name))
                print(f"    {p.name}  ({n} audio files)")
            else:
                print(f"    {p.name}  ({human(p.stat().st_size)})")
    print()

    metas = sorted(META.glob("*.json")) if META.is_dir() else []
    approved = []
    unapproved = []
    for mp in metas:
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        slug = meta.get("slug", mp.stem)
        existing = mf.load(MANIFESTS, slug)
        if existing and existing.get("approved"):
            approved.append((slug, existing))
        else:
            unapproved.append((slug, mp))

    if unapproved:
        print("PLANNED, NOT APPROVED")
        for slug, _ in unapproved:
            print(f"  {slug}")
        print("  -> python3 catlog.py plan SLUG   then read and approve")
        print()

    if approved:
        waiting = []
        rendered = []
        imported = []
        for slug, m in approved:
            dest = OUT / m["artist_folder"] / m["album_folder"]
            want = sum(d["track_count"] for d in m["discs"])
            if not dest.is_dir():
                waiting.append((slug, want))
                continue
            done = len(list(dest.glob("*.mp3")))
            if done >= want:
                rendered.append((slug, want))
            elif done == 0:
                imported.append((slug, want))
            else:
                waiting.append((slug, want, done))

        if waiting:
            print("APPROVED, NOT RENDERED")
            for row in waiting:
                if len(row) == 2:
                    print(f"  {row[0]}  (0/{row[1]} tracks)")
                else:
                    print(f"  {row[0]}  ({row[2]}/{row[1]} tracks - partial)")
            print("  -> python3 catlog.py render SLUG")
            print()

        if rendered:
            print("RENDERED, READY TO IMPORT")
            for slug, n in rendered:
                m = dict(approved)[slug]
                d = OUT / m["artist_folder"] / m["album_folder"]
                size = sum(f.stat().st_size for f in d.glob("*.mp3"))
                print(f"  {slug}  ({n} tracks, {human(size)})")
            print()

        if imported:
            print("IMPORTED (album folder is empty - the MP3s were moved out)")
            for slug, n in imported:
                print(f"  {slug}  ({n} tracks)")
            print()

    outdirs = sorted(p for p in OUT.iterdir() if p.is_dir()) if OUT.is_dir() else []
    if outdirs:
        print("OUTPUT TREE")
        for p in outdirs:
            for a in sorted(x for x in p.iterdir() if x.is_dir()):
                n = len(list(a.glob("*.mp3")))
                size = sum(f.stat().st_size for f in a.glob("*.mp3"))
                if n:
                    print(f"  {p.name}/{a.name}  ({n} tracks, {human(size)})")
    return 0


# ---------------------------------------------------------------- plan

def cmd_plan(args):
    todo = slugs(args.slug)
    if not todo:
        print("nothing to plan; no metadata files in", META)
        return 1
    rc = 0
    for slug in todo:
        mp = META / f"{slug}.json"
        if not mp.is_file():
            print(f"ERROR: no metadata at {mp}")
            rc = 1
            continue
        meta = json.loads(mp.read_text(encoding="utf-8"))
        meta.setdefault("slug", slug)
        m = mf.build(meta, INTAKE)
        path, err = mf.write(m, MANIFESTS)
        if err:
            print(f"REFUSING {slug}: {err}")
            rc = 1
            continue
        print(mf.summary(m))
        print(f"manifest: {path}")
        print()
        if m["errors"]:
            rc = 1
    return rc


def cmd_approve(args):
    for slug in slugs(args.slug):
        try:
            p = mf.approve(MANIFESTS, slug)
            print(f"approved: {p}")
        except Exception as exc:
            print(f"ERROR {slug}: {exc}")
            return 1
    return 0


# ---------------------------------------------------------------- render

def cmd_render(args):
    rc = 0
    for slug in slugs(args.slug):
        m = mf.load(MANIFESTS, slug)
        if not m:
            print(f"ERROR: no manifest for {slug}; run plan first")
            rc = 1
            continue
        if m["errors"]:
            print(f"REFUSING {slug}: manifest has errors")
            for e in m["errors"]:
                print(f"  x {e}")
            rc = 1
            continue
        if not m.get("approved"):
            print(f"REFUSING {slug}: not approved")
            rc = 1
            continue
        if render_one(m, slug) != 0:
            rc = 1
    return rc


def render_one(m, slug):
    a = m["album"]
    dest = OUT / a["artist_folder"] / a["album_folder"]
    dest.mkdir(parents=True, exist_ok=True)
    workdir = WORK / slug
    workdir.mkdir(parents=True, exist_ok=True)

    log = [f"ALBUM: {a['talb']}", f"DEST:  {dest}", ""]

    cover = None
    art = m["artwork"]
    if art.get("source"):
        src = INTAKE / art["source"]
        if src.is_file():
            cover, note = artwork.prepare(src, workdir / "cover.jpg")
            log.append(f"ARTWORK: {src.name} {note}")
        else:
            log.append(f"ARTWORK: missing {art['source']}")
    if not cover:
        log.append("ARTWORK: none")

    ok = fail = 0
    for d in m["discs"]:
        log.append(f"--- disc {d['tpos']}/{d['tpos_total']}")
        for t in d["tracks"]:
            src = INTAKE / t["source"]
            dst = dest / t["filename"]
            if not src.is_file():
                log.append(f"  MISSING {t['source']}")
                fail += 1
                continue
            good, err = audio.encode(src, dst, t["start_s"], t["duration_s"])
            if not good:
                log.append(f"  ENCODE FAILED {t['filename']}: {err}")
                fail += 1
                continue
            track = dict(t)
            track.setdefault("tpos", f"{d['tpos']}/{d['tpos_total']}")
            good, err = tagging.write(dst, a, track, cover)
            if not good:
                log.append(f"  TAG FAILED {t['filename']}: {err}")
                fail += 1
                continue
            ok += 1
            log.append(f"  ok  {t['filename']}")

    if cover and Path(cover).exists():
        shutil.copy2(cover, dest / "cover.jpg")
        log.append("")
        log.append("cover.jpg copied")

    total = sum(p.stat().st_size for p in dest.glob("*.mp3"))
    log.append("")
    log.append(f"files written: {ok}, failures: {fail}, {human(total)}")

    text = "\n".join(log)
    print(text)
    rd = REPORTS / f"render-{slug}"
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "render.txt").write_text(text, encoding="utf-8")
    return 0 if fail == 0 else 1


# ---------------------------------------------------------------- verify

def cmd_verify(args):
    rc = 0
    for slug in slugs(args.slug):
        m = mf.load(MANIFESTS, slug)
        if not m:
            print(f"ERROR: no manifest for {slug}")
            rc = 1
            continue
        a = m["album"]
        d = OUT / a["artist_folder"] / a["album_folder"]
        if not d.is_dir():
            print(f"{slug}: not rendered")
            rc = 1
            continue
        present = len(list(d.glob("*.mp3")))
        if present == 0:
            # Delivered, then moved into the library. Not a failure.
            print(f"{slug}: empty - already imported?")
            continue
        problems = verify_album(m, d)
        expected = sum(x["track_count"] for x in m["discs"])
        print(f"{slug}: {expected - len(problems)}/{expected} tracks ok")
        for p in problems[:40]:
            print(f"  x {p}")
        if len(problems) > 40:
            print(f"  ... {len(problems) - 40} more")
        if problems:
            rc = 1
    return rc


def verify_album(m, folder):
    """Every check that catches a wrong or half-finished render."""
    problems = []
    for d in m["discs"]:
        for t in d["tracks"]:
            p = folder / t["filename"]
            if not p.is_file():
                problems.append(f"MISSING {t['filename']}")
                continue
            info = audio.probe_stream(p)
            if info.get("codec") != "mp3":
                problems.append(f"{t['filename']}: codec {info.get('codec')}")
            br = info.get("bitrate", 0)
            if not (BITRATE_MIN <= br <= BITRATE_MAX):
                problems.append(f"{t['filename']}: bitrate {br}")
            if info.get("rate") != "44100":
                problems.append(f"{t['filename']}: {info.get('rate')} Hz")
            if abs(info.get("duration", 0) - t["duration_s"]) > DURATION_TOLERANCE:
                problems.append(f"{t['filename']}: duration off")
            tags = tagging.read(p)
            for k in tagging.REQUIRED:
                if k not in tags:
                    problems.append(f"{t['filename']}: missing {k}")
            if tags.get("TIT1") != t["tit1"]:
                problems.append(f"{t['filename']}: TIT1 differs from plan")
            if tags.get("TIT2") != t["tit2"]:
                problems.append(f"{t['filename']}: TIT2 differs from plan")
            if t.get("tpos") and tags.get("TPOS") != t["tpos"]:
                problems.append(t["filename"] + ": TPOS differs from plan")
            if tags.get("_pictures") != 1:
                problems.append(
                    f"{t['filename']}: {tags.get('_pictures', 0)} pictures")
    cover = folder / "cover.jpg"
    if not cover.is_file():
        problems.append("cover.jpg missing")
    else:
        dim = artwork.dimensions(cover)
        if dim and max(dim) > artwork.MAX_EDGE:
            problems.append(f"cover {dim[0]}x{dim[1]} exceeds {artwork.MAX_EDGE}")
    return problems


# ---------------------------------------------------------------- deliver

def cmd_deliver(args):
    """Verify in place. Everything is already written into the output tree."""
    return cmd_verify(args)


# ---------------------------------------------------------------- inspect

def cmd_inspect(args):
    target = INTAKE / args.item
    if not target.exists():
        print(f"ERROR: not in intake: {args.item}")
        return 1

    print(f"ITEM: {args.item}")
    if target.is_dir():
        found = artwork.candidates(target)
        audio_files = sorted(
            p for p in target.rglob("*")
            if p.is_file() and p.suffix.lower() in cues.AUDIO_EXT
            and not cues.ignored(p.name))
        print(f"audio: {len(audio_files)} file(s)")
        total = 0.0
        for f in audio_files:
            info = audio.sniff(f)
            dur = info["duration_s"] or 0
            total += dur
            print(f"  {f.name}")
            print(f"    {info['format']}  {dur:.0f}s  "
                  f"{info['sample_rate']}Hz  {info['bits'] or '?'}bit")
            for k, v in (info["tags"] or {}).items():
                print(f"      {k} = {v}")
        print(f"  total {total / 60:.1f} min")
        print()
        print(f"images: {len(found)}")
        for c in found:
            print(f"  {c['path'].name:32s} {c['width']}x{c['height']}  "
                  f"sq={c['squareness']}  score={c['score'][0]:.2f}")
        if found:
            print(f"  -> cover would be {found[0]['path'].name}")
        print()
        for c in sorted(target.rglob("*.cue")):
            info = cues.read_cue(c)
            flag = "" if info["encoding_confident"] else "  <- verify titles"
            print(f"CUE: {c.name}  {info['encoding']}{flag}")
            print(f"  files: {len(info['files'])}  tracks: {len(info['tracks'])}")
            print(f"  album title: {info['title']}")
            print(f"  performer:   {info['performer']}")
    else:
        info = audio.sniff(target)
        for k, v in info.items():
            if k != "tags":
                print(f"  {k}: {v}")
        for k, v in (info["tags"] or {}).items():
            print(f"  tag {k} = {v}")
    return 0


# ---------------------------------------------------------------- census

def cmd_census(args):
    from collections import Counter
    root = Path(args.path)
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}")
        return 1
    counts = Counter()
    none = 0
    seen = 0
    for p in sorted(root.rglob("*.mp3")):
        if cues.ignored(p.name):
            continue
        seen += 1
        tags = tagging.read(p)
        if "_error" in tags:
            continue
        g = tags.get("TCON")
        if g is None:
            none += 1
        else:
            counts[g] += 1
    print(f"scanned {seen} files")
    print(f"  no genre : {none}")
    print(f"  distinct : {len(counts)}")
    print()
    for g, n in counts.most_common():
        print(f"{n:7d}  {g}")
    return 0


# ---------------------------------------------------------------- tidy

def cmd_tidy(args):
    rc = 0
    for slug in slugs(args.slug):
        m = mf.load(MANIFESTS, slug)
        if not m:
            print(f"ERROR: no manifest for {slug}")
            rc = 1
            continue
        a = m["album"]
        d = OUT / a["artist_folder"] / a["album_folder"]
        changed = 0
        for p in sorted(d.glob("*.mp3")):
            if tagging.tidy(p):
                changed += 1
        print(f"{slug}: tidied {changed} file(s)")
    return rc


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="classical music ingestion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("status", help="what is in intake (default)")

    p = sub.add_parser("plan", help="write a manifest")
    p.add_argument("slug")

    p = sub.add_parser("approve", help="mark a manifest approved")
    p.add_argument("slug")

    p = sub.add_parser("render", help="split, encode, tag")
    p.add_argument("slug")

    p = sub.add_parser("verify", help="check every track")
    p.add_argument("slug")

    p = sub.add_parser("deliver", help="verify (output tree is the destination)")
    p.add_argument("slug")

    p = sub.add_parser("tidy", help="strip encoder noise")
    p.add_argument("slug")

    p = sub.add_parser("inspect", help="everything about one intake item")
    p.add_argument("item")

    p = sub.add_parser("census", help="genre vocabulary in a library")
    p.add_argument("path")

    args = ap.parse_args()

    handlers = {
        None: cmd_status,
        "status": cmd_status,
        "plan": cmd_plan,
        "approve": cmd_approve,
        "render": cmd_render,
        "verify": cmd_verify,
        "deliver": cmd_deliver,
        "tidy": cmd_tidy,
        "inspect": cmd_inspect,
        "census": cmd_census,
    }

    if args.cmd in ("plan", "render", "verify", "deliver", "tidy"):
        if not need_mutagen():
            return 1

    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
