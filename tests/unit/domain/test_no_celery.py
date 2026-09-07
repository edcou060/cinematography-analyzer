"""Domain packages must not import Celery (ADR-0002)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "src" / "cine_analyzer" / "domain"


def test_domain_modules_do_not_import_celery_or_redis() -> None:
    offenders: list[str] = []
    for path in ROOT.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import celery" in text or "from celery" in text:
            offenders.append(f"{path.name}:celery")
        if "import redis" in text or "from redis" in text:
            offenders.append(f"{path.name}:redis")
    assert offenders == []
