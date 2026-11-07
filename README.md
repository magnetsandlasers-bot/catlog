# catlog

Classical music ingestion. Point it at a folder of ripped or downloaded
music, approve the tags it proposes, get MP3 320 out in this library's
format.

Named for the catalogue and the log.

## What it is for

Ripping a CD is easy. Ripping it *correctly* is not, because almost none of
the metadata you need is in the files:

- A CUE sheet gives track boundaries and little else. Its performer strings
  are routinely wrong or incomplete.
- `REM DATE` is the release year, so the recording year is missing entirely.
- Artwork arrives in scattered sizes, and the biggest image is usually a
  booklet spread rather than the cover.
- Classical releases put several works on one disc, so "one album, one work"
  falls apart immediately.

Every one of those is a judgement call. catlog does the mechanical work —
splitting, transcoding, resizing, tagging — and stops at a manifest for a
human to approve. Nothing is encoded until then.

## Using it

    python3 catlog.py                    what is in intake and what needs deciding
    python3 catlog.py inspect ITEM       everything about one album
    python3 catlog.py plan SLUG          write a manifest
    python3 catlog.py approve SLUG       open the gate
    python3 catlog.py render SLUG        split, encode, tag
    python3 catlog.py verify SLUG        check every track
    python3 catlog.py census PATH        genre vocabulary in a library

`SLUG` may also be `all`, which acts on every album with a metadata file.

A batch is usually: look at intake, write a metadata file per album, `plan
all`, read the summaries, `approve all`, `render all`, `verify all`.

Nothing renders until a manifest says `"approved": true`. That flag is the
only gate, and it is deliberate.

## Layout

    ~/catlog                this repo
    ~/catlog-data           data, kept out of the repo on purpose
      intake/               drop zone       \\recorder\catlog-intake
      out/                  finished albums \\recorder\catlog-out
      manifests/  meta/  reports/  work/  logs/  quarantine/

Code and data are separate so that a stray `git clean -xdf` cannot touch the
intake or the delivered albums. Run the tools from the repo in place; there
is no deploy step and no second copy of the scripts.

## Documentation

- `docs/TAGGING.md` — **the contract.** Every rule about how this library
  tags classical music, including the ones that are only there because a
  mistake got corrected. Read this before changing anything.
- `docs/OPERATING.md` — dependencies, the container invocation, measured
  timings, and the traps worth knowing before they cost an afternoon.
- `examples/` — real metadata files covering every source shape.

## Scope

Classical only. The Pazz & Jop library is tagged differently and deliberately
stays out of this.

Output is always MP3 320 CBR. Lossless sources are decoded and encoded once;
sources already at 320 are re-tagged without re-encoding. Nothing is ever
upscaled, in audio or in artwork.

## Status

Seven albums through it: a three-disc opera, a single disc holding two string
quartets, a 44-track opera shipped as pre-split FLACs, and four discs with no
CUE at all. That covers the common container shapes. SACD ISO is not
supported — see `docs/OPERATING.md`.

## Licence

Private. Not published for reuse.
