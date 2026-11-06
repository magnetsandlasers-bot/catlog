# User guide

The day to day. What to do with a new pile of files.

## 1. Drop the files in

    ~/catlog-data/intake/

or over SMB, which is easier:

    \\recorder\catlog-intake

A folder per album. An archive is fine. A disc image is fine. Multi-disc sets
go in as one folder, not one per disc.

## 2. See what arrived

    python3 ~/catlog/scan.py

Reads everything, changes nothing. Tells you the shape of each item, the
formats and bitrates, artwork sizes, CUE encodings, and flags anything that
will need a decision. The report lands in `reports/scan-<timestamp>/`.

Look at the flags. Anything that says `NO ARTWORK`, `cannot split`, `MP3 below
320` or `encoding ambiguous` is going to need you.

## 3. Look closer at the one you are doing

    python3 ~/catlog/inspect.py "Album Folder Name"

Every track from the CUE with computed durations, every image with its
dimensions and a squareness score and a guess at what it is, the text encoding
of the CUE and any EAC logs, and whether the audio carries an embedded
cuesheet. This is where you work out what the album *is*.

Useful checks:

- Do the track durations add up to the source duration? If not, audio is being
  dropped somewhere.
- Which image is the cover? The squarest one, not the biggest.
- Is the CUE in CP1251 or Shift-JIS? If it says `ambiguous`, verify the titles.

## 4. Work out what the album is

This is the only part catlog cannot do for you. Four things:

**The works.** How many, in what order, and where do they change? A disc with
two quartets has TIT1 changing partway through. Note the track number where it
changes.

**The recording year.** Not in the files. `REM DATE` is the release year.
Research it. Discogs often states the exact session dates; MusicBrainz release
pages do too and give per-track recording dates, which is how you catch a disc
assembled from two different sessions. National library catalogues are
surprisingly reliable. A reissue's year is not the recording year.

**The performers.** Orchestra first, then `cond.`, then conductor. Opera omits
soloists entirely. Most CUE performer strings are wrong or incomplete -- build
from a real source.

**The genre.** Prefer an existing value. See `TAGGING.md`.

## 5. Write the metadata file

Under `~/catlog-data/meta/`, one JSON file per album. It is the input to planning;
the manifest is the output.

    {
      "slug": "schubert-abq-tod-rosamunde",
      "album": {
        "talb": "Schubert: Der Tod und das Maedchen / Rosamunde",
        "tpe2": "Alban Berg Quartett",
        "tpe1": "Alban Berg Quartett",
        "tcom": "Franz Schubert (1797-1828)",
        "tcon": "Quartet, string",
        "tdrc": "1985",
        "grp1": "Classical",
        "work": "Der Tod und das Maedchen",
        "tit1": "String Quartet no.14 in D minor, D.810—(rec. 1984)",
        "artist_folder": "Alban Berg Quartett",
        "album_folder": "Schubert_ Der Tod und das Maedchen _ Rosamunde",
        "artwork": "Schubert - Alban Berg Quartett/03.jpg",
        "artwork_note": "03.jpg is the near-square booklet front"
      },
      "discs": [
        {
          "tpos": 1,
          "cue": "Schubert - Alban Berg Quartett/Album.cue",
          "tracks_override": {
            "1": {"mvnm": "Allegro", "roman": "I", "mvin": "1/4"},
            "5": {"mvnm": "Allegro ma non troppo", "roman": "I", "mvin": "1/4",
                  "tit1": "String Quartet no.13 in A minor, D.804, op.29—(rec. 1984)"}
          }
        }
      ]
    }

Notes on the fields:

- `artwork` is a path relative to `intake/`.
- `tit1` at album level is the default for every track.
- `tracks_override` is keyed by track number as a string. Anything set there
  wins for that track. This is how the work changes mid-disc -- and note that
  you must set `tit1` on **every** track of the second work, not just the
  first, because the album-level value is the fallback.
- Omit `mvin` entirely for opera, and omit `roman` too.
- For a disc released as pre-split files rather than one image, the CUE has one
  `FILE` per track, and catlog handles that automatically.

## 6. Plan

    python3 ~/catlog/plan.py --meta ~/catlog-data/meta/some-album.json

Writes `manifests/<slug>/manifest.json` and prints a readable summary: every
track with its start and duration, its TIT2, the artwork resize, and any
warnings or errors. Nothing is encoded.

Read it properly. The things to look at:

- Track count and total duration against the source.
- TIT2 values, especially where the work changes.
- `WARNINGS` -- a duration mismatch means audio is being dropped; a missing
  artwork means nothing will be embedded.
- `ERRORS` means it cannot render at all.

If something is wrong, fix the metadata file and re-plan. Planning is free.

## 7. Approve

In the manifest:

    "approved": false   ->   "approved": true

That single flag is the gate. Rendering refuses without it. If a directory is
already approved, re-planning will not silently overwrite it -- it stops and
asks.

## 8. Render

    nohup python3 ~/catlog/render.py --slug some-album > /tmp/render.log 2>&1 &

Run it detached. A disc takes roughly 15 to 20 minutes, an opera three discs
about 15, forty-four shorter tracks about 8. Total elapsed is dominated by
decoding, so it scales with audio duration, not track count.

Watch progress:

    tail -f /tmp/render.log
    ls ~/catlog-data/out/<Artist>/<Album>/ | wc -l

## 9. Verify and deliver

    python3 ~/catlog/deliver.py --slug some-album

Checks every track: it exists, it is really MP3, it is really near 320k, the
sample rate is right, the duration matches the plan to within 1.5s, every
required tag is present, TIT1 and TIT2 match what was planned, there is
exactly one embedded image, and the cover is within 1280. Prints the album
tags and the total size.

Then:

    python3 ~/catlog/deliver.py --slug some-album --copy

Repeats all of that and, only if everything passed, copies to
`~/catlog-data/out/<Artist>/<Album>/`. It will not copy while problems remain.

## 10. Import

`out/` is already shaped like the library. Drag the album folder into the
classical library over SMB, or rsync it. Then let Navidrome rescan.

The finished folder contains the MP3s and a `cover.jpg`.

## Housekeeping

Once an album is imported and you are happy, delete the source from `intake/`.
catlog never deletes intake automatically -- that is on purpose, because
re-deriving a render from a deleted source means re-ripping.

`work/` is scratch and can be emptied at any time. `reports/` and
`manifests/` are the audit trail; the manifests for delivered albums are the
record of what was actually written.

## When it goes wrong

**Encode failed, `No such file or directory`.** A path in the plan does not
resolve. Usually a per-track `source` missing its directory. Re-plan and check
that the source paths in the manifest are relative to `intake/` and exist.

**Durations do not add up.** The CUE's last track has no following index, so
its duration comes from the source file length minus its start. If the source
is truncated or the CUE is for a different edition, the tail is wrong.
`inspect.py` shows both numbers.

**Cover looks wrong.** It picked something from a booklet. Set `artwork`
explicitly in the metadata to a specific file.

**Titles come out double-numbered.** The source already carried a numeral in
MVNM. Do not set `roman` for those tracks.

**Re-planning refuses.** The manifest is approved. Move it aside or set
`approved` back to false first.
