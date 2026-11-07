"""catlog internals.

The rules that matter live here, not in the entry point:

    naming     the library's tag and filename rules -- read this first
    cues       CUE parsing, folder enumeration, text encodings
    audio      ffprobe/mutagen probing and MP3 encoding
    artwork    measuring, choosing and resizing covers
    tagging    writing and reading the ID3 frames
    manifest   building, persisting and summarising the approval manifest
"""
