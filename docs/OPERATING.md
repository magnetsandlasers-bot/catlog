# Operating notes

Notes for whoever is running this. Mostly written for me, after each thing
that cost more time than it should have.

## Shape

`catlog.py` is the only entry point. `lib/` holds the parts that matter:

    lib/naming.py     the library's tag and filename rules
    lib/cues.py       CUE parsing, folder enumeration, text encodings
    lib/audio.py      probing, MP3 encoding
    lib/artwork.py    measuring, choosing, resizing covers
    lib/tagging.py    reading and writing ID3 frames
    lib/manifest.py   building and persisting the approval manifest

If a rule about how music gets tagged needs changing, it goes in `naming.py`
and `docs/TAGGING.md` together. Those two must not disagree.

## Where things live

    ~/catlog              code. git repo.
    ~/catlog-data         data. NOT in the repo, deliberately.
      intake/             drop zone            \\recorder\catlog-intake
      out/                finished albums      \\recorder\catlog-out
      manifests/          approval records
      meta/               the per-album JSON inputs
      reports/  work/  logs/  quarantine/

Code and data are separate so that a `git clean -xdf` in the repo cannot
touch the intake or the delivered albums.

Environment overrides, all defaulting under `~/catlog-data`:

    CATLOG_DATA  CATLOG_INTAKE  CATLOG_OUT  CATLOG_MANIFESTS
    CATLOG_REPORTS  CATLOG_WORK  CATLOG_META

## Dependencies

    sudo apt install -y ffmpeg p7zip-full unrar unar flac shntool \
        cuetools libimage-exiftool-perl imagemagick python3-mutagen

`python3-mutagen` is a system package, so no virtualenv. ffmpeg decodes APE
natively. SACD is not supported and cannot be without building sacd-ripper.

## Driving it from another machine

The SSH tool blocks `python3` on the hosts, so run the code in a container
against a CIFS mount of recorder's home:

    sudo mount -t cifs //192.168.42.104/karl /mnt/recorder_pipeline \
        -o credentials=/etc/samba/.woke-credentials,uid=1001,gid=1001,vers=3.0

    docker run --rm \
        -v /home/karl/pylibs:/libs:ro \
        -v /mnt/recorder_pipeline:/r \
        -e HOME=/r -e PYTHONPATH=/libs \
        --entrypoint python3 ghcr.io/open-webui/open-webui:main \
        /r/catlog/catlog.py

`HOME=/r` is what makes the default paths resolve. `PYTHONPATH=/libs` points
at a mutagen installed outside the image:

    docker run --rm -v /home/karl/pylibs:/libs --entrypoint pip \
        ghcr.io/open-webui/open-webui:main install --target /libs mutagen

Long renders outlive a 30-second command timeout. Run detached
(`docker run -d --name X ...`) and poll the output directory. A killed
render leaves partial MP3s behind; delete the album folder before re-running.

## Traps

**Encoding straight to CIFS stalls.** Writing ffmpeg output directly to a
CIFS mount can wedge partway with the producer alive and no bytes moving.
Reproducible at around the 1.6 MB mark, twice. Reading from CIFS is fine.
If a render ever looks stuck, check whether the destination is a network
mount before debugging anything else.

**`karl` is uid 1000 on recorder and woke-server but uid 1001 on llamabear.**
A mount with a hardcoded `uid=1000` from llamabear yields a mount karl cannot
write to — bare "Permission denied", clean server-side log. Container writes
run as root and mask this entirely.

**A new or changed Samba share needs `systemctl restart smbd`**, not
`reload`. Symptom when missed: `mount error(2)` on the share name, and
`process_usershare_file: stat of /var/lib/samba/usershares/<name> failed` in
`/var/log/samba/log.<client>`.

**ffmpeg stamps `TSSE`** with its own version string on every file. Cleared
during tagging; `tidy` exists for anything that predates that.

**Mutagen upgrades ID3v2.3 to v2.4 on save.** Deliberate and accepted
library-wide. Mixed versions are normal, not a bug.

**Old manifests have no per-track `tpos`.** Render supplies it from the disc
if absent, so both manifest generations work. Don't remove that fallback.

## Measured timings

Roughly 11x realtime on the i7-7700. Total audio duration dominates; track
count is nearly irrelevant.

| Album | Audio | Wall |
|---|---|---|
| Borodin, Prince Igor, 3 discs | 210 min | ~13 min |
| Schubert, 2 quartets | 72 min | ~6 min |
| Rossini, Barbiere, 44 tracks | 130 min | ~9 min |
| Larsson, 9 tracks | 73 min | ~4 min |
| Nielsen, 8 tracks | 65 min | ~3 min |
| Rachmaninov, 6 tracks | 76 min | ~4 min |
| Butterworth, 9 tracks | 56 min | ~3 min |

## Things that are not implemented

**SACD ISO.** No `sacd_extract` package in Ubuntu, and ffmpeg cannot open a
SACD ISO at all — it handles DSD in DSF/DFF containers but not the ISO 9660
image. Would need sacd-ripper built from source, plus decisions about stereo
versus multichannel and the DSD ultrasonic lowpass (skipping it folds noise
above 30 kHz back into the audible band). Out of scope until there is a
reason.

**A single image with no CUE** cannot be split. Quarantines.

## Recovering

**Re-render.** Delete the album folder under `out/` and render again. The
manifest is already approved.

**Change the metadata after rendering.** Edit the JSON, delete the manifest
(or set `approved` false), re-plan, re-approve, delete the output folder,
re-render.

**A render died halfway.** Partial MP3s are untagged or truncated. Delete the
folder and start over. `verify` would catch them but only after the time is
spent.

## Genre vocabulary

`catlog.py census PATH` counts `TCON` across a finished library. Last run
over 13,090 files: 83 distinct values, with known duplicate spellings
documented in `TAGGING.md`. Cleaning those up has not been done.
