"""Parts of a result: what a target recolours separately (Limine: the menu and the
wallpaper; Plymouth: each group of images and the progress bar...), each with its
own accent.

    -a mauve peach                  every part, one result per accent
    -a mauve wallpaper=peach        the wallpaper in peach, the rest in mauve
    -a menu=mauve wallpaper=peach   one result

A part without an accent of its own takes the plain ones (one result each); a
part named with PART=ACCENT keeps that accent in every result. The output name
carries the accent of the main part (the first that uses an accent), then
"-<part>-<accent>" for each other part whose accent differs.
"""
import re

from .mapping import note_accent_ignored
from .palette import ACCENTS

PART = re.compile(r"[a-z0-9][a-z0-9-]*")


def split_accents(values):
    """-a values -> (plain accents, {part: accent}). Checked here: part names and
    their accents; the plain ones are expanded by the caller ('all')."""
    plain, parts = [], {}
    for v in values or []:
        if "=" not in v:
            plain.append(v)
            continue
        part, _, acc = (s.strip() for s in v.partition("="))
        if not PART.fullmatch(part):
            raise SystemExit(f"-a {v}: a part name is lowercase letters, digits and '-'")
        if acc not in ACCENTS:
            raise SystemExit(f"-a {v}: unknown accent '{acc}' (choose from: {', '.join(ACCENTS)})")
        if part in parts and parts[part] != acc:
            raise SystemExit(f"-a: two accents for the part '{part}'")
        parts[part] = acc
    return plain, parts


def check_parts(a, known):
    """Fail on a PART=ACCENT whose part this result does not have."""
    bad = [p for p in a.part_accents if p not in known]
    if bad:
        raise SystemExit(f"-a {bad[0]}=…: no part named '{bad[0]}' "
                         f"(parts: {', '.join(known) or 'none'})")


def accent_sets(a, using):
    """The results to write: [(accents, name)]. using: the parts that use the accent,
    the main one first; accents: {part: accent} for them; name: what goes into the
    output name as its accent (None when no part uses one)."""
    if not using:
        return [({}, None)]
    fixed = a.part_accents
    free = any(p not in fixed for p in using)
    out = []
    for acc in (a.accent if free else [None]):
        accents = {p: fixed.get(p, acc) for p in using}
        main = accents[using[0]]
        name = "-".join([main, *(f"{p}-{accents[p]}" for p in using[1:] if accents[p] != main)])
        out.append((accents, name))
    return out


def note_unused(a, using, reasons=None):
    """A part given an accent that it does not use: say so (reasons: {part: why})."""
    for p in a.part_accents:
        if p not in using:
            note_accent_ignored(a, f"for the part '{p}' "
                                   f"{(reasons or {}).get(p, 'as it does not use the accent')}")


def single(a, parts):
    """Whether these parts give a single result whatever the plain accents are."""
    return len(a.accent) == 1 or all(p in a.part_accents for p in parts)
