# The tag format

This is the specification catlog writes to. It describes the classical
library only. The Pazz & Jop library is tagged differently and deliberately.

Everything below is ID3v2.4 on MP3 320 CBR, 44100 Hz, stereo. Frame
names are the raw ID3 names because that is what the scripts read and write,
where a tag editor shows something different it is noted.

### The audio is always 44.1 kHz

Everything catlog writes is MP3 320 CBR at 44100 Hz, stereo. This has
to be FORCED in ffmpeg with -ar 44100 and is not a default worth
trusting: the default follows the source, and a DSD-derived source at
352.8 kHz silently produced 48000 Hz files which then failed verify
on every track. A high resolution source does not change the delivery
format. The library is one rate.

## Frame by frame

| Frame | Shown as | Holds |
|---|---|---|
| TALB | Album | `Composer: Work 1 / Work 2` |
| TIT1 | Grouping\* | The work, with its recording year |
| TIT2 | Title | The work, the movement number, the movement name |
| TPE1 | Artist | Full credit, orchestra first |
| TPE2 | Album Artist | Conductor, or the ensemble |
| TCOM | Composer | Name and life dates |
| TCON | Genre | Controlled vocabulary, see below |
| TDRC | Year | Release year |
| TRCK | Track | Position within the disc, bare number |
| TPOS | Disc | `n/total`, omitted for a single disc |
| GRP1 | Grouping\* | Always `Classical` |
| MVNM | Movement | Movement name, or act plus name for opera |
| MVIN | Movement number | `n/total`, omitted for opera |
| APIC | Cover | One image, embedded |
| COMM | Comment | Cleared. Reserved for Karl. |

\* Both TIT1 and GRP1 render as "Grouping" in exiftool. This causes a genuine
amount of confusion. TIT1 is the work; GRP1 is the constant string
`Classical`. If you are looking at a file and see two Groupings, that is why.

## TALB -- the album title

    Composer: Work 1 / Work 2

Composer surname in normal case. Work titles in normal case. The composer is
named once at the front; further works after the slash do not repeat it.

    Borodin: Prince Igor
    Mozart: Le Nozze di Figaro
    Schubert: Der Tod und das Maedchen / Rosamunde

When a disc carries works by two different composers, each work carries its
own composer:

    Brahms: Symphony no.2 / Dvořák: Symphony no.7

The content decides how many works appear. One work, two works, two composers,
all valid. This is why an album is not one work -- see TIT1.

An all-caps composer was tried and abandoned. Do not reintroduce it.

Use the shorter form for the work name. `Schubert: Der Tod und das Maedchen /
Rosamunde`, not the full catalogue form with quartet numbers and keys. The
detail belongs in TIT1, not here.

The album folder on disk uses underscores where the tag uses spaces and
slashes:

    Schubert_ Der Tod und das Maedchen _ Rosamunde

### Work numbering is lowercase

`no.` with a lower-case n and a full stop. Not `No.`, not `no`, not `nr.`:

    Symphony no.2 in E flat major, op.63
    Piano Trio no.1, op.73
    String Quartet no.14 in D minor, D.810
    Piano Concerto no.3 in D minor, op.30

This applies everywhere a work number appears -- TALB, TIT1, TIT2, and the
album folder name on disk. The library was already using it before it was
written down: `Rachmaninov_ Symphony no.3 in A minor`,
`Sibelius_ Symphony no.2 in D`, `Symphony no.1` throughout the Karajan tags.

Catalogue numbers keep their own conventions and are not affected: `op.63`,
`D. 810`, `FS 116`, `K.527`, `S. 110`.

### Several works where one dominates

When a disc is built around one substantial work and carries shorter pieces
alongside it, name the main work and roll the rest up as `Orchestral Works`:

    Larsson: Symphony no.3 / Orchestral Works

rather than listing all four:
    Larsson: Symphony no.3 / Three Orchestral Pieces / Adagio / Musica permutatio

The full contents still appear work by work in TIT1. The album title is a
label, not a table of contents. Use the full listing when the works are of
comparable weight and you would browse to any of them by name.

## TIT1 -- the work

    Work Title—(rec. YYYY)

Em dash between title and year. Space after `rec.`. The year is the
**recording** year, not the release year.

    Symphony no.2 in E flat major, op.63—(rec. 1964)
    String Quartet no.14 in D minor, D.810—(rec. 1984)
    Il Barbiere di Siviglia—(rec. 1957)

The recording year is there because a conductor may have recorded the same
work more than once, and two Karajan Brahms cycles need telling apart.

**TIT1 can change mid-album.** This is the single most important structural
point. A disc holding two quartets has two different TIT1 values, switching
at the first track of the second work. An album is a container, not a work.

Catalogue numbers prefix the work title inconsistently across the library
(`K.527 Don Giovanni—(rec. 1954)` versus a bare `Le Nozze di Figaro`). There
is no rule. Follow whatever the release itself uses.

## TIT2 -- the title

    TIT1 + space + [numeral ". "] + MVNM

    String Quartet no.14 in D minor, D.810—(rec. 1984) I. Allegro
    Il Barbiere di Siviglia—(rec. 1957) Act 1 - “Una voce poco fa” (Rosina)

The work name is repeated in the title on purpose. Navidrome has no
work or movement browse, so Title is the only field guaranteed to be visible.
Baking the work into it is what makes the library navigable.

## TPE1 and TPE2 -- who is on it

**TPE2 is the conductor.** For chamber music and recitals it is the ensemble
or the recitalist. This is the primary browse and sort axis, which is why it
is the conductor and not the detailed credit.

**TPE1 is the full credit, orchestra first.**

    The Sofia Festival Orchestra, cond. Emil Tchakarov
    Royal Concertgebouw Orchestra, cond. Bernard Haitink; with Janet Baker
      (mezzo-soprano) & James King (tenor)

Orchestra, then `cond.`, then conductor. Soloists come after a semicolon and
`with`, each with their voice type in parentheses. For non-orchestral discs
the string is just the group or the soloist.

**Opera is the exception: soloists are omitted.** Orchestra and conductor
only. No cast list, no chorus credit as a separate item.

    The Philharmonia Orchestra and Chorus, cond. Alceo Galliera

This is a deliberate exception, and it is a large saving -- opera casts are
long, and getting them right means research on every disc.

Soloists are **not** omitted elsewhere. A concerto or a lieder recital carries
the soloist.

## TCOM -- composer

Name followed by life dates in parentheses.

    Gustav Mahler (1860-1911)
    Franz Schubert (1797-1828)
    Gioachino Rossini (1792-1868)

**One composer only, never a list.** An album may hold works by several
composers, but TCOM is per track: each track carries the composer of the work
it belongs to. Never join composers with a slash or a comma, and never copy
the album's composers into every track.

    track 1-6  TCOM  Karol Szymanowski (1882-1937)
    track 7    TCOM  Anton Webern (1883-1945)

In the metadata JSON, album-level tcom is the default and
tracks_override.tcom overrides it for tracks belonging to another composer.

## TCON -- genre

Noun first, qualifier second, comma separated: `Quartet, string`,
`Concerto, piano`, `Suite, ballet`. Where the qualifier is obvious or the form
has no standard one, a single word stands alone: `Symphony`, `Opera`,
`Orchestral`. Capitalise the first word only.

### The census, 2026-11-06

13,090 files scanned, 83 distinct values, 14 files with no genre at all. The
vocabulary in actual use, by frequency:

    3323  Symphony              179  Quartet, string      55  Song
    2298  Song, lieder          135  Sonata, piano        54  Orchestral
    1623  Classical             133  Chamber Music        50  Overture
    1407  Suite, orchestral     120  Cantata              42  Soundtrack
    1175  Opera                 118  Tone Poem            39  Suite, orchestal
     329  Oratorio              111  Concerto, violin     38  Sonata, violin
     274  Suite, ballet        109  Ballet               31  Minimalism
     208  Concerto              104  Incidental Music     28  Concerto, horn
     193  Concerto, piano        80  Choral               27  Requiem
                                  79  Song, orchestral     26  Medieval
                                  78  Suite, piano         20  Concerto, cello
                                  69  Song, cycle          19  Concerto, viola
                                  64  Piano                19  Brass Ensemble

...and a long tail of 40 values seen ten times or fewer.

### Known duplicates

The tail contains the same value spelled several ways. These are errors, not
convention, and consolidating them changes no meaning:

    Suite, orchestral (1407)  <-  Suite, orchestal (39)
                                  Suite. orchestral (21)
                                  Suite, ochestral (20)
                                  Orchestral Suite (9)
                                  Orchestral suite (9)

    Symphonic Poem (13)       <-  Symphonic poem (1)
    Song, lieder (2298)       <-  Song, Lieder (3)
    Concerto, orchestral (19) <-  Concerto, ochestral (1)

Those five Suite variants account for 98 files that should join the 1,407.
Note the mixture of comma, full stop and missing comma as the separator --
match on the whole string, not on a pattern.

Not yet cleaned up. A standalone census script is worth having in the repo;
re-running over 13k files across CIFS takes about 7 minutes.

### Open questions

Three values need a decision rather than a sweep:

- **`Classical` (1,623)** -- a catch-all that conveys nothing. Deliberate
  "unknown" bucket, or should these be reclassified?
- **`Concerto` (208) vs `Concerto, piano` (193)** -- do the unqualified ones
  get instrument qualifiers, or stay generic?
- **`Chamber Music` (133)** -- overlaps `Quartet, string`, `Trio, piano`,
  `Quintet, piano`, `Sonata, violin`.

Karl's stated intent is a closed or semi-closed list. Until that lands, extend
cautiously and prefer an existing value over a new one.

## TDRC and the recording year

These are two different years and they are allowed to disagree.

- `TDRC` is the **release** year. For an old recording reissued on CD this is
  the CD's year.
- `(rec. YYYY)` inside TIT1 is the **recording** year.

A file with TDRC 1998 and `—(rec. 1975)` is correct, not a mistake. Do not
"fix" it.

Older files in the library carry TYER instead of TDRC (ID3v2.3). Those predate
the 2026 rewrite and are not a guide to current convention.

The recording year is almost never present in the source files. It has to be
researched, and it is the main reason a plan needs a human.

## MVNM and MVIN -- movements

For instrumental music:

    MVNM  Allegro                       (bare, no numeral)
    MVIN  1/4                           (position and total)

The numeral appears **only** in TIT2. MVNM stays clean.

**If a file has no MVIN, the numeral belongs inside MVNM.** Some sources
deliver movements that are not individually numbered, and the numeral is part
of the movement name:

    MVNM  III. Sequenz - Tuba mirum

Do not auto-number files that already carry a numeral in MVNM. You will get
`III. III. Sequenz - Tuba mirum`.

**Opera has no movements.** MVIN is never populated. The act goes into MVNM
as free text with a leading label:

    Act 1 - “Una voce poco fa” (Rosina)
    Act 2 - Temporale
    Overture, Act 1
    Act 1, continued
    Appendix - Tutto e disposto

Sources vary between `Act 1:` and `Act 1 - `. The library uses the hyphen,
so catlog normalises a colon to a hyphen. `Appendix - ` is the convention for
bonus material.

Some rips only prefix the first track of each act, which loses act grouping
the moment you sort by title. Prefer prefixing every track.

## APIC -- artwork

One embedded image per track, and a `cover.jpg` alongside the album.

- Long edge maximum **1280**, aspect ratio preserved, downscale only.
- Under **600** on the short edge, or missing: flag it.
- Between 600 and 1280: leave alone. Never upscale.

Picking the cover is the subtle part. It is not the largest image in the
folder. Booklet scans are frequently bigger than the cover and are extremely
not square:

    01.jpg  1412x2889   ratio 0.49   booklet spread
    02.jpg  1386x1797   ratio 0.77   booklet page
    03.jpg  1412x1451   ratio 0.97   the actual cover

Pick on squareness and filename convention, not on pixel count. `cover`,
`front`, `folder` beat `booklet`, `NN-NN`, `back`, `box`.

## COMM and TSSE -- what to clear

The importer left junk in `COMM`, usually just the composer surname. Karl
wants the field for his own use, so catlog clears it.

ffmpeg stamps `TSSE` with its own version string on every file it writes.
Also cleared.

## Filenames

    <disc>-<track> <movement name>.mp3   (multi-disc)
    <track> <movement name>.mp3          (single disc)

    1-01 Overture.mp3
    2-08 Act 2 - Aria of Prince Igor.mp3
    04 Overture.mp3                      (a one-disc album)

Zero-padded track number. The disc prefix appears ONLY on multi-disc sets.
A single-disc album carries no disc prefix at all, and its TPOS frame is
omitted entirely rather than being written as one slash one. Tags keep their real
punctuation; filenames are sanitised, because `?` and curly quotes are legal
in a tag and hostile in a filename.

    tag:   Act 1 - “Ehi, Fiorelli?...Mio signore”
    file:  1-04 Act 1 - _Ehi, Fiorelli_...Mio signore_.mp3

Characters replaced with underscore: `/ \ : ? * " < > |` and curly quotes.
The colon replacement is what leaves the `1-02 Act 1 - _Piano...` look.

## Album folder on disk

    <Artist Folder>/<Album Folder>/

Artist folder is the conductor, or the recitalist. Album folder is the tag
title with the separator punctuation replaced by underscores. A multi-disc
set is one album folder holding all the discs, not one folder per disc.
