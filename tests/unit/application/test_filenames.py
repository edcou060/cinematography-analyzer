"""Original filenames are metadata, never a storage key or error message."""

from cine_analyzer.application.filenames import sanitize_original_filename


def test_directories_are_stripped_to_the_final_component() -> None:
    assert sanitize_original_filename("/etc/passwd") == "passwd"
    assert sanitize_original_filename("nested/clip.mp4") == "clip.mp4"


def test_non_printables_and_slashes_are_replaced() -> None:
    assert sanitize_original_filename("a\x00b\\c.mp4") == "a_b_c.mp4"


def test_empty_or_dot_names_become_a_stable_placeholder() -> None:
    assert sanitize_original_filename("") == "upload"
    assert sanitize_original_filename(".") == "upload"
    assert sanitize_original_filename("..") == "upload"
    assert sanitize_original_filename("   ") == "upload"


def test_a_long_name_is_truncated() -> None:
    raw = "x" * 600 + ".mp4"
    cleaned = sanitize_original_filename(raw)
    assert len(cleaned) == 512
