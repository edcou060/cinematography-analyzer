# Metric definitions, formulas, and caveats

## 1. Measurement policy

The system measures observable signals and produces transparent heuristics. It does not infer a director's intention or a viewer's emotion as fact.

Every metric definition includes:

- semantic name and unit;
- input samples and preprocessing;
- formula or algorithm;
- method version and configuration;
- valid range and unavailable conditions;
- confidence or quality indicators;
- evidence references;
- known failure modes;
- validation method.

The dashboard uses three visual labels:

- **Measured** - direct deterministic property such as duration or percentile.
- **Estimated** - rule/model label such as framing or lighting key.
- **Interpreted** - optional prose derived from measured/estimated values.

## 2. Temporal and editing metrics

### 2.1 Shot boundary

A shot boundary is a timestamp returned by the configured transition detector after minimum-length and continuity validation. Boundary detection is not narrative scene detection.

Baseline method:

1. decode a downscaled video stream in presentation order;
2. run pinned PySceneDetect `AdaptiveDetector` or `ContentDetector`;
3. record per-frame detector statistics when debug mode is enabled;
4. force the video start and end as outer boundaries;
5. merge or flag intervals shorter than `min_shot_ms` according to configuration;
6. validate that shot intervals cover the complete media duration without overlap.

The threshold must be calibrated with a small annotated fixture set containing hard cuts, fades, flashes, whip pans, dark frames, and gradual lighting changes.

### 2.2 Shot duration

For shot (i):

\[
d_i = t_{i,end} - t_{i,start}
\]

Persist `duration_ms` as an integer. Display seconds only in the UI.

### 2.3 Average shot length

\[
ASL = \frac{1}{N}\sum_{i=1}^{N}d_i
\]

Also report median, p10, p90, standard deviation, and median absolute deviation. A mean alone is easily distorted by titles, long takes, or end credits.

### 2.4 Shots per minute

\[
SPM = \frac{60{,}000N}{D_{video,ms}}
\]

Name this `shots_per_minute`, not “cut rate,” because a clip with (N) shots has approximately (N-1) internal cuts.

### 2.5 Local edit activity

Create an impulse at each detected boundary and smooth it with a configurable kernel. For a window (W_t):

\[
C(t) = \min\left(1, \frac{\#\{b_j \in W_t\}}{c_{reference}}\right)
\]

The implementation may use a Gaussian kernel for a smoother curve, but the kernel width and reference density are stored in provenance. This component feeds the tension proxy and remains visible independently.

### Failure modes

- flashes and rapid exposure changes can resemble cuts;
- dissolves require a detector/config different from hard cuts;
- animation, strobe lights, and camera flashes may generate false positives;
- very dark or static adjacent shots can create false negatives;
- variable-frame-rate timestamp handling can shift frame-derived positions.

## 3. Deterministic sampling

Given a shot `[start_ms, end_ms)`, chromatic sample targets use fractions 0.20, 0.50, and 0.80 by default:

\[
t_{sample}=t_{start}+q(t_{end}-t_{start}),\quad q\in\{0.2,0.5,0.8\}
\]

For short shots:

1. remove duplicate millisecond targets;
2. avoid known transition frames when at least three interior frames exist;
3. always produce at least one representative target if a frame can be decoded;
4. record actual decoded presentation timestamp;
5. never silently substitute a frame from another shot.

Composition and motion sampling specify frames per second plus minimum/maximum samples per shot. The plan is deterministic for a given configuration.

## 4. Chromatic metrics

### 4.1 Preprocessing

For each selected frame:

1. apply display rotation;
2. convert to a consistent sRGB-oriented representation;
3. downscale while preserving aspect ratio;
4. identify contiguous near-black letterbox regions touching frame borders;
5. optionally exclude burned-in subtitle/overlay regions when configured;
6. draw a deterministic, stratified pixel sample up to `max_pixels_per_shot`;
7. convert sampled RGB values to float before CIE Lab conversion.

Do not concatenate resized frames vertically and treat that geometry as an image. Flatten sampled pixels from each frame and concatenate the pixel arrays. This avoids accidental spatial operations and makes per-frame contribution explicit.

### 4.2 CIE Lab handling

OpenCV can convert 8-bit or floating images to CIE Lab, but ranges differ. The recommended method is:

```python
rgb01 = rgb_u8.astype("float32") / 255.0
lab = cv2.cvtColor(rgb01, cv2.COLOR_RGB2LAB)
```

For this float path, preserve CIE-style `L*` on 0-100 and signed `a*`, `b*`. If an 8-bit path is used, explicitly convert its encoded L channel:

\[
L^* = L_{8bit}\frac{100}{255}
\]

Never compare an 8-bit OpenCV L value directly with thresholds defined in CIE L-star units.

### 4.3 Dominant palette

Baseline algorithm:

1. fit `MiniBatchKMeans(k=5)` to the sampled Lab pixels;
2. set a fixed `random_state` and explicit `n_init`;
3. predict cluster membership for the same sample;
4. compute cluster proportions;
5. sort centers by decreasing proportion;
6. convert centers Lab -> RGB, clamp, and format uppercase hex;
7. merge nearly identical centers when their configured Delta-E distance is below a threshold;
8. report fewer than five colors if the image lacks five stable clusters.

The k-means objective does not understand cinematic semantic color roles. A swatch is a pixel-distribution cluster, not necessarily a production-design color.

### 4.4 Palette stability

Measure how consistently palette clusters appear across the shot's sampled frames. One baseline is the weighted mean nearest-center Delta-E between each frame palette and the shot palette. Convert it to a bounded stability score with a documented scale.

Low stability may mean lighting changes, camera movement, multiple compositions inside a bad shot boundary, or insufficient sampling. It is useful as a quality warning, not a defect label.

### 4.5 Lightness distribution

Calculate on valid pixel samples:

- mean and standard deviation of L-star;
- p10, p50, and p90;
- dynamic spread `p90 - p10`;
- shadow ratio, default (L^* < 20);
- highlight ratio, default (L^* > 80);
- clipping proxies near (L^* < 1) and (L^* > 99).

Percentiles are more robust than variance alone and are easier to explain visually.

### 4.6 Lighting-key estimate

The first implementation is a configurable rule system, for example:

- `LOW_KEY_ESTIMATE` when median L-star is below 40 and either dynamic spread exceeds 45 or shadow ratio exceeds 0.40;
- `HIGH_KEY_ESTIMATE` when median L-star exceeds 65, shadow ratio is below 0.10, and dynamic spread is below 45;
- otherwise `BALANCED_ESTIMATE`.

These are starting thresholds, not cinematic law. Store them in config, display the underlying distribution, and calibrate on labeled examples. A bright high-contrast frame and a dark low-contrast frame show why a two-feature rule is insufficient.

### Chromatic failure modes

- letterboxing can dominate the black cluster;
- subtitles and logos can create artificial colors;
- skin, wardrobe, and background may need separate palettes;
- color-management metadata may be missing or wrong;
- HDR/transfer functions require a dedicated tone/color pipeline;
- compressed 8-bit footage can produce banding and unstable clusters;
- K-means is sensitive to sample composition and does not preserve rare accents.

MVP support should be limited to SDR inputs. Detect and reject or explicitly flag unsupported HDR/transfer characteristics.

## 5. Spatial composition metrics

### 5.1 Subject detection and tracking

Baseline subject class is `person`. A detector produces normalized boxes and confidence. A tracker associates observations within a shot. Reset track identity at shot boundaries unless a future cross-shot identity feature is explicitly designed.

Primary-subject selection is deterministic and documented. Example score for track (j):

\[
P_j = 0.45\,coverage_j + 0.35\,medianArea_j + 0.20\,medianConfidence_j
\]

where coverage is the fraction of sampled frames containing the track. Ties use stable ordering. This finds the most continuously prominent detected person, not the narratively important character.

### 5.2 Normalized centroid

For bounding box `(x_min, y_min, x_max, y_max)` already normalized by display width/height:

\[
c_x=\frac{x_{min}+x_{max}}{2},\qquad c_y=\frac{y_{min}+y_{max}}{2}
\]

Use mask centroid only when the selected mask adapter passes validation; boxes remain the baseline for reproducibility.

### 5.3 Thirds proximity

The four intersections are:

\[
R=\{(1/3,1/3),(2/3,1/3),(1/3,2/3),(2/3,2/3)\}
\]

For centroid (c), find normalized Euclidean distance to the nearest intersection:

\[
d(c,R)=\min_{r\in R}\lVert c-r\rVert_2
\]

Convert distance to a score:

\[
S_{thirds}=\exp\left(-\left(\frac{d}{\sigma}\right)^2\right)
\]

with `sigma` stored in configuration. Aggregate with median and p10 across observations. Report track coverage beside the score so a high value from one detected frame is not misleading.

Call this **thirds proximity**, never “composition quality” or “rule-of-thirds compliance.” Centered, symmetrical, off-balance, and negative-space compositions can be intentional.

### 5.4 Center proximity

Use the same distance formulation around `(0.5, 0.5)`. Showing thirds and center proximity together prevents the system from privileging one composition convention.

### 5.5 Headroom and lead-room candidates

Headroom can be approximated from a person/face box as the normalized distance between the top of the selected subject and the frame top. Lead room requires an estimated facing direction or motion direction and is deferred until that signal can be validated. Do not derive “look room” from box location alone.

### 5.6 Framing estimate

Bounding-box area alone is not enough. The baseline combines person height ratio, face height ratio when available, truncation at frame edges, and track coverage. A starting rule table can be calibrated:

| Estimated label | Evidence pattern |
| --- | --- |
| Extreme wide | person height small, environment dominant |
| Wide | most/all body visible with moderate frame coverage |
| Medium | person occupies roughly waist/chest-up scale |
| Close-up | face/head-and-shoulders dominates |
| Extreme close-up | face/detail fills a large portion or is cropped |
| Undetermined | no stable person/face evidence or conflicting samples |

Do not encode film-school verbal definitions as untested numeric truth. The annotated table is `docs/metrics/framing_calibration_v1.md`. Numeric thresholds live on hashed `SpatialConfig.framing_rules` with `version=framing_rules_v1` (ADR-0013).

### 5.7 Confidence

Framing confidence can combine detector confidence, track coverage, distance from rule thresholds, agreement across samples, and face/person consistency. It is a heuristic confidence until calibrated; name it as such.

### Spatial failure modes

- occlusion and profile faces;
- crowds and rapidly changing primary subject;
- mirrors, posters, screens, and photographs;
- non-human subjects;
- silhouettes and extreme color grades;
- multi-panel/split-screen images;
- camera rotation not applied before normalization;
- shot/reverse-shot boundaries missed by the temporal detector.

## 6. Motion metrics

### 6.1 Why raw optical flow is insufficient

Dense Farneback flow gives a vector per pixel between frames. Its magnitude combines camera motion, subject motion, parallax, noise, cuts, and compression. A moving subject is not the same as a pan; a handheld camera is not simply “erratic object motion.”

### 6.2 Baseline motion decomposition

Within each shot only:

1. downscale and grayscale frames;
2. compute dense flow between adjacent samples;
3. remove invalid/high-error regions and optional subject masks;
4. estimate robust global flow from likely background pixels using median vector or an affine/homography model;
5. calculate residual flow after subtracting global motion;
6. summarize magnitude with median and p90 rather than mean alone;
7. normalize by frame diagonal and elapsed time.

Report:

- `global_motion_magnitude` - proxy for camera/background motion;
- `residual_motion_magnitude` - proxy for local/subject motion;
- `flow_valid_ratio` - quality signal;
- optional dominant direction and directional consistency.

Pinned `motion-v1` defaults (ADR-0015): `working_max_side=320`, Farneback
`pyr_scale=0.5`, `levels=3`, `winsize=15`, `iterations=3`, `poly_n=5`,
`poly_sigma=1.2`, discontinuity flag at `1.5` frame-diagonals per second. Magnitudes
are median flow length divided by the working-frame diagonal and pair `dt` in seconds.
`direction_consistency` is the mean of `max(0, cosine)` between successive unflagged
global vectors.

Never compute flow across a detected cut. If a boundary is missed, robust outlier checks should flag the pair.

### 6.3 Camera-movement labels

Pan/tilt/zoom/handheld labels are a stretch feature. They require temporal consistency and geometric evidence:

- pan: coherent horizontal global motion over several pairs;
- tilt: coherent vertical global motion;
- zoom: radial expansion/contraction or scale component in homography;
- locked-off: low global motion with sufficient texture;
- handheld candidate: higher-frequency global motion with direction changes;
- unknown: insufficient texture, motion blur, or conflicting evidence.

Labels include confidence and should be benchmarked against annotated clips.

## 7. Audio metrics

### 7.1 Extraction

Use FFmpeg to extract a mono analysis stream at a fixed sample rate. Preserve the source time offset. If no audio stream exists, return a valid `NO_AUDIO` result.

### 7.2 Window features

At a fixed hop (for example 500 ms or 1 s), calculate:

- RMS energy and dBFS;
- onset strength;
- spectral flux;
- optional short-term loudness (LUFS) using a clearly named implementation;
- optional low/high frequency energy ratios.

Pinned `audio-v1` defaults (ADR-0016): mono s16le at the hashed `sample_rate_hz`
(22050), `window_ms=1000`. Onset strength is half-wave-rectified spectral flux from a
512-point FFT with hop 256. Short-term LUFS is not computed; `loudness_lufs_short_term`
is `None` until a later ADR names a library. Timeline alignment uses `TensionConfig.hop_ms`.

Do not call normalized RMS “volume” without defining the scale. Integrated loudness across a short, mixed clip and local intensity serve different purposes.

### 7.3 Normalization

For a within-video proxy, robustly normalize each component using observed percentiles:

\[
N(x)=clip\left(\frac{x-p_{10}}{p_{90}-p_{10}+\epsilon},0,1\right)
\]

This supports shape comparison inside one clip but not absolute comparison across films. A later cross-video model requires a fixed reference distribution and versioned calibration dataset.

## 8. Tension proxy

The “tension index” is renamed **visual-audio tension proxy** in technical surfaces. It is a configurable signal, not a psychological measurement.

At time (t):

\[
T(t)=clip(w_cC(t)+w_aA(t)+w_mM(t),0,1)
\]

Default demonstration weights:

- edit activity (w_c=0.35);
- audio activity (w_a=0.30);
- motion activity (w_m=0.35).

Weights must sum to one after excluding unavailable components. If audio is absent, renormalize the remaining configured weights and add a provenance warning. Store and display all component curves.

Pinned `tension-v1` defaults (ADR-0017): hop 500 ms, Gaussian cut sigma 750 ms,
`c_reference=3.0`, robust percentiles 10/90, `epsilon=1e-6`. `A(t)` is the mean of
robust-normalized onset, flux, and linear RMS. `M(t)` is the mean of robust-normalized
global and residual motion. Technical surfaces say **tension proxy**, never emotion.

### Suggested component construction

- `C(t)`: smoothed local boundary density.
- `A(t)`: weighted robust-normalized onset strength, spectral flux, and short-term loudness/RMS.
- `M(t)`: weighted robust-normalized global and residual motion magnitude.

Apply a short smoothing kernel after component alignment. Store raw and smoothed artifacts when debug mode is on.

### Validation

The tension proxy is validated for engineering consistency, not universal artistic truth:

- no component produces NaN/inf;
- values stay within `[0,1]`;
- time alignment is correct on synthetic impulses;
- missing components renormalize deterministically;
- increasing one isolated component cannot decrease the result;
- the dashboard explains the contributing components;
- a small human review checks whether peaks correspond to observable events.

## 9. Aggregate metrics

Video-level palette is not simply k-means over all video pixels; long shots would dominate. Choose and name an aggregation strategy:

- duration-weighted shot palettes;
- equal-shot-weighted palettes;
- representative-frame global palette.

The MVP reports per-shot palettes and may add one explicitly duration-weighted overview.

For composition, aggregate only shots with valid primary subjects and report the valid-shot ratio. For lighting key, report duration-weighted label proportions rather than a single label for the whole clip.

## 10. Evidence and explainability

Every shot detail page should show:

- time range and detector boundary score;
- representative frame and sampled timestamps;
- subject box/mask overlay used for composition;
- thirds/center guides;
- palette swatches with proportions;
- lightness histogram and thresholds;
- motion vector summary or trace;
- warnings, missing-data reason, method version, and confidence.

The user should be able to disagree with an interpretation while still trusting how the measurement was produced.

## 11. Calibration dataset

Create a small, legally usable validation corpus rather than relying on memory or famous copyrighted scenes.

Minimum set:

- synthetic hard cuts, fades, flashes, and no-cut motion;
- 30-50 short licensed/self-shot clips with annotated shot boundaries;
- 100-200 representative frames labeled for visible subject, framing category, and unusable cases;
- frames spanning low/high/balanced lightness patterns;
- clips with pans, tilts, locked-off subject motion, handheld motion, and low texture;
- audio clips with impulses, gradual ramps, silence, and no audio stream.

Store annotations separately from derived results. Record annotator, date, guideline version, and uncertainty. Use train/calibration examples to set thresholds and a held-out set for reporting.

## 12. Evaluation metrics

| Feature | Evaluation |
| --- | --- |
| Shot boundaries | precision/recall/F1 within timestamp tolerance; false positives by pattern |
| Shot durations | exact derivation from validated boundaries |
| Palette | determinism, cluster stability, proportion sum, qualitative evidence review |
| Lighting estimate | confusion matrix plus underlying continuous feature distributions |
| Subject detection | detection recall on visible-person subset |
| Tracking | track coverage and identity switches within shots |
| Framing estimate | macro F1 and abstention rate |
| Thirds proximity | geometry unit tests and evidence overlay review |
| Motion | synthetic direction/magnitude tests and annotated movement confusion matrix |
| Audio | synthetic signal expected values and alignment tests |
| Tension proxy | invariants, alignment, component explainability; no “accuracy” claim without a human target |

## 13. Metric card template

Add a completed card before adding any new dashboard metric:

```markdown
### Metric name
- Kind: measured | estimated | interpreted
- Unit/range:
- Inputs:
- Sampling:
- Preprocessing:
- Formula/algorithm:
- Method version:
- Config fields:
- Evidence:
- Unavailable when:
- Confidence/quality:
- Known failure modes:
- Unit tests:
- Golden/validation test:
- UI wording:
```
