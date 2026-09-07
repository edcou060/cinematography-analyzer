"""Original filenames are metadata. They are never a storage key and never an error."""

from pathlib import Path

_MAX_NAME = 512


def sanitize_original_filename(raw: str) -> str:
    """Keep a display name. Drop directories, NULs, and non-printables."""
    name = Path(raw).name
    cleaned_chars: list[str] = []
    for char in name:
        if char.isprintable() and char not in {"/", "\\"}:
            cleaned_chars.append(char)
        else:
            cleaned_chars.append("_")
    cleaned = "".join(cleaned_chars).strip()
    if not cleaned or cleaned in {".", ".."}:
        return "upload"
    return cleaned[:_MAX_NAME]
