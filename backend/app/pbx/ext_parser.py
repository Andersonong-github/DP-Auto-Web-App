"""Extension/number range parsing (ported from the desktop ``utils/ext_parser.py``, rules aligned line by line)."""

from __future__ import annotations

from typing import List

# Max extensions expanded per range, so a single paste cannot overload the service
MAX_RANGE = 5000


def parse_ext_range(ext_range: str, strip_six: bool = True) -> List[str]:
    """Expand input like ``"60338314500 - 60338314509"`` into a list of numbers.

    Commas separate multiple groups; ranges are zero-padded to the width of the start value;
    ``strip_six`` removes a leading 6.
    """
    exts: List[str] = []
    for group in str(ext_range or "").split(","):
        group = group.strip()
        if not group:
            continue
        if "-" in group:
            parts = group.split("-", 1)
            start, end = parts[0].strip(), parts[1].strip()
            if strip_six and start.startswith("6"):
                start = start[1:]
            if strip_six and end.startswith("6"):
                end = end[1:]
            # Still being typed (for example "60338314500-"), so skip
            if not start.isdigit() or not end.isdigit():
                continue
            ext_len = len(start)
            start_num = int(start)
            end_num = int(end)
            if end_num < start_num:
                continue
            if end_num - start_num + 1 > MAX_RANGE:
                end_num = start_num + MAX_RANGE - 1
            for num in range(start_num, end_num + 1):
                exts.append(str(num).zfill(ext_len))
        else:
            ext = group
            if strip_six and ext.startswith("6"):
                ext = ext[1:]
            exts.append(ext)
    return exts


def parse_ext_groups(ext_range: str, strip_six: bool = True) -> List[List[str]]:
    """Return groups split by comma, for tasks such as "create one number per group"."""
    groups: List[List[str]] = []
    for group in str(ext_range or "").split(","):
        group = group.strip()
        if not group:
            continue
        exts = parse_ext_range(group, strip_six=strip_six)
        if exts:
            groups.append(exts)
    return groups
