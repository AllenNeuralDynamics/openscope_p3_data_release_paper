import numpy as np

from openscope_p3_publication.mesoscope_standard_oddball_cohort import (
    native_window_statistics,
)


def test_native_window_provenance_keeps_slice_summary_and_digest():
    timestamps = np.arange(12) * 0.1
    _, provenance = native_window_statistics(
        timestamps,
        lambda start, stop: np.ones((stop - start, 1)),
        1,
        {"response": [[0.2, 0.4], [0.8, 1.0]]},
    )

    assert provenance["frame_slice_count"] == 2
    assert provenance["frame_slice_span"] == [1, 11]
    assert provenance["frame_count_read"] == 8
    assert len(provenance["values_and_slices_sha256"]) == 64
    assert "frame_slices" not in provenance
