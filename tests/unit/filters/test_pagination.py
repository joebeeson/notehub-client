from collections.abc import Callable

import pytest

from notehub_client.filters import CursorPagination, Pagination, cursor, page


@pytest.mark.parametrize(
    "page_size",
    [
        pytest.param(True, id="boolean-is-not-an-integer-page-size"),
        pytest.param(10_001, id="above-maximum"),
    ],
)
def test_page_size_must_be_an_integer_in_the_allowed_range(page_size: int | bool) -> None:
    with pytest.raises(ValueError, match="1 to 10000"):
        Pagination(page_size=page_size)


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        pytest.param(lambda: Pagination(page_num=0), "positive integer", id="page-zero"),
        pytest.param(lambda: Pagination(page_num=True), "positive integer", id="page-boolean"),
        pytest.param(lambda: CursorPagination(cursor=""), "nonempty string", id="empty-cursor"),
        pytest.param(lambda: CursorPagination(page_size=0), "1 to 10000", id="cursor-page-size"),
    ],
)
def test_pagination_values_reject_invalid_options(
    factory: Callable[[], object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_page_and_cursor_factories_include_expected_query_values() -> None:
    assert dict(page(page_size=25, page_num=3)) == {"pageSize": 25, "pageNum": 3}
    assert dict(cursor("next-page", page_size=50)) == {
        "cursor": "next-page",
        "pageSize": 50,
    }
