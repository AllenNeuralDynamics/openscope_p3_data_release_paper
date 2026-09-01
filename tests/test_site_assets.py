from __future__ import annotations

from pathlib import Path

from openscope_p3_publication.neural_response_figure import (
    SOURCE_MEDIA_DIR,
    copy_neuropixels_event_media,
    load_neuropixels_event_responses,
)


def test_publication_assets_are_staged_from_canonical_media(tmp_path: Path) -> None:
    stale_path = tmp_path / "stale.u16.gz"
    stale_path.write_bytes(b"stale")

    outputs = copy_neuropixels_event_media(
        load_neuropixels_event_responses(),
        tmp_path,
    )

    assert {output.name for output in outputs} == {
        path.name for path in SOURCE_MEDIA_DIR.glob("*.u16.gz")
    }
    assert all(
        output.read_bytes() == (SOURCE_MEDIA_DIR / output.name).read_bytes()
        for output in outputs
    )
    assert not stale_path.exists()