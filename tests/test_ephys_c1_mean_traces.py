import copy

import numpy as np
import pytest

from openscope_p3_publication.ephys_c1_mean_traces import prepare_positive_q1_means
from openscope_p3_publication.ephys_c1_population import load_c1_population
from openscope_p3_publication.standard_oddball_neuropixels import load_diagnostic


@pytest.fixture(scope="module")
def inputs():
    return load_diagnostic(), load_c1_population()


@pytest.mark.parametrize(
    "change", ["units", "session", "asset", "time", "rates", "baselines", "values", "statistics"],
)
def test_shared_mean_helper_rejects_misaligned_or_nonfinite_inputs(inputs, change):
    data, split = copy.deepcopy(inputs)
    if change == "units":
        split["payload"]["unit_ids"].reverse()
    elif change == "session":
        split["payload"]["session_id"] = "other"
    elif change == "asset":
        split["payload"]["asset"] = {}
    elif change == "time":
        split["time"] = split["time"][:-1]
    elif change == "rates":
        split["rates"] = split["rates"][:, :-1]
    elif change == "baselines":
        split["baselines"] = split["baselines"][:, :-1]
    elif change == "values":
        split["rates"][0, 0, 0] = np.nan
    else:
        data.statistics["q1_p"] = data.statistics["q1_p"][:, :-1]
    with pytest.raises(ValueError, match="Q1 mean-trace"):
        prepare_positive_q1_means(data, split)
