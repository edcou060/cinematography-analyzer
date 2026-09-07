"""CPU chromatic adapter: float CIE Lab, letterbox mask, MiniBatchKMeans (ADR-0012)."""

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import numpy as np
from numpy.typing import NDArray

from cine_analyzer.application.lighting_key import estimate_lighting_key, lighting_key_confidence
from cine_analyzer.domain.chromatics import (
    ChromaticValue,
    ColorSwatch,
    LabColor,
    LightnessDistribution,
    RgbColor,
)
from cine_analyzer.domain.config import ChromaticConfig
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.ports.chromatics import ChromaticComputeResult, ChromaticFrame

__all__ = [
    "OpenCvChromaticAnalyzer",
    "letterbox_mask",
    "load_cv2",
    "load_sklearn",
    "rgb_uint8_to_lab",
]

_NO_FRAMES = "chromatic_no_decoded_samples"
_LETTERBOX = "chromatic_letterbox_insufficient"
_NO_PIXELS = "chromatic_no_usable_pixels"
_DECODE = "chromatic_decode_failed"
_CLUSTER = "chromatic_cluster_failed"
_IMAGE_NDIM = 3
_COLOR_CHANNELS = 3


def load_cv2() -> Any:
    """Import OpenCV. Isolated so tests can replace this function."""
    import cv2

    return cv2


def load_sklearn() -> SimpleNamespace:
    """Import MiniBatchKMeans. Isolated so tests can replace this function."""
    from sklearn.cluster import MiniBatchKMeans

    return SimpleNamespace(MiniBatchKMeans=MiniBatchKMeans)


def rgb_uint8_to_lab(rgb: NDArray[np.uint8], cv2_module: Any | None = None) -> NDArray[np.float32]:
    """Convert HxWx3 uint8 sRGB to float CIE Lab (L* on 0-100)."""
    cv2 = load_cv2() if cv2_module is None else cv2_module
    rgb01 = rgb.astype(np.float32) / 255.0
    return cast("NDArray[np.float32]", cv2.cvtColor(rgb01, cv2.COLOR_RGB2LAB))


def letterbox_mask(
    lstar: NDArray[np.float32],
    *,
    lstar_max: float,
    coverage: float,
) -> tuple[NDArray[np.bool_], float]:
    """Mask out contiguous near-black rows/columns that touch the frame border."""
    near = lstar <= lstar_max
    height, width = near.shape
    top = 0
    while top < height and float(near[top].mean()) >= coverage:
        top += 1
    bottom = height
    while bottom > top and float(near[bottom - 1].mean()) >= coverage:
        bottom -= 1
    left = 0
    while left < width and bottom > top and float(near[top:bottom, left].mean()) >= coverage:
        left += 1
    right = width
    while right > left and bottom > top and float(near[top:bottom, right - 1].mean()) >= coverage:
        right -= 1
    mask = np.zeros((height, width), dtype=np.bool_)
    if bottom > top and right > left:
        mask[top:bottom, left:right] = True
    ratio = float(mask.mean()) if mask.size else 0.0
    return mask, ratio


class OpenCvChromaticAnalyzer:
    """Measure one shot from JPEG bytes. Domain models never import this module."""

    def analyze_shot(
        self,
        frames: tuple[ChromaticFrame, ...],
        config: ChromaticConfig,
    ) -> ChromaticComputeResult:
        """Cluster sampled Lab pixels and attach a lighting-key estimate."""
        if not frames:
            return _absent(MetricStatus.INSUFFICIENT_DATA, _NO_FRAMES, ())
        cv2 = load_cv2()
        kept = 0
        total = 0
        parts: list[NDArray[np.float32]] = []
        used: list[UUID] = []
        decoded = 0
        for frame in frames:
            rgb = _decode_jpeg_rgb(frame.jpeg, cv2)
            if rgb is None:
                continue
            decoded += 1
            rgb = _downscale(rgb, config.working_max_side, cv2)
            if rgb.size == 0:
                continue
            lab_img = rgb_uint8_to_lab(rgb, cv2)
            mask, _ratio = letterbox_mask(
                lab_img[:, :, 0],
                lstar_max=config.letterbox_lstar_max,
                coverage=config.letterbox_coverage,
            )
            kept += int(mask.sum())
            total += int(mask.size)
            if not bool(mask.any()):
                continue
            parts.append(lab_img[mask])
            used.append(frame.sample_id)
        if decoded == 0:
            return _absent(MetricStatus.FAILED, _DECODE, ())
        usable = (kept / total) if total else 0.0
        if usable < config.min_usable_pixel_ratio or not parts:
            reason = _LETTERBOX if usable < config.min_usable_pixel_ratio else _NO_PIXELS
            return _absent(MetricStatus.INSUFFICIENT_DATA, reason, tuple(used))
        pixels = _subsample_rows(np.concatenate(parts, axis=0), config.max_pixels_per_shot)
        lightness = _lightness(pixels[:, 0], config)
        swatches = _palette(pixels, config, cv2)
        if not swatches:
            return _absent(MetricStatus.FAILED, _CLUSTER, tuple(used))
        lighting = estimate_lighting_key(lightness, config.lighting_key_rules)
        value = ChromaticValue(
            palette=swatches,
            lightness=lightness,
            lighting_key=lighting,
            usable_pixel_ratio=usable,
        )
        confidence = lighting_key_confidence(lighting, lightness, config.lighting_key_rules)
        return ChromaticComputeResult(
            status=MetricStatus.OK,
            value=value,
            confidence=confidence,
            reason_code=None,
            evidence_sample_ids=tuple(used),
        )


def _absent(
    status: MetricStatus,
    reason: str,
    evidence: tuple[UUID, ...],
) -> ChromaticComputeResult:
    return ChromaticComputeResult(
        status=status,
        value=None,
        confidence=None,
        reason_code=reason,
        evidence_sample_ids=evidence,
    )


def _decode_jpeg_rgb(jpeg: bytes, cv2_module: Any) -> NDArray[np.uint8] | None:
    if not jpeg:
        return None
    array = np.frombuffer(jpeg, dtype=np.uint8)
    bgr = cv2_module.imdecode(array, cv2_module.IMREAD_COLOR)
    if bgr is None or bgr.ndim != _IMAGE_NDIM or bgr.shape[2] != _COLOR_CHANNELS:
        return None
    return cast("NDArray[np.uint8]", cv2_module.cvtColor(bgr, cv2_module.COLOR_BGR2RGB))


def _downscale(rgb: NDArray[np.uint8], max_side: int, cv2_module: Any) -> NDArray[np.uint8]:
    height, width = rgb.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return rgb
    scale = max_side / longest
    new_width = max(1, round(width * scale))
    new_height = max(1, round(height * scale))
    return cast(
        "NDArray[np.uint8]",
        cv2_module.resize(rgb, (new_width, new_height), interpolation=cv2_module.INTER_AREA),
    )


def _subsample_rows(pixels: NDArray[np.float32], max_rows: int) -> NDArray[np.float32]:
    count = pixels.shape[0]
    if count <= max_rows:
        return pixels
    indices = (np.arange(max_rows, dtype=np.float64) * (count / max_rows)).astype(np.int64)
    indices = np.clip(indices, 0, count - 1)
    return cast("NDArray[np.float32]", pixels[indices])


def _lightness(lstar: NDArray[np.float32], config: ChromaticConfig) -> LightnessDistribution:
    values = np.clip(lstar.astype(np.float64), 0.0, 100.0)
    p10, p50, p90 = (float(item) for item in np.percentile(values, [10.0, 50.0, 90.0]))
    ordered = tuple(sorted((p10, p50, p90)))
    return LightnessDistribution(
        mean_lstar=float(values.mean()),
        stddev_lstar=float(values.std(ddof=0)),
        p10_lstar=ordered[0],
        p50_lstar=ordered[1],
        p90_lstar=ordered[2],
        shadow_ratio=float((values < config.shadow_lstar).mean()),
        highlight_ratio=float((values > config.highlight_lstar).mean()),
    )


def _palette(
    pixels: NDArray[np.float32],
    config: ChromaticConfig,
    cv2_module: Any,
) -> tuple[ColorSwatch, ...]:
    unique = np.unique(np.round(pixels, decimals=3), axis=0)
    cluster_count = min(config.clusters, unique.shape[0], pixels.shape[0])
    if cluster_count < 1:
        return ()
    if cluster_count == 1:
        centres: list[NDArray[np.float64]] = [np.asarray(pixels.mean(axis=0), dtype=np.float64)]
        counts = [pixels.shape[0]]
    else:
        centres, counts = _fit_kmeans(pixels, cluster_count, config)
    merged = _merge_centres(centres, counts, config.delta_e_merge)
    swatches = [_swatch(centre, count, cv2_module) for centre, count in merged if count > 0]
    swatches = _merge_duplicate_hex(swatches)
    if not swatches:
        return ()
    swatches.sort(key=lambda item: (-item[1], item[0].rgb.hex))
    total = sum(count for _swatch_value, count in swatches)
    minimum = max(1, int(config.min_swatch_proportion * total))
    kept = [(draft, count) for draft, count in swatches if count >= minimum]
    if not kept:
        kept = [swatches[0]]
    total = sum(count for _swatch_value, count in kept)
    ranked: list[ColorSwatch] = []
    remaining = 1.0
    for index, (draft, count) in enumerate(kept):
        if index == len(kept) - 1:
            proportion = max(0.0, min(1.0, remaining))
        else:
            proportion = count / total
            remaining -= proportion
        ranked.append(draft.model_copy(update={"rank": index + 1, "proportion": proportion}))
    return tuple(ranked)


def _fit_kmeans(
    pixels: NDArray[np.float32],
    cluster_count: int,
    config: ChromaticConfig,
) -> tuple[list[NDArray[np.float64]], list[int]]:
    api = load_sklearn()
    samples = np.ascontiguousarray(pixels, dtype=np.float64)
    batch = max(1, min(config.kmeans_batch_size, samples.shape[0]))
    model = api.MiniBatchKMeans(
        n_clusters=cluster_count,
        random_state=config.random_seed,
        batch_size=batch,
        n_init=config.kmeans_n_init,
        max_iter=100,
    )
    labels = model.fit_predict(samples)
    centres = [np.asarray(centre, dtype=np.float64) for centre in model.cluster_centers_]
    counts = [int(item) for item in np.bincount(labels, minlength=cluster_count)]
    return centres, counts


def _merge_duplicate_hex(
    swatches: list[tuple[ColorSwatch, int]],
) -> list[tuple[ColorSwatch, int]]:
    combined: dict[str, tuple[ColorSwatch, int]] = {}
    for draft, count in swatches:
        hex_color = draft.rgb.hex
        existing = combined.get(hex_color)
        if existing is None:
            combined[hex_color] = (draft, count)
            continue
        prev, prev_count = existing
        total = prev_count + count
        keeper = prev if prev_count >= count else draft
        combined[hex_color] = (keeper, total)
    return list(combined.values())


def _merge_centres(
    centres: list[NDArray[np.float64]],
    counts: list[int],
    delta_e_merge: float,
) -> list[tuple[NDArray[np.float64], int]]:
    items = sorted(
        ((centre, count) for centre, count in zip(centres, counts, strict=True) if count > 0),
        key=lambda item: (-item[1], float(item[0][0]), float(item[0][1]), float(item[0][2])),
    )
    merged: list[tuple[NDArray[np.float64], int]] = []
    for centre, count in items:
        placed = False
        for index, (existing, existing_count) in enumerate(merged):
            if _delta_e(existing, centre) < delta_e_merge:
                total = existing_count + count
                blended = (existing * existing_count + centre * count) / total
                merged[index] = (blended, total)
                placed = True
                break
        if not placed:
            merged.append((centre, count))
    return merged


def _delta_e(left: NDArray[np.float64], right: NDArray[np.float64]) -> float:
    delta = left.astype(np.float64) - right.astype(np.float64)
    return float(np.sqrt(float(np.dot(delta, delta))))


def _swatch(
    lab_centre: NDArray[np.float64],
    count: int,
    cv2_module: Any,
) -> tuple[ColorSwatch, int]:
    lstar = float(np.clip(lab_centre[0], 0.0, 100.0))
    a_star = float(np.clip(lab_centre[1], -128.0, 127.0))
    b_star = float(np.clip(lab_centre[2], -128.0, 127.0))
    red, green, blue = _lab_to_rgb(lab_centre, cv2_module)
    hex_color = f"#{red:02X}{green:02X}{blue:02X}"
    return (
        ColorSwatch(
            rank=1,
            lab=LabColor(lstar=lstar, a=a_star, b=b_star),
            rgb=RgbColor(r=red, g=green, b=blue, hex=hex_color),
            proportion=1.0,
        ),
        count,
    )


def _lab_to_rgb(lab_centre: NDArray[np.float64], cv2_module: Any) -> tuple[int, int, int]:
    patch = lab_centre.reshape(1, 1, 3).astype(np.float32)
    rgb01 = cv2_module.cvtColor(patch, cv2_module.COLOR_LAB2RGB)[0, 0]
    rgb = np.clip(np.rint(rgb01 * 255.0), 0, 255).astype(np.int64)
    return int(rgb[0]), int(rgb[1]), int(rgb[2])
