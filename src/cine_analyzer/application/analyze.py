"""Create or reuse an analysis identity. No pipeline stages run here."""

from dataclasses import dataclass
from uuid import uuid4

from cine_analyzer.application.errors import AdapterError, wrap_adapter
from cine_analyzer.application.identity import make_analysis_key
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.logging_setup import bind_context, get_logger
from cine_analyzer.ports.ingestion import AnalysisRecord, AnalysisRepository, VideoRecord

__all__ = ["CreateAnalysis", "CreateAnalysisResult"]


@dataclass(frozen=True, slots=True)
class CreateAnalysisResult:
    """Outcome of analysis-identity creation."""

    analysis: AnalysisRecord
    reused: bool
    configuration_hash: str


class CreateAnalysis:
    """Persist or reuse the key ``sha256(video + canonical config + pipeline version)``."""

    def __init__(self, repository: AnalysisRepository) -> None:
        self._repository = repository

    def execute(
        self,
        *,
        video: VideoRecord,
        config: AnalysisConfig,
        request_id: str,
    ) -> CreateAnalysisResult:
        """Insert a QUEUED analysis or return the existing row for the same identity."""
        with bind_context(
            request_id=request_id,
            video_id=str(video.metadata.video_id),
            stage="analyze",
        ):
            try:
                result = self._execute(video=video, config=config)
            except AdapterError as error:
                raise wrap_adapter(error, request_id=request_id, stage="analyze") from error
            get_logger(__name__).info(
                "analyze.identity.completed",
                analysis_id=str(result.analysis.analysis_id),
                reused=result.reused,
            )
            return result

    def _execute(
        self,
        *,
        video: VideoRecord,
        config: AnalysisConfig,
    ) -> CreateAnalysisResult:
        configuration_hash = config.hash()
        analysis_key = make_analysis_key(
            video_sha256=video.metadata.content_sha256,
            config=config,
        )
        existing = self._repository.get_analysis_by_key(analysis_key)
        if existing is not None:
            return CreateAnalysisResult(
                analysis=existing,
                reused=True,
                configuration_hash=configuration_hash,
            )
        record = AnalysisRecord(
            analysis_id=uuid4(),
            video_id=video.metadata.video_id,
            configuration_hash=configuration_hash,
            pipeline_version=config.pipeline_version,
            analysis_key=analysis_key,
            state=AnalysisState.QUEUED,
        )
        stored = self._repository.insert_analysis(record)
        reused = stored.analysis_id != record.analysis_id
        return CreateAnalysisResult(
            analysis=stored,
            reused=reused,
            configuration_hash=configuration_hash,
        )
