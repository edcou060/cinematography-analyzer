"""Within-shot IoU tracker. Track identity resets when a new shot is passed."""

from uuid import UUID

from cine_analyzer.application.spatial_geometry import box_centroid, box_iou
from cine_analyzer.domain.config import SpatialConfig
from cine_analyzer.domain.spatial import BoxNorm, SubjectObservation
from cine_analyzer.ports.spatial import DetectionHit

__all__ = ["IoUSubjectTracker"]

_PERSON = "person"


class IoUSubjectTracker:
    """Greedy IoU matching against the last box of each live track."""

    def track(
        self,
        hits: tuple[DetectionHit, ...],
        sample_ids: tuple[UUID, ...],
        config: SpatialConfig,
    ) -> tuple[SubjectObservation, ...]:
        """Associate person hits. Non-person classes and low confidence are dropped."""
        last_box: dict[str, BoxNorm] = {}
        next_index = 1
        observed: list[SubjectObservation] = []
        by_sample: dict[UUID, list[DetectionHit]] = {}
        for hit in hits:
            if hit.class_name != _PERSON:
                continue
            if hit.detector_confidence < config.person_confidence:
                continue
            by_sample.setdefault(hit.sample_id, []).append(hit)
        for sample_id in sample_ids:
            sample_hits = by_sample.get(sample_id, [])
            assigned_tracks: set[str] = set()
            assigned_hits: set[int] = set()
            pairs: list[tuple[float, str, int]] = []
            for track_id, box in last_box.items():
                for index, hit in enumerate(sample_hits):
                    pairs.append((box_iou(box, hit.box), track_id, index))
            pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
            chosen: dict[int, str] = {}
            for iou, track_id, index in pairs:
                if iou < config.track_iou_min:
                    break
                if track_id in assigned_tracks or index in assigned_hits:
                    continue
                assigned_tracks.add(track_id)
                assigned_hits.add(index)
                chosen[index] = track_id
            for index, hit in enumerate(sample_hits):
                assigned = chosen.get(index)
                if assigned is None:
                    assigned = f"t{next_index:04d}"
                    next_index += 1
                last_box[assigned] = hit.box
                centroid_x, centroid_y = box_centroid(hit.box)
                observed.append(
                    SubjectObservation(
                        track_id=assigned,
                        sample_id=hit.sample_id,
                        class_name=hit.class_name,
                        detector_confidence=hit.detector_confidence,
                        box=hit.box,
                        centroid_x=centroid_x,
                        centroid_y=centroid_y,
                    )
                )
        return tuple(observed)
