# Example metadata files

One JSON file per album. These are three real albums that went through the
pipeline, kept as working references.

| File | What it demonstrates |
|---|---|
| `borodin-prince-igor.json` | multi-disc, one work across three discs, opera |
| `schubert-abq.json` | one disc, two works, TIT1 changing mid-disc, roman numerals, MVIN |
| `rossini-barbiere.json` | one disc released as 44 pre-split FLACs, opera, act normalisation |

Read them alongside `docs/TAGGING.md`. The fields are explained in
`docs/USER-GUIDE.md` step 5.

## The three shapes, side by side

**Multi-disc, single work.** Every disc uses the album-level `tit1`. No
overrides needed except where a movement name is wrong in the CUE. Discs are
separate entries in `discs`, distinguished by `tpos`.

**Multi-work, single disc.** The second work needs `tit1` set on *every* track
it covers, not just its first, because the album-level value is the fallback
for anything not overridden. This is the one that catches people out.

**Pre-split files.** No overrides for track boundaries at all -- the CUE has
one `FILE` per track, and catlog reads each track's duration from its own
file. Overrides are only used here to fix two movement names the ripper had
mangled.

## What is not in these files

Nothing here sets `mvnm` from the CUE, except where the CUE was wrong. The CUE
is the default source for movement names and act labels; overrides exist to
correct it, not to restate it.

No `mvin` appears in the opera examples. Opera has no movement numbers.
