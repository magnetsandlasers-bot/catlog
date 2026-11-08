"""The library's naming rules.

Every rule here came from Karl, usually by correcting a mistake. Do not
"improve" them without asking. The prose version is docs/TAGGING.md; this is
the executable one, and the two must agree.
"""

import re

EM_DASH = "\u2014"
REC_SEP = EM_DASH + "(rec. "


def safe_filename(name):
    """Make a movement name safe as a filename.

    Tags keep real punctuation; filenames cannot. Slashes, colons, question
    marks, asterisks, quotes, angle brackets, pipes and curly quotes all
    become underscores. The colon rule is what produces the library's
    characteristic "1-02 Act 1 - _Piano..." look.
    """
    name = str(name).replace(chr(0), "")
    for bad in (47, 92, 58, 63, 34, 42, 60, 62, 124, 8220, 8221):
        name = name.replace(chr(bad), "_")
    name = re.sub(r"\s+", " ", name).strip()
    return name.rstrip(". ")


def normalize_act(name):
    """Normalise an act label to the library form: "Act 3: X" -> "Act 3 - X".

    Idempotent. CUE sheets vary between a colon and a hyphen; the library
    uses the hyphen.
    """
    m = re.match(r"^Act (\d+)", name)
    if m and name[m.end():m.end() + 1] == ":":
        return "Act " + m.group(1) + " -" + name[m.end() + 1:]
    return name


def work_tag(work, year):
    """TIT1: the work title with its recording year.

        Symphony no.2 in E flat major, op.63—(rec. 1964)

    The year is the RECORDING year, not the release year. It is there so two
    recordings of the same work by the same conductor can be told apart.
    """
    if year in (None, ""):
        return work
    return f"{work}{REC_SEP}{year})"


def title_tag(tit1, mvnm, roman=None):
    """TIT2: the work repeated, then the movement.

        String Quartet no.14 in D minor, D.810—(rec. 1984) I. Allegro

    The work is repeated in the title on purpose: Navidrome has no work or
    movement browse, so Title is the only field guaranteed to be visible.

    A single-movement work has no mvnm, and the title collapses to the work
    rather than repeating itself.
    """
    if not mvnm:
        return tit1
    lead = (roman + ". ") if roman else ""
    return f"{tit1} {lead}{mvnm}".strip()


def track_filename(disc, track, stem, tpos_total=1):
    """Multi-disc keeps its disc prefix. A single disc gets none."""
    if tpos_total in (None, 1):
        return f"{track:02d} {safe_filename(stem)}.mp3"
    return f"{disc}-{track:02d} {safe_filename(stem)}.mp3"


def tpos_tag(disc, tpos_total):
    """TPOS is omitted entirely for a single-disc album."""
    if tpos_total in (None, 1):
        return ""
    return f"{disc}/{tpos_total}"


def filename_stem(mvnm, tit1):
    """Filename source: the movement, or the work for a single-movement piece."""
    if mvnm:
        return mvnm
    return tit1.split(EM_DASH)[0].strip()


def album_folder(talb):
    """The album folder on disk: tag punctuation becomes underscores.

        Schubert: Der Tod und das Maedchen / Rosamunde
        Schubert_ Der Tod und das Maedchen _ Rosamunde
    """
    return safe_filename(talb)


def has_upper_work_number(text):
    """Detect the No. mistake. Work numbers are lowercase no.N."""
    return bool(re.search(r"\bNo\.\s*\d", text))
