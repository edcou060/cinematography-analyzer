# Engineering review of the original concept

The original concept is strong. These changes make it implementable, defensible, and easier to explain in an interview.

| Original idea | Production clarification |
| --- | --- |
| PySceneDetect “scenes” | Treat outputs as detected shots. Narrative scenes require a separate semantic grouping problem. |
| Three consumers read a shared memory frame buffer | Baseline on immutable sample artifacts and reference-only messages. Keep shared memory as a measured single-host optimization behind a port. |
| Process full video concurrently from ingestion | Shot detection is an early sequential dependency. Build a sampling plan, then parallelize independent shot/pillar work. |
| Use Celery / Ray | Choose one. Local runner first, Celery/Redis for the distributed profile; Ray only if measured scheduling/locality needs justify migration. |
| YOLO11 + SAM 2 from the start | Use a detector protocol and YOLO/fake baseline. Add SAM 2 only if masks measurably improve a target metric. |
| Box area determines shot type | Use person/face ratios, truncation, temporal agreement, and abstention; call the result a framing estimate. |
| Rule of Thirds Alignment Score | Call it thirds proximity. Centered and non-thirds composition can be intentional. |
| Raw optical flow detects pans/tilts | Separate robust global/background motion from residual/subject motion; add camera labels only after temporal validation. |
| RGB -> Lab with OpenCV uint8 thresholds | Use float RGB `[0,1]` -> Lab or explicitly convert encoded 8-bit L to L-star; thresholds must state units. |
| Mean + variance classifies lighting | Use percentiles, spread, shadow/highlight ratios, and versioned calibrated rules; expose underlying evidence. |
| K-means returns a five-color palette | Sample deterministically, mask bars, sort by prevalence, merge near duplicates, and allow fewer than five stable colors. |
| High audio volume + cuts + motion equals tension | Present a componentized, configurable tension proxy. Normalize carefully and never claim audience-emotion ground truth. |
| vLLM/Llama critic as a headline feature | Make it optional, metrics-only, short, validated, separately cached, and unable to fail or modify analysis. |
| Recompile for NVDEC early | Profile CPU decode first. Hardware decode is valuable only when decode dominates and compatibility is tested. |
| Triton as “gold standard” | A dedicated GPU worker is enough for a solo demo. Triton belongs behind a measured need for batching/model isolation. |
| Threads always fail because of the GIL | Many native CV/ML calls release the GIL. Select threads/processes from profiling and isolation needs. |
| Streamlit owns the workflow | Streamlit is an API client. PostgreSQL/API own job state; worker processes own heavy compute. |

The result remains ambitious: it still demonstrates media ingestion, strict schemas, CPU/GPU resource routing, concurrency, distributed tasks, observability, testing, and visualization. The difference is that every advanced component now has a reason and an entry point.
