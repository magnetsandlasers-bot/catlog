# catlog

A classical music ingestion pipeline. Drop a folder, an archive, or a disc
image onto the recorder box, approve the proposed tags, get MP3 320 out with
the tagging conventions this library actually uses.

Named for the catalogue and the log. The pun is deliberate.

## Why it exists

Ripping a CD is easy. Ripping a CD *correctly* is not. A CUE sheet gives you
track boundaries and nothing else. Its performer strings are frequently wrong,
incomplete, or scrambled. `REM DATE` is the release year, not the recording
year, so `recording year` is almost never in the files at all. Artwork comes in
scattered at unpredictable sizes, and the biggest image is a booklet spread
rather than the cover. Classical releases put several works on one disc, so
"one album, one work" falls apart on the first chamber disc.

Every one of those is a decision that needs a human, so catlog splits the job.
It does the mechanical work -- splitting, transcoding, resizing, writing tags --
and stops dead at a manifest for you to check. Nothing is encoded until you say
so.

## The shape of it

    intake/     drop files here       (smb: \\recorder\catlog-intake)
    work/       scratch, safe to delete
    manifests/  the proposals, one per album
    out/        finished albums       (smb: \\recorder\catlog-out)
    reports/    scan and render logs
    quarantine/ anything that needs a decision

Two stages matter:

1. `plan.py` reads a metadata file and the CUE sheets and writes a manifest.
   Every output track, every start time, every tag, the artwork, the warnings.
   It writes nothing else.
2. `render.py` refuses to run unless the manifest says `"approved": true`.
   Then it splits, encodes, tags and embeds.

Between those two is where you work. Edit the manifest, re-plan, approve, render.

## Quick start

    # what is in intake?
    python3 ~/catlog/scan.py

    # everything about one album, in detail
    python3 ~/catlog/inspect.py "Some Album Folder"

    # write a metadata file for it under meta/, then
    python3 ~/catlog/plan.py --meta ~/catlog-data/meta/some-album.json

    # read the plan, then flip "approved": true in the manifest
    python3 ~/catlog/render.py --slug some-album

    # verify every track and copy to the out share
    python3 ~/catlog/deliver.py --slug some-album --copy

Not part of the album workflow, but useful when the vocabulary drifts:

    # what genre values is the library actually using?
    python3 ~/catlog/census.py /mnt/woke_classical

Long renders outlive an ssh session. Run them detached and poll:

    nohup python3 ~/catlog/render.py --slug some-album > /tmp/render.log 2>&1 &

## Documentation

- `docs/TAGGING.md` -- the tag format. Composer, work, movement, performers,
  the recording-year rule, opera, multi-work discs. This is the part that
  matters and the part that took the longest to pin down.
- `docs/USER-GUIDE.md` -- the day to day. Deciding what an album is, choosing
  artwork, approving, importing.
- `docs/ADMIN-GUIDE.md` -- dependencies, environment variables, how each stage
  works internally, and the failure modes worth knowing in advance.
- `census.py` -- counts the `TCON` values in a finished library, so the genre
  vocabulary can be seen rather than assumed.

## Scope

Classical only. The Pazz & Jop library is tagged differently and deliberately
stays out of this.

Output is always MP3 320 CBR. Lossless sources are decoded and encoded once.
Sources that are already MP3 320 are re-tagged without re-encoding. Nothing is
ever upscaled, in audio or in artwork.

## Status

Working, with three albums through it: a three-disc opera, a single disc
holding two string quartets, and one released as 44 pre-split FLACs. That
covers the common container shapes. SACD ISO extraction is not implemented.

## Licence

Private. Not published for reuse.
