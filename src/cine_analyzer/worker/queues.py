"""Declared Celery queue names and stage-to-queue routing (ADR-0021)."""

from typing import Final

__all__ = [
    "QUEUE_CPU_ANALYSIS",
    "QUEUE_CPU_DECODE",
    "QUEUE_CRITIC",
    "QUEUE_GPU_SPATIAL",
    "QUEUE_INGEST",
    "TASK_CRITIC",
    "TASK_GPU_SPATIAL",
    "TASK_ORCHESTRATE",
    "TASK_RUN_STAGE",
    "WORKER_CPU_QUEUES",
    "WORKER_GPU_QUEUES",
    "queue_for_stage",
    "queues_for_role",
    "task_name_for_stage",
]

QUEUE_INGEST: Final = "ingest"
QUEUE_CPU_DECODE: Final = "cpu_decode"
QUEUE_CPU_ANALYSIS: Final = "cpu_analysis"
QUEUE_GPU_SPATIAL: Final = "gpu_spatial"
QUEUE_CRITIC: Final = "critic"

TASK_ORCHESTRATE: Final = "cine_analyzer.orchestrate_analysis"
TASK_RUN_STAGE: Final = "cine_analyzer.run_stage"
TASK_GPU_SPATIAL: Final = "cine_analyzer.run_gpu_spatial"
TASK_CRITIC: Final = "cine_analyzer.run_critic"

WORKER_CPU_QUEUES: Final = f"{QUEUE_INGEST},{QUEUE_CPU_DECODE},{QUEUE_CPU_ANALYSIS},{QUEUE_CRITIC}"
WORKER_GPU_QUEUES: Final = QUEUE_GPU_SPATIAL

_STAGE_QUEUES: Final[dict[str, str]] = {
    "orchestrate": QUEUE_INGEST,
    "sampling": QUEUE_CPU_DECODE,
    "report": QUEUE_CPU_ANALYSIS,
    "aggregate": QUEUE_INGEST,
    "spatial": QUEUE_GPU_SPATIAL,
    "critic": QUEUE_CRITIC,
}


def queue_for_stage(stage_name: str) -> str:
    """Return the resource queue for a stage. Unknown names are rejected."""
    try:
        return _STAGE_QUEUES[stage_name]
    except KeyError:
        message = f"unknown stage name {stage_name!r}"
        raise ValueError(message) from None


def queues_for_role(role: str) -> str:
    """Default listen list for a CPU or GPU worker process."""
    if role == "gpu":
        return WORKER_GPU_QUEUES
    if role == "cpu":
        return WORKER_CPU_QUEUES
    message = f"unknown worker role {role!r}"
    raise ValueError(message)


def task_name_for_stage(stage_name: str) -> str:
    """Celery task name for a command. GPU and critic stay off the CPU task."""
    if stage_name == "orchestrate":
        return TASK_ORCHESTRATE
    if stage_name == "spatial":
        return TASK_GPU_SPATIAL
    if stage_name == "critic":
        return TASK_CRITIC
    return TASK_RUN_STAGE
