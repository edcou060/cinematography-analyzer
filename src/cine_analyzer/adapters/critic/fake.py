"""Deterministic fake critic for CI. Uses only CriticInput fields."""

from cine_analyzer.domain.critic import CriticInput, CriticOutput

__all__ = ["FAKE_CRITIC_IDENTITY", "FakeCritic"]

FAKE_CRITIC_IDENTITY = "fake:deterministic-v1"


class FakeCritic:
    """One to three cautious sentences. No director, genre, story, or quality claims."""

    def identity(self) -> str:
        return FAKE_CRITIC_IDENTITY

    def complete(self, prompt: str, payload: CriticInput, *, timeout_ms: int) -> str:
        del prompt, timeout_ms
        sentences: list[str] = [
            (
                f"The clip has {payload.editing.shot_count} detected shots "
                f"with mean length {payload.editing.asl_seconds} s "
                f"and median {payload.editing.median_seconds} s."
            )
        ]
        if payload.palette:
            joined = ", ".join(payload.palette)
            sentences.append(f"Duration-weighted palette colours include {joined}.")
        if payload.tension_proxy.peak_seconds and len(sentences) < 3:
            peaks = ", ".join(str(item) for item in payload.tension_proxy.peak_seconds)
            audio = (
                "Audio features are present."
                if payload.tension_proxy.audio_available
                else "Audio features are not present."
            )
            sentences.append(f"Tension-proxy peaks occur at {peaks} s. {audio}")
        if len(sentences) < 3:
            thirds = payload.composition.median_thirds_proximity
            if thirds is not None:
                sentences.append(
                    "Median thirds proximity among spatial-valid shots is "
                    f"{thirds} (geometric, not composition quality). "
                    f"Spatial valid ratio {payload.composition.valid_shot_ratio}."
                )
            else:
                sentences.append(
                    "Low-key estimate coverage is "
                    f"{payload.lighting.low_key_ratio} among chromatic-valid shots "
                    f"(valid ratio {payload.lighting.valid_shot_ratio})."
                )
        output = CriticOutput(sentences=tuple(sentences[:3]))
        return output.model_dump_json()
