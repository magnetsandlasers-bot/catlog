# Administrator guide

Everything about running, changing and debugging catlog.

## Host

`recorder` -- 192.168.42.104, Ubuntu, headless. Everything lives under
`/home/karl/catlog-data`, exposed as two dedicated Samba shares, plus the
existing `[karl]` home share as a fallback.

The scripts are plain Python 3 with no service, no daemon and no state beyond
the filesystem. There is nothing to restart and nothing to keep running.

## Samba shares

Two dedicated shares, added 2026-11-06, so intake and output are reachable
without walking the whole home directory.

    [catlog-intake]   /home/karl/catlog-data/intake   read-write
    [catlog-out]      /home/karl/catlog-data/out      read-write

Both are defined in /etc/samba/smb.conf alongside the pre-existing
[Recordings] and [karl] shares, and follow their conventions. The
stanzas are reproduced in `docs/smb.conf.example`.

    browseable = yes
    read only = no
    guest ok = no
    valid users = karl
    create mask = 0664
    directory mask = 0775
    force user = karl

`force user = karl` is the important line. Files written from a Mac or from
another Linux box land owned by karl regardless of the client uid, which is
what lets the pipeline read what you dropped and lets you read what it
produced.

From macOS:

    Finder > Go > Connect to Server
    smb://recorder/catlog-intake
    smb://recorder/catlog-out

The live data at `~/catlog-data` is separate from this repository, which is the code.
They are deliberately separate, so that `git status` in the repo is never
polluted by half-processed albums.

### A trap worth knowing

`karl` is uid 1000 on recorder but uid 1001 on llamabear. A CIFS mount with a
hardcoded `uid=1000` on llamabear produces a mount owned by the wrong uid, and
every write fails with a bare "Permission denied" that looks like a server
problem and is not. Mount with the local uid:

    sudo mount -t cifs //192.168.42.104/catlog-intake /mnt/x \
        -o credentials=/etc/samba/.woke-credentials,uid=1001,gid=1001,vers=3.0

For anything driven from a container running as root this does not matter,
which is why it can sit undetected for a while.

### Reloading after a config change

    sudo systemctl restart smbd

A `reload` re-reads the config, but a newly added share may not appear until
the daemon is restarted. The first mount attempt after adding these shares
failed with "No such file or directory" on the share name until smbd was
restarted. The telltale is a usershare lookup in the log:

    process_usershare_file: stat of /var/lib/samba/usershares/catlog-intake failed

That message means smbd did not find the share in smb.conf at all.

## Dependencies

    sudo apt install -y ffmpeg p7zip-full unrar unar flac shntool cuetools \
        libimage-exiftool-perl imagemagick python3-mutagen

What each is actually for:

| Package | Why |
|---|---|
| ffmpeg, ffprobe | decode, split, encode, probe durations, resize artwork |
| p7zip-full, unrar, unar | listing and extracting zip, rar, 7z |
| flac | CUE-driven splitting of FLAC, if it is ever needed |
| shntool, cuetools | CUE parsing and boundary checks, for diagnosis |
| libimage-exiftool-perl | manual inspection; the pipeline itself does not call it |
| imagemagick | manual artwork work; the pipeline uses ffmpeg's scale filter |
| python3-mutagen | reading and writing ID3 |

`python3-mutagen` is a system package, so no virtualenv is required. Mutagen
1.46 and 1.48 have both been used successfully.

APE needs nothing extra -- ffmpeg decodes Monkey's Audio natively. SACD can't
be read at all; see the limitations section.

## Directory layout

    ~/catlog-data/
      intake/       drop zone. not managed.
      work/         scratch, per album. safe to delete.
      manifests/    <slug>/manifest.json. the approval record.
      out/          finished albums, library-shaped.
      reports/      scan-<ts>/ and render-<slug>-<ts>/
      quarantine/   reserved for items needing a decision
      logs/
      meta/         the per-album JSON inputs. not written by the scripts.

Create them once:

    mkdir -p ~/catlog-data/{intake,work,manifests,out,reports,quarantine,logs,meta}

`meta/` is where you keep the JSON that drives planning. It is an input, not an
output, so it is the one directory worth keeping under version control if you
ever want to reproduce an album.

## Environment variables

Every path has a default under `~/catlog-data`, so in normal use none of these are
needed. They exist so the pipeline can be pointed elsewhere, or run from a
container against a mounted volume.

| Variable | Used by | Default |
|---|---|---|
| `CATLOG_INTAKE` | scan, inspect, plan, render | `~/catlog-data/intake` |
| `CATLOG_MANIFESTS` | plan, render, deliver | `~/catlog-data/manifests` |
| `CATLOG_OUT` | render, deliver | `~/catlog-data/out` |
| `CATLOG_REPORTS` | scan, render | `~/catlog-data/reports` |
| `CATLOG_WORK` | render | `~/catlog-data/work` |
| `CATLOG_LOCAL_OUT` | deliver | same as `CATLOG_OUT` |

`deliver.py` also takes `--local-root` and `--dest-root` if the render output
and the delivery tree are in different places. If they resolve to the same
directory it verifies in place and skips copying.

## The stages

### scan.py

Walks each top-level item in intake and classifies it: archive, folder of
tracks, image plus CUE, image with no CUE, disc image. Reads format, bitrate
and duration via mutagen, measures artwork with a pure-stdlib JPEG/PNG parser,
sniffs CUE and EAC log encodings, and lists archive contents through `7z`.

Writes `reports/scan-<ts>/scan.txt` and `scan.json`. Read-only with respect to
the music.

Flags are the useful output: no artwork, artwork under 600, MP3 below 320,
single file with no CUE, ambiguous text encoding, nested archives.

### inspect.py

One item, in depth. Per-track CUE timings with computed durations, every image
with dimensions and a squareness score, text encodings, embedded-cuesheet
detection.

Takes an item name from intake, or `--all`.

### plan.py

The important one. Reads the metadata JSON and the CUE sheets, resolves every
track's start and duration, computes TIT1/TIT2 from the overrides, works out
the artwork resize, and writes `manifests/<slug>/manifest.json`. Encodes
nothing.

Behaviours worth knowing:

- A CUE with more than one `FILE` line is treated as pre-split tracks: each
  track's `source` points at its own file and `start_s` is zero.
- A CUE with one `FILE` line is treated as a disc image to be cut at index
  points.
- Per-track overrides win over per-disc, which win over album-level defaults.
- If a manifest already exists and is marked approved, planning refuses to
  overwrite it silently.
- Act prefix normalisation converts `Act 1: ` to `Act 1 - `, idempotently.

### render.py

Refuses to run unless the manifest is approved and free of errors. Downscales
the artwork once, then for each track extracts the range, encodes to MP3 320,
writes the ID3 frames, embeds the cover, and clears `COMM`/`TSSE`/`TENC`.
Copies `cover.jpg` into the album folder. Runs a sample verification pass and
writes `reports/render-<slug>-<ts>/render.txt`.

Encoding parameters, for the record:

    ffmpeg -ss <start> -i <source> -t <duration>
           -map_metadata -1 -vn
           -c:a libmp3lame -b:a 320k -compression_level 0
           -id3v2_version 4 -write_id3v1 0

`-map_metadata -1` discards everything the source carried, so no stale tags
survive into the output.

### deliver.py

Verifies the rendered album -- codec, bitrate band, sample rate, duration
against the plan, every required frame present, TIT1/TIT2 matching the plan,
exactly one embedded image, cover within 1280 -- and only then optionally
copies to the output tree. Refuses to copy while any problem remains.

### tidy.py

Strips `TSSE`, `TENC` and `COMM` from already-rendered files. Redundant for
anything rendered since the inline cleanup went in; kept for old output and for
files from other sources.

## Performance

Roughly 11x realtime for MP3 encoding on the i7-7700. Measured:

| Album | Audio | Wall time |
|---|---|---|
| Borodin, Prince Igor, 3 discs, 30 tracks | 210 min | ~13 min |
| Schubert, 8 tracks | 72 min | ~6 min |
| Rossini, Barbiere, 44 tracks | 130 min | ~9 min |

Length of audio dominates, not track count. Artwork resizing and tagging are
noise.

**Long renders must not run in the foreground of a session that can be cut
off.** Either detach:

    nohup python3 ~/catlog/render.py --slug X > /tmp/render.log 2>&1 &

or, if driving from another machine over ssh, expect a command timeout and run
it detached there too. A killed render leaves partial MP3s in the output
directory; delete the album folder before re-running, because the renderer
overwrites but does not clean up.

## Limitations

**SACD ISO is not supported.** Ubuntu has no `sacd_extract` package, and ffmpeg
cannot open a SACD ISO at all -- it handles DSD in DSF/DFF containers but not
the ISO 9660 image. Supporting it means building sacd-ripper from source and
deciding two things: stereo versus multichannel, and the DSD ultrasonic
lowpass. Skipping the lowpass folds noise above 30 kHz back into the audible
band, which is audible. Out of scope until there is a reason.

**A single image with no CUE cannot be split.** It quarantines. Either supply a
CUE or split by hand.

**Encoder output across CIFS stalls.** If ffmpeg writes straight to a CIFS
mount, long encodes can wedge partway with the producer alive but no bytes
moving. This was reproducible at around the 1.6 MB mark, twice. Reading from
CIFS is fine. The fix is to render to local disk and copy afterwards, which is
why `deliver.py` is a separate step. Do not "simplify" that away.

**Mutagen upgrades ID3v2.3 to v2.4 on save.** Any file the pipeline touches
comes out as v2.4. This is deliberate and was accepted library-wide. It means
mixed-version libraries are normal, and older v2.3 files with TYER are not a
bug.

**`TIT1` and `GRP1` both display as "Grouping"** in exiftool and several tag
editors. Confusing when reading a file by hand. TIT1 is the work, GRP1 is the
literal string `Classical`.

**Non-ASCII and punctuation.** Tags keep real punctuation including curly
quotes; filenames are sanitised. If a tag looks right and the filename looks
odd, that is by design. See `TAGGING.md`.

## Diagnostic recipes

Read tags properly without mutagen on the host:

    python3 -c "from mutagen.id3 import ID3; t=ID3('f.mp3'); print(t)"

Dump every frame of a file:

    exiftool -a -G1 -s file.mp3

Confirm what a CUE really says versus what it looks like:

    python3 ~/catlog/inspect.py "Album Folder"

Check an encode independently:

    ffprobe -v error -show_entries stream=codec_name,bit_rate -of default=nw=1 f.mp3

Find files that did not get tagged:

    find ~/catlog-data/out -name '*.mp3' -size -1k

## Recovering

**Re-render an album.** Delete the output album folder, set `"approved": true`
is already set, re-run render. No need to re-plan unless the metadata changed.

**Change the metadata after rendering.** Edit the JSON, move the existing
manifest aside (or set `approved` to false), re-plan, re-approve, delete the
output folder, re-render, re-deliver.

**A render died halfway.** Partial MP3s are untagged or truncated. Delete the
album output folder and start the render again. `deliver.py` would catch them,
but only after wasting the time.

**Intake item is wrong.** catlog never modifies intake. Fix the source, or
remove it and drop a corrected copy.

## Repository hygiene

The git repository holds code and documentation only. `intake/`, `out/`,
`manifests/`, `reports/`, `work/`, `logs/`, `quarantine/` and `meta/` are
ignored, because they are data and can be recreated or are large. If an album
matters enough to reproduce exactly, keep its metadata JSON somewhere outside
the pipeline and commit that instead.
