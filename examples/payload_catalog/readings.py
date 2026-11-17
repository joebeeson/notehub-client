"""Run locally with: uv run --extra validate examples/payload_catalog/readings.py."""

from dataclasses import dataclass
from pathlib import Path

from notehub_client.catalog import load
from notehub_client.catalog.validation import validate_sample
from notehub_client.payloads import PayloadDecoder
from notehub_client.typing import Event


@dataclass(frozen=True)
class ReadingV1:
    """The original wire representation."""

    fahrenheit: float


@dataclass(frozen=True)
class Reading:
    """The application's stable domain representation."""

    celsius: float


def upgrade_v1(source: ReadingV1) -> Reading:
    """Convert legacy units explicitly."""
    return Reading((source.fahrenheit - 32) * 5 / 9)


def main() -> None:
    """Load artifacts, decode historical data, and independently validate a sample."""
    catalog = load(Path(__file__).with_name("catalog.toml"))
    decoder = PayloadDecoder(
        catalog=catalog,
        bindings={"reading.v1": ReadingV1, "reading.v2": Reading},
        upgrades={(("reading", "1"), Reading): upgrade_v1},
    )
    event: Event = {
        "product": "product:example",
        "file": "readings.qo",
        "body": {"schema_version": 1, "fahrenheit": 68},
    }
    decoded = decoder.decode(event, as_type=Reading)
    print(decoded.body)
    print(validate_sample(decoded.contract, event["body"]))


if __name__ == "__main__":
    main()
