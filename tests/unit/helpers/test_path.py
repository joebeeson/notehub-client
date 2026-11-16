import pytest

from notehub_client.helpers import encode_path_segments


@pytest.mark.parametrize(
    ("segments", "expected"),
    [
        pytest.param(("projects", "app:test"), "projects/app:test", id="notehub-identifier"),
        pytest.param(("notes", "daily note.qi"), "notes/daily%20note.qi", id="space"),
        pytest.param(("notes", "daily#note.qi"), "notes/daily%23note.qi", id="reserved-character"),
    ],
)
def test_path_segments_are_encoded_without_escaping_identifier_colons(
    segments: tuple[str, ...], expected: str
) -> None:
    assert encode_path_segments(*segments) == expected


@pytest.mark.parametrize(
    "segment",
    [
        pytest.param("", id="empty"),
        pytest.param(".", id="current-directory"),
        pytest.param("..", id="parent-directory"),
    ],
)
def test_path_segments_reject_ambiguous_segments(segment: str) -> None:
    with pytest.raises(ValueError, match="cannot be dot segments"):
        encode_path_segments("projects", segment)
