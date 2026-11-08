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
natively. ffmpeg cannot open a SACD ISO image (ISO 9660), but it DOES
decode DFF and DSF, so an ISO must first be extracted to DFF or DSF with
sacd_extract or iso2dsd. See the DSD section under Traps for what that
output looks like and what to do about it.

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


**DSD sources arrive at 352.8 kHz and that is not a mistake.** ffmpeg
decoding DSD64 picks DSD64 native rate divided by 8, so a plain
ffmpeg -i x.dff x.flac gives 24-bit 352.8 kHz. Measured on a 48-minute
disc: 4.7 GB, and it takes about 16x realtime to encode rather than the
usual 18x. Two things follow.

First, DSD carries aggressive noise shaping. Measured band RMS relative
to 100-1000 Hz on that source: -67 dB at 15-20 kHz, but -50 dB at
25-40 kHz and -22 dB at 60-100 kHz. That ultrasonic hash is most of the
file size. It is NOT audible after resampling, and it does not alias:measured output above 20 kHz sits at -96 dB with the default swresample
and -94 dB with soxr, so the default resampler is fine and soxr buys
nothing here.

Second, use an explicit target rate when making the archive.
ffmpeg -i x.dff -c:a flac -ar 88200 -af lowpass=f=30000 x.flac gives
about 890 MB instead of 4.9 GB for the same disc, at 2x the delivery
rate so the later resample to 44.1 kHz is a clean integer decimation.

**Every DSD-to-FLAC conversion done that way has a broken seektable.**
ffmpeg reports read_timestamp() failed in the middle on any -ss seek
into the file, reproducible from a local copy so it is the files and not
CIFS. A full decode is clean and durations match the source log, so the
audio is intact. It does not affect rendering, because a per-track
folder source starts every track at 0.0 and never seeks.

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

**SACD ISO.** ffmpeg cannot open one. The ISO must be extracted to DFF or
DSF first, with sacd_extract or its Java GUI wrapper iso2dsd. Both emit
DSD, not PCM: RAW ISO, DFF and DSF are the only output modes, so the
ISO-to-FLAC work still has to be done with ffmpeg afterwards.

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


## Rendering albums in parallel

batch.py renders several albums at once, MAX_PARALLEL workers, default 4.
Measured on llamabear 2026-11-07, 300 s chunks, libmp3lame 320k CBR, encoding
to local disk, page cache warmed first:

    workers   wall     throughput      speedup   efficiency
    1         16.5 s   18.1x realtime  1.00x     100 %
    2         18.3 s   32.9x           1.81x      91 %
    4         18.4 s   65.3x           3.60x      90 %
    6         26.4 s   68.3x           3.76x      63 %

Four is the correct cap and it is not a guess: llamabear has 4 physical cores
and libmp3lame is single threaded, so 4 encoders is one per core. Six workers
add 5 % throughput for 50 % more CPU, which is the hyperthread siblings being
useless to LAME. Do not raise the default without re-measuring, and expect a
worse ratio if the audio source is CIFS rather than local.

At 4 workers a normal 60 minute album takes roughly 3 minutes of wall clock,
and a full length opera such as Prince Igor, 209 minutes, took 11.5 minutes
when rendered on its own.

The stall watchdog is now PER ALBUM rather than on the whole output tree.
With several renders in flight, one wedged encode no longer shows up as the
tree failing to grow, so a tree-wide check would go blind exactly when it
mattered. A stall kills the process GROUP. Killing only the python parent
leaves ffmpeg running and still writing the file, which is how orphan encodes
end up burning CPU unnoticed: I hit exactly that during benchmarking.

NICE_LEVEL, default 10, nices the renders so interactive work on llamabear
still gets CPU, Ollama and OpenWebUI included. Nice only has an effect under
contention, so it costs nothing when the box is otherwise idle.

## Staging and publishing

With STAGE_DIR set, an album is encoded to local disk and published to the
real out tree afterwards. The batch driver sets CATLOG_OUT to the stage for
the render subprocess, so catlog.py itself is unchanged.

Publishing is atomic in the sense that matters. The album is copied into a
hidden .incoming-SLUG directory beside its destination, checked against the
staged original by FILE COUNT and BYTE COUNT, and only then swapped into
place. If either check fails the incoming directory is deleted and the
out tree is not touched. This is not paranoia: the first version copied
straight onto the destination, and a deliberately corrupted copy left
truncated MP3s in out looking exactly like a finished album. A clean
failure beats a corrupt success.

On success the staged copy is deleted, so staging costs no permanent disk.
On failure the staged copy is KEPT, so a retry does not re-encode. The stage
is only cleaned automatically when the render itself stalls or errors.

The done webhook is sent after publishing, not after encoding. A completion
notification therefore means the album is in the out tree, which is what
notifications are for. An earlier build pinged on render completion, and the
album was still sitting in the stage directory.

Launch recipe, from llamabear, staging on local disk:

    docker run -d --name catlog-batch
        -v /home/karl/pylibs:/libs:ro
        -v /mnt/recorder_pipeline:/r
        -v /home/karl/catlog-stage:/stage
        -e HOME=/r -e PYTHONPATH=/libs
        -e STAGE_DIR=/stage/out
        -e SLUGS=slug-one,slug-two,slug-three
        --entrypoint python3 ghcr.io/open-webui/open-webui:main /r/catlog/batch.py

Leave STAGE_DIR unset to render straight to out, which is the old behaviour
and is fine for a single album.
