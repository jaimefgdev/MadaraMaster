#!/usr/bin/env python3
# jaimefg1888


def format_bytes(size: int | float) -> str:
    """Convert a byte count to a human-readable string.

    Args:
        size: Number of bytes. Negative values are treated as zero.

    Returns:
        A formatted string such as ``"4.20 MB"`` or ``"512 KB"``.
    """
    if size < 0:
        return "0 B"
    size = int(size)
    if size < 1024:
        return f"{size} B"

    units: list[tuple[int, str, int]] = [
        (1024**4, "TB", 2),
        (1024**3, "GB", 2),
        (1024**2, "MB", 1),
        (1024**1, "KB", 1),
    ]
    for threshold, unit, decimals in units:
        if size >= threshold:
            return f"{size / threshold:.{decimals}f} {unit}"

    return f"{size} B"
