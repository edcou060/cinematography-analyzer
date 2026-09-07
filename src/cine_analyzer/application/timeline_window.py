"""Window and downsample a timeline without loading the whole UI payload."""

from cine_analyzer.domain.timeline import Timeline, TimelinePoint

__all__ = ["MAX_TIMELINE_POINTS", "window_timeline"]

MAX_TIMELINE_POINTS = 2_000


def window_timeline(
    timeline: Timeline,
    *,
    start_ms: int,
    end_ms: int,
    max_points: int,
) -> tuple[TimelinePoint, ...]:
    """Inclusive start, exclusive end. Evenly stride when over the cap."""
    cap = min(max(1, max_points), MAX_TIMELINE_POINTS)
    selected = tuple(point for point in timeline.points if start_ms <= point.at_ms < end_ms)
    if len(selected) <= cap:
        return selected
    if cap == 1:
        return (selected[0],)
    last_index = len(selected) - 1
    indexes = dict.fromkeys(round(index * last_index / (cap - 1)) for index in range(cap))
    return tuple(selected[index] for index in indexes)
