# Framing calibration v1

Person-height ratios against frame height, measured from axis-aligned boxes. Labels are **estimates**. Face height is not used in v1. Cases below are the annotated table behind `framing_rules_v1`.

Visible definition: the subject is a single person-class box. Height ratio is `box.y_max - box.y_min`. Truncation means the box is within `edge_truncation` of the top and of the bottom.

| Case id | Visible pattern | Height ratio | Track coverage | Expected label | Notes |
| --- | --- | --- | --- | --- | --- |
| cal-ew | Tiny figure, environment dominant | 0.10 | 1.00 | EXTREME_WIDE_ESTIMATE | Below `extreme_wide_height_max` (0.18) |
| cal-wide | Full body, moderate coverage | 0.28 | 1.00 | WIDE_ESTIMATE | Below `wide_height_max` (0.38) |
| cal-med | Waist/chest-up scale | 0.50 | 1.00 | MEDIUM_ESTIMATE | Below `medium_height_max` (0.62) |
| cal-cu | Head-and-shoulders dominates | 0.72 | 1.00 | CLOSE_UP_ESTIMATE | Below `close_up_height_max` (0.85) |
| cal-ecu | Face/detail fills the frame | 0.92 | 1.00 | EXTREME_CLOSE_UP_ESTIMATE | At or above 0.85 |
| cal-ecu-crop | Box touches top and bottom | 0.70 | 1.00 | EXTREME_CLOSE_UP_ESTIMATE | Truncation overrides height band |
| cal-gap | Median sits on a threshold | 0.38 | 1.00 | MEDIUM_ESTIMATE | `wide_height_max` is exclusive-upper; 0.38 is medium |
| cal-split | Half the samples wide, half close | 0.28 / 0.72 | 1.00 | UNDETERMINED | Disagreement above `disagreement_fraction` |
| cal-unstable | Person on fewer than 40% of samples | 0.50 | 0.25 | no SpatialValue | `NO_SUBJECT` / `spatial_no_subject`, not zeros |
| cal-empty | No person box | — | 0.00 | no SpatialValue | `NO_SUBJECT` / `spatial_no_subject` |

`composition_grid.mp4` paints a magenta rectangle at height 0.50 with centroid on a thirds intersection; the fake backend is expected to report `MEDIUM_ESTIMATE`.
