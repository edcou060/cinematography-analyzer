# Primary technical references

Reference snapshot: 2026-09-06. Pin and validate actual dependency versions in `uv.lock`; these links explain design choices rather than replacing compatibility tests.

1. PySceneDetect 0.7.1 API - detectors, backends, timecode pairs, and version-pinning warning: https://www.scenedetect.com/docs/latest/api.html
2. Ultralytics YOLO model catalog - YOLO11 as a mature option and newer model families: https://docs.ultralytics.com/models/
3. Ultralytics YOLO11 documentation: https://docs.ultralytics.com/models/yolo11/
4. Ultralytics licensing guidance - AGPL-3.0 and Enterprise paths: https://www.ultralytics.com/license
5. Meta SAM 2 repository - video/image predictors, requirements, checkpoints, and licenses: https://github.com/facebookresearch/sam2
6. OpenCV color conversions - supported CIE Lab conversions, input ranges, and float normalization: https://docs.opencv.org/4.x/d8/d01/group__imgproc__color__conversions.html
7. OpenCV optical flow tutorial - dense Farneback output and examples: https://docs.opencv.org/4.x/d4/dee/tutorial_optical_flow.html
8. scikit-learn MiniBatchKMeans - batch sizing, deterministic `random_state`, C-contiguous conversion, and API: https://scikit-learn.org/stable/modules/generated/sklearn.cluster.MiniBatchKMeans.html
9. Pydantic models - validation, serialization, JSON Schema, and extra-field behavior: https://docs.pydantic.dev/latest/concepts/models/
10. FFmpeg ffprobe - machine-readable media/stream probing and writers: https://ffmpeg.org/ffprobe.html
11. FastAPI background-task caveat - heavy work and multi-process/server task tools: https://fastapi.tiangolo.com/tutorial/background-tasks/
12. Celery introduction - brokers, workers, distribution, concurrency, routing/workflows: https://docs.celeryq.dev/en/stable/getting-started/introduction.html
13. Celery task guide - acknowledgement, redelivery, idempotency, retries, and late ack: https://docs.celeryq.dev/en/stable/userguide/tasks.html
14. vLLM OpenAI-compatible server - optional local critic serving interface: https://docs.vllm.ai/en/latest/serving/openai_compatible_server/
15. Streamlit documentation - application and deployment reference: https://docs.streamlit.io/

## Citation policy for the repository

- Use primary/official documentation for technical behavior.
- Link a model paper/repository and the exact code/weights license.
- Record the accessed/version snapshot when a claim can change.
- Treat thresholds and architecture choices as this project's decisions, not claims made by a library.
- Re-run compatibility, golden, and benchmark tests after upgrades.
