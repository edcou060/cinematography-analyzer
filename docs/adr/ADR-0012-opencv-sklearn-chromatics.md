# ADR-0012: Chromatic compute uses OpenCV float Lab and sklearn MiniBatchKMeans

- Status: Accepted
- Date: 2026-09-06
- Owners: project owner
- Supersedes: none

## Context

Phase 05 requires float CIE Lab conversion, deterministic MiniBatchKMeans, and letterbox masking. Phase 04 already pinned `opencv-python` (not headless) because PySceneDetect decodes through OpenCV. Installing `opencv-python-headless` beside `opencv-python` is a known conflict. A dedicated colour-science library would add another hashed colour path without changing the public Lab contract.

## Decision

- Keep `opencv-python` as the OpenCV wheel. Do not add `opencv-python-headless`.
- Convert sampled pixels with the float path `rgb_u8.astype(float32)/255` then `cv2.COLOR_RGB2LAB`, so L* is on `[0, 100]` and is never an 8-bit OpenCV L channel.
- Cluster with `sklearn.cluster.MiniBatchKMeans` using hashed `n_clusters`, `random_state`, `batch_size`, and `n_init`.
- Do not add an extra colour-management library. OpenCV is the Lab converter.
- Domain and application code do not import `cv2`, `sklearn`, or NumPy; those stay in the adapter behind `ChromaticAnalyzer`.

## Alternatives considered

**Switch the base install to `opencv-python-headless`.** Rejected: PySceneDetect and JPEG evidence encoding already depend on the existing wheel; dual OpenCV packages are unsafe.

**FFmpeg `colorspace` filters for Lab.** Rejected: another subprocess boundary for a per-pixel conversion OpenCV already does in-process.

**A pure-Python k-means to avoid scikit-learn.** Rejected: the metric definition names MiniBatchKMeans with explicit seed and `n_init`.

## Consequences

Easier: one OpenCV install, documented Lab ranges, deterministic clustering.

Harder: scikit-learn pulls SciPy and Joblib into the base lockfile. Those licences must stay in `THIRD_PARTY_NOTICES.md`.

## Verification

Unit tests convert black, white, and a known sRGB colour through the float Lab path. Golden frames run twice and compare palette order and lighting-key labels. `tests/unit/test_supply_chain.py` accepts the new lockfile closure.

## Revisit trigger

OpenCV 5 changes Lab encoding, or scikit-learn 2 changes MiniBatchKMeans defaults in a way that shifts palettes; then pin a new range and bump `chromatics-v1`.
