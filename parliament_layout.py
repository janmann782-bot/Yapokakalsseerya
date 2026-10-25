"""Shared geometry for parliament PNG and SVG diagrams."""
from __future__ import annotations

import math
from dataclasses import dataclass

PARLIAMENT_LAYOUT_VERSION = 2


def _max_arc_seats(radius: float, pitch: float) -> int:
    """Maximum seat centers on a semicircle with at least ``pitch`` distance."""
    if radius <= 0 or pitch <= 0:
        return 1
    ratio = min(1.0, pitch / (2.0 * radius))
    if ratio >= 1.0:
        return 1
    angle = 2.0 * math.asin(ratio)
    return max(1, int(math.floor(math.pi / angle)))


def hemicycle_layout(total: int, s: float) -> tuple[list[int], float, float, float, int, int]:
    """Build non-overlapping concentric semicircle rows.

    Row count grows until the exact chord distance between neighbouring seats is
    larger than the seat diameter plus a visible gap. No overflow is ever dumped
    into the outer row, which was the cause of seats overlapping on 200+ chambers.
    """
    if total <= 0:
        return [], 26 * s, 13 * s, 4 * s, int(132 * s), int(111 * s)

    if total <= 60:
        seat_r, min_rows = 5.1 * s, 4
    elif total <= 110:
        seat_r, min_rows = 4.5 * s, 5
    elif total <= 170:
        seat_r, min_rows = 3.9 * s, 6
    elif total <= 280:
        seat_r, min_rows = 3.2 * s, 7
    else:
        seat_r, min_rows = 2.9 * s, 8

    gap = 1.8 * s
    # Conservative spacing also guarantees axis-aligned square seats never touch.
    pitch = 2.0 * seat_r * math.sqrt(2.0) + gap
    inner_r = 24.0 * s
    step = max(10.8 * s, pitch + 1.4 * s)

    rows = min(min_rows, total)
    while rows < 24:
        capacities = [
            _max_arc_seats(inner_r + step * i, pitch)
            for i in range(rows)
        ]
        if sum(capacities) >= total:
            break
        rows += 1

    capacities = [
        _max_arc_seats(inner_r + step * i, pitch)
        for i in range(rows)
    ]

    # Distribute proportionally to row capacity, then fill remaining free slots
    # from the outside in. Every row always stays under its geometric capacity.
    cap_sum = max(1, sum(capacities))
    counts = [max(1, min(cap, int(total * cap / cap_sum))) for cap in capacities]

    # If mandatory one-per-row pushed us above total, remove from inner rows first.
    while sum(counts) > total:
        changed = False
        for i in range(len(counts)):
            if counts[i] > 1 and sum(counts) > total:
                counts[i] -= 1
                changed = True
        if not changed:
            break

    remaining = total - sum(counts)
    while remaining > 0:
        changed = False
        for i in range(len(counts) - 1, -1, -1):
            if counts[i] < capacities[i]:
                counts[i] += 1
                remaining -= 1
                changed = True
                if remaining <= 0:
                    break
        if not changed:
            # Defensive fallback: add another outer row rather than overlap.
            rows += 1
            rr = inner_r + step * (rows - 1)
            cap = _max_arc_seats(rr, pitch)
            capacities.append(cap)
            take = min(cap, remaining)
            counts.append(take)
            remaining -= take

    outer_r = inner_r + step * (len(counts) - 1)
    diagram_h = int(outer_r + seat_r + 29 * s)
    base_y = int(diagram_h - 19 * s)
    return counts, inner_r, step, seat_r, diagram_h, base_y


@dataclass(frozen=True, slots=True)
class Seat:
    x: float
    y: float
    radius: float
    row: int
    angle: float


@dataclass(frozen=True, slots=True)
class Diagram:
    seats: tuple[Seat, ...]
    width: float
    height: int


def fitted_hemicycle(total: int, width: float, scale: float = 1.0) -> Diagram:
    """Fit the complete seat bounds and order parties as angular sectors.

    Angles sweep from the lower left through the top to the lower right.
    Seats on all rows take part in the sweep; we never fill one ring at a time.
    Equal-angle seats go from the outside row towards the inside row.
    """
    padding = 10 * scale
    if width <= 2 * padding:
        raise ValueError("Diagram width is too small")
    if total <= 0:
        return Diagram((), width, math.ceil(2 * padding))
    counts, inner_r, step, seat_r, _, _ = hemicycle_layout(total, scale)
    outer_r = inner_r + step * (len(counts) - 1)
    # Scale the circles and the row spacing together. Padding also contains
    # the SVG stroke and integer raster rounding at the outermost seats.
    fit = min(1.0, (width / 2 - padding) / (outer_r + seat_r))
    radius = seat_r * fit
    baseline = padding + (outer_r + seat_r) * fit
    height = math.ceil(2 * padding + (outer_r + 2 * seat_r) * fit)
    seats = []
    for row, count in enumerate(counts):
        arc_r = (inner_r + step * row) * fit
        for j in range(count):
            angle = math.pi / 2 if count == 1 else math.pi - (j + 0.5) * math.pi / count
            seats.append(Seat(width / 2 + arc_r * math.cos(angle), baseline - arc_r * math.sin(angle), radius, row, angle))
    seats.sort(key=lambda seat: (-seat.angle, -seat.row))
    return Diagram(tuple(seats), width, height)


def seat_colors(parties: list[dict], total: int) -> list[str]:
    """Preserve each party's count, followed by grey vacant seats."""
    colors = []
    for party in parties:
        take = min(max(0, int(party['seats'])), total - len(colors))
        colors.extend([party['color']] * take)
        if len(colors) == total:
            break
    colors.extend(['#C8CCD1'] * (total - len(colors)))
    return colors
