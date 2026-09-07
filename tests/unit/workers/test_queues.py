"""Queue names and CPU/GPU routing (ADR-0021)."""

import pytest

from cine_analyzer.worker.queues import (
    QUEUE_CPU_ANALYSIS,
    QUEUE_CPU_DECODE,
    QUEUE_CRITIC,
    QUEUE_GPU_SPATIAL,
    QUEUE_INGEST,
    TASK_CRITIC,
    TASK_GPU_SPATIAL,
    TASK_ORCHESTRATE,
    TASK_RUN_STAGE,
    WORKER_CPU_QUEUES,
    WORKER_GPU_QUEUES,
    queue_for_stage,
    queues_for_role,
    task_name_for_stage,
)


def test_gpu_spatial_never_shares_the_cpu_analysis_queue() -> None:
    assert queue_for_stage("spatial") == QUEUE_GPU_SPATIAL
    assert queue_for_stage("spatial") != QUEUE_CPU_ANALYSIS
    assert QUEUE_GPU_SPATIAL not in WORKER_CPU_QUEUES.split(",")
    assert queues_for_role("gpu") == WORKER_GPU_QUEUES == QUEUE_GPU_SPATIAL


def test_declared_stage_queues() -> None:
    assert queue_for_stage("orchestrate") == QUEUE_INGEST
    assert queue_for_stage("sampling") == QUEUE_CPU_DECODE
    assert queue_for_stage("report") == QUEUE_CPU_ANALYSIS
    assert queue_for_stage("aggregate") == QUEUE_INGEST
    assert queue_for_stage("critic") == QUEUE_CRITIC
    assert queues_for_role("cpu") == WORKER_CPU_QUEUES


def test_task_names_keep_gpu_and_critic_off_the_cpu_task() -> None:
    assert task_name_for_stage("orchestrate") == TASK_ORCHESTRATE
    assert task_name_for_stage("spatial") == TASK_GPU_SPATIAL
    assert task_name_for_stage("critic") == TASK_CRITIC
    assert task_name_for_stage("sampling") == TASK_RUN_STAGE
    assert task_name_for_stage("report") == TASK_RUN_STAGE


def test_unknown_stage_and_role_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown stage"):
        queue_for_stage("frames")
    with pytest.raises(ValueError, match="unknown worker role"):
        queues_for_role("tpu")
