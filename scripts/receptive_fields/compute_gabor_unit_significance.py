# Authors: Lucas Rudelt, Marcel C. Raabe
# Date: 2026-10-29
"""Unit-level Gabor p-values after the full search, then BH across the family.

Each unit gets one Gumbel p-value: 1000 presentation shuffles, the map
statistic studentized in every delay x duration x orientation the optimized
file was searched over (its ``sweep_delays`` / ``sweep_durations``), and the
maximum of those studentized values (`gabor_significance`). Responses use
the driver's window rule, so the null is taken over exactly the tested windows.
Benjamini–Hochberg q-values are then computed once per family and written beside
the existing per-orientation counting ``p_value`` of the pooled optimized files:

* ``p_value_gumbel`` — uncorrected unit-level p-value
* ``p_value_bh`` — BH q-value

The families are those of the Zebra significance (`filter_significant_maps.py`):
all probes of the ecephys session, all planes of the mesoscope session, and each
SLAP2 DMD x channel on its own. Only the pooled optimized files are scored;
per-trial halves are left unchanged. Files are read from
``<results-dir>/<modality>/<session>/<signal>/``, the layout of the Zebra results:
``spikes`` for ecephys, the ``events`` results for the imaging modalities. Files
are updated atomically.

Sessions are streamed from DANDI. Saved Gumbel p-values are reused unless
--recompute; BH is always redone over the whole family.

    python compute_gabor_unit_significance.py [--modality ecephys mesoscope slap2]
                                              [--results-dir ../results/gabors] [--recompute]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import h5py
import numpy as np

sys.path.append(str(Path(__file__).resolve().parent))

import gabor_significance as gabor
import rf_gabors

# Reduced Gabor results as tracked in the repository:
# gabors/<ecephys|mesoscope|slap2>/<session>/<spikes|events>/
RESULTS = Path(__file__).resolve().parents[1] / "results" / "gabors"
N_SHUFFLE = gabor.N_SHUFFLE
Q_LEVEL = 0.05


def _names(path: Path) -> list[str]:
    with h5py.File(path, "r") as hf:
        return [gabor._text(value) for value in hf["unit_names"][:]]


def _read_vector(path: Path, name: str, n_units: int):
    with h5py.File(path, "r") as hf:
        if name not in hf or hf[name].shape != (n_units,):
            return None
        return np.asarray(hf[name][:], dtype=float)


def _write_vector(path: Path, name: str, values: np.ndarray, **attrs) -> None:
    values = np.asarray(values, dtype=np.float64)
    with rf_gabors.atomic_h5_update(path) as hf:
        if name in hf:
            del hf[name]
        hf.create_dataset(name, data=values)
        for key, value in attrs.items():
            hf.attrs[key] = value


def gumbel_p_values(responses, df_rf, batch: int = 64) -> np.ndarray:
    """Gumbel p-value per unit. Units are scored in batches so the shuffle fits."""
    x_pos, y_pos, orientations = rf_gabors.rf_grid(df_rf)
    parts = []
    for start in range(0, responses.shape[0], batch):
        result = gabor.joint_null(
            responses[start:start + batch], df_rf, x_pos, y_pos, orientations,
            N_SHUFFLE, seed=0,
        )
        parts.append(np.asarray(result["gumbel_p"], dtype=float))
    p_values = np.concatenate(parts)
    return np.where(np.isfinite(p_values), p_values, 1.0)


def _pooled_files(directory: Path) -> list[Path]:
    """Pooled optimized files; per-trial halves and set-aside copies are left out."""
    if not directory.is_dir():
        raise FileNotFoundError(f"No Gabor results at {directory}")
    return [
        path for path in sorted(directory.glob("*__optimized.h5"))
        if "__trial_" not in path.name and "legacy" not in path.parent.name
    ]


def _grid(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """The delay x duration grid an optimized file was reduced over."""
    with h5py.File(path, "r") as hf:
        if "sweep_delays" not in hf.attrs or "sweep_durations" not in hf.attrs:
            raise ValueError(
                f"{path.name} does not record its delay x duration grid; it was computed "
                "before the Gabor grids matched the Zebra ones. Recompute it with the driver."
            )
        return (np.asarray(hf.attrs["sweep_delays"], dtype=float),
                np.asarray(hf.attrs["sweep_durations"], dtype=float))


def _group(path: Path) -> str:
    """Probe, plane or DMD: the part of the file name before ``optimized``."""
    return path.stem.split("__")[-2]


def _align(saved_names, available: dict[str, int]) -> np.ndarray:
    missing = [name for name in saved_names if name not in available]
    if missing:
        raise RuntimeError(
            f"{len(missing)} saved units are absent from the recording, "
            f"for example {missing[:3]}. The results were computed on another "
            "release of the NWB file; recompute them with the Gabor driver."
        )
    return np.asarray([available[name] for name in saved_names], dtype=int)


def _pending(files, recompute):
    out = []
    for path in files:
        names = _names(path)
        cached = None if recompute else _read_vector(path, "p_value_gumbel", len(names))
        out.append((path, names, cached))
    return out


def _score(path, names, responses, df_rf):
    started = time.perf_counter()
    p_values = gumbel_p_values(responses, df_rf)
    elapsed = time.perf_counter() - started
    _write_vector(path, "p_value_gumbel", p_values, p_value_gumbel_n_shuffle=N_SHUFFLE)
    print(f"  {_group(path)}: {len(names)} units in {elapsed:.1f} s "
          f"({elapsed / max(len(names), 1):.3f} s/unit)", flush=True)
    return p_values


def compute_ecephys(results: Path, recompute: bool) -> None:
    dandiset, asset = gabor.EPHYS_ASSET
    pending = _pending(_pooled_files(results / "ecephys" / Path(asset).stem / "spikes"), recompute)
    if all(cached is not None for _, _, cached in pending):
        print("ecephys: using saved Gumbel p-values", flush=True)
        _write_bh("ecephys", pending)
        return

    stream, _ = gabor.open_stream(dandiset, asset)
    with stream:
        # Spike times once; each probe is then scored alone.
        units = stream.units_df(include_spikes=False)
        units["unit_name"] = units["unit_name"].map(gabor._text)
        row_of = {name: int(row) for row, name in enumerate(units["unit_name"])}
        bounds = np.concatenate([[0], np.asarray(
            stream._h5["units"]["spike_times_index"][:], dtype=np.int64
        )])
        flat = np.asarray(stream._h5["units"]["spike_times"][:], dtype=float)
        df_rf = stream.gabor_rf_df()
    scored = []
    for path, names, cached in pending:
        if cached is None:
            rows = _align(names, row_of)
            spikes = [flat[int(bounds[row]):int(bounds[row + 1])] for row in rows]
            responses, _ = gabor.spike_responses(spikes, df_rf, *_grid(path))
            cached = _score(path, names, responses, df_rf)
        scored.append((path, names, cached))
    _write_bh("ecephys", scored)


def compute_mesoscope(results: Path, recompute: bool) -> None:
    dandiset, asset = gabor.MESO_ASSET
    events_dir = results / "mesoscope" / Path(asset).stem / "events"
    pending = _pending(_pooled_files(events_dir), recompute)
    if all(cached is not None for _, _, cached in pending):
        print("mesoscope: using saved Gumbel p-values", flush=True)
        _write_bh("mesoscope", pending)
        return

    stream, _ = gabor.open_stream(dandiset, asset)
    scored = []
    with stream:
        df_rf = stream.stim_df(gabor.meso_gabors.STIM_TABLE)
        for path, names, cached in pending:
            if cached is None:
                plane = _group(path)
                delays, durations = _grid(path)
                print(f"  loading {plane}", flush=True)
                traces, times, available = gabor.meso_gabors.load_traces(stream, plane, "events")
                margin = float(delays.max() + durations.max() + 1.0)
                traces, times = rf_gabors.slice_to_stimulus(traces, times, df_rf, margin)
                rows = _align(names, {name: i for i, name in enumerate(available)})
                responses, _ = gabor.trace_responses(
                    traces[rows], times, df_rf, delays, durations,
                    gabor.meso_gabors.WINDOW_MEANS,
                )
                cached = _score(path, names, responses, df_rf)
            scored.append((path, names, cached))
    _write_bh("mesoscope", scored)


def compute_slap2(results: Path, recompute: bool) -> None:
    dandiset, asset = gabor.SLAP2_ASSET
    files = _pooled_files(results / "slap2" / Path(asset).stem / "events")
    pending = _pending(files, recompute)
    stream = None
    df_rf = None
    try:
        # Each DMD x channel is its own family: green (iGluSnFR4f) and red (RCaMP3)
        # are different indicators, and each DMD is tested on its own.
        for path, names, cached in pending:
            channel = "green" if "rf-events-green" in path.name else "red"
            dmd = _group(path)
            if cached is None:
                if stream is None:
                    stream, _ = gabor.open_stream(dandiset, asset)
                    df_rf = stream.stim_df(gabor.slap2_gabors.STIM_TABLE)
                delays, durations = _grid(path)
                margin = float(delays.max() + durations.max() + 1.0)
                print(f"  loading {dmd} {channel}", flush=True)
                traces, times, available = gabor.slap2_gabors.load_traces(
                    stream, dmd, channel,
                    t_start=float(df_rf["start_time"].min() - margin),
                    t_stop=float(df_rf["stop_time"].max() + margin),
                    signal="events", nwb_path=asset,
                )
                rows = _align(names, {name: i for i, name in enumerate(available)})
                responses, _ = gabor.trace_responses(
                    traces[rows], times, df_rf, delays, durations,
                    gabor.slap2_gabors.WINDOW_MEANS,
                )
                cached = _score(path, names, responses, df_rf)
            _write_bh(f"slap2 {dmd} {channel}", [(path, names, cached)])
    finally:
        if stream is not None:
            stream.__exit__(None, None, None)


def _write_bh(family: str, scored) -> None:
    p_values = np.concatenate([p for _, _, p in scored])
    q_values = gabor.bh_fdr(p_values)
    print(
        f"{family}: BH q ≤ {Q_LEVEL} for {(q_values <= Q_LEVEL).sum()} / {len(q_values)} units",
        flush=True,
    )
    cursor = 0
    for path, names, _ in scored:
        q_group = q_values[cursor:cursor + len(names)]
        cursor += len(names)
        _write_vector(
            path, "p_value_bh", q_group,
            p_value_bh_family=family,
            p_value_bh_n_units=int(len(q_values)),
            p_value_bh_q_level=Q_LEVEL,
        )


MODALITIES = {
    "ecephys": compute_ecephys,
    "mesoscope": compute_mesoscope,
    "slap2": compute_slap2,
}


def main(modalities=tuple(MODALITIES), results=RESULTS, recompute: bool = False) -> None:
    for modality in modalities:
        print(f"\n=== {modality} ===", flush=True)
        MODALITIES[modality](Path(results), recompute)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--modality", nargs="+", choices=list(MODALITIES), default=list(MODALITIES))
    parser.add_argument("--results-dir", default=str(RESULTS),
                        help=f"Root of the reduced Gabor results (default {RESULTS})")
    parser.add_argument("--recompute", action="store_true",
                        help="Recompute Gumbel p-values that are already saved")
    args = parser.parse_args()
    main(args.modality, args.results_dir, args.recompute)
