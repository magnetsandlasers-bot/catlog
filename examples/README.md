# Example metadata files

One JSON file per album. These are real albums that went through the pipeline,
kept as working references.

| File | What it demonstrates |
|---|---|
| `borodin-prince-igor.json` | multi-disc, one work across three discs, opera |
| `schubert-abq.json` | one disc, two works, TIT1 changing mid-disc, roman numerals, MVIN |
| `rossini-barbiere.json` | one disc released as 44 pre-split FLACs with a CUE |
| `larsson-orchestral-works-3.json` | no CUE at all (folder mode), four works, one single-movement |
| `nielsen-symphonies-2-6.json` | folder mode, two works, two movements sets restarting |
| `rachmaninov-concertos-2-3.json` | folder mode, soloist in TPE1 after the orchestra |
| `butterworth-terroni.json` | folder mode, per-track TPE1 where one work has a different ensemble |

Read them alongside `docs/TAGGING.md`. The fields are explained in
`docs/USER-GUIDE.md` step 5.

## The source shapes

**Multi-disc, single work.** Every disc uses the album-level `tit1`. No
overrides needed except where a movement name is wrong in the CUE. Discs are
separate entries in `discs`, distinguished by `tpos`.

**Multi-work, single disc.** The second work needs `tit1` set on *every* track
it covers, not just its first, because the album-level value is the fallback
for anything not overridden. This is the one that catches people out. Roman
numerals go in `roman`, positions in `mvin`, and both restart at each work.

**Pre-split with a CUE.** The CUE has one `FILE` per track. catlog reads each
track's duration from its own file; tracking boundaries come from the CUE.

**No CUE at all.** The disc entry uses `"folder": "path"` instead of
`"cue"`. Audio files are enumerated sorted by name, so filenames must sort
into playing order. Track numbers are assigned from that order.

**Single-movement works.** Set `"mvnm": ""`. TIT2 collapses to TIT1 rather
than repeating itself, and the filename comes from the work title. Larsson's
`Musica permutatio` is the example.

**Per-track artist.** `tpe1` can be overridden per track. Butterworth's viola
sonata is Goff and Terroni, not the trio, so TPE2 stays `The Terroni Trio` for
the album while TPE1 differs on tracks 4-6.

## What is not in these files

Nothing sets `mvnm` from the CUE except where the CUE was wrong, or where
there is no CUE at all. The CUE is the default source for movement names and
act labels; overrides exist to correct it or to supply it.

No `mvin` appears in the opera examples. Opera has no movement numbers.

Work numbers are always lowercase `no.` -- `Symphony no.3`, never `No.3`.
