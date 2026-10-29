# Author: Marcel C. Raabe
# Contributors: Lucas Rudelt
# Date: 2026-10-29
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import h5py
import numpy as np
import pandas as pd
import pynwb
import remfile
import requests
from dandi.dandiapi import DandiAPIClient
from tqdm.auto import tqdm

DANDISET_ID = "001637"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_url(asset_id: str) -> str:
    r = requests.get(
        f"https://api.dandiarchive.org/api/assets/{asset_id}/download/",
        allow_redirects=True, stream=True, timeout=30,
    )
    url = r.url
    r.close()
    return url


def _detect_modality(nwb: pynwb.NWBFile) -> str:
    if nwb.units is not None:
        return "ecephys"
    ophys = nwb.processing.get("ophys")
    if ophys and any("DMD" in k for k in ophys.data_interfaces):
        return "slap2"
    if ophys or any(k.startswith("VIS") for k in nwb.processing):
        return "mesoscope"
    return "unknown"


def _require_modality(actual: str, expected: str, method: str) -> None:
    if actual != expected:
        raise RuntimeError(
            f"{method}() requires modality='{expected}', got '{actual}'"
        )


# ---------------------------------------------------------------------------
# NWBStream — unified context-managed handle
# ---------------------------------------------------------------------------

@dataclass
class NWBStream:
    """Lazy streaming handle for a DANDI NWB file. Use as a context manager."""

    nwb:      pynwb.NWBFile
    io:       pynwb.NWBHDF5IO
    _h5:      h5py.File
    modality: Literal["ecephys", "mesoscope", "slap2", "unknown"]
    asset_id: str

    def __enter__(self) -> NWBStream:
        return self

    def __exit__(self, *_) -> None:
        try:
            self.io.close()
        finally:
            self._h5.close()

    # --- Ecephys ---

    def units_df(self, probe: str | None = None, include_spikes: bool = True) -> pd.DataFrame:
        """Units table as a DataFrame, optionally filtered to one probe.

        Avoids pynwb's to_dataframe() which triggers one HTTP request per
        HDF5 chunk for spike_times and per-unit DynamicTableRegion expansion
        for electrodes. Instead, reads both as single bulk h5py reads.

        Adds ``probe`` (``device_name``), ``electrode_row``, and ``location`` — CCF
        acronym at the unit's extremum channel (``extremum_channel_index`` with
        per-probe offset into the stacked electrodes table). Decoded into
        ``area``, ``layer``, ``group``, and ``tissue`` via :mod:`utils.ccf`.

        probe: substring matched against ``device_name``, e.g. 'ProbeB'.
        include_spikes: if False, skip loading spike_times (fast anatomy-only).
        """
        _require_modality(self.modality, "ecephys", "units_df")
        from .ccf import enrich_unit_locations
        from .ecephys_io import unit_electrode_rows

        h5u = self._h5["units"]

        # --- scalar columns (small, one read each) ---
        skip = {"spike_times", "spike_times_index", "electrodes", "electrodes_index",
                "waveform_mean", "waveform_sd", "waveform_mean_index", "waveform_sd_index"}
        data = {}
        for col in self.nwb.units.colnames:
            if col in skip:
                continue
            try:
                raw = h5u[col][:]
                data[col] = raw.tolist() if hasattr(raw, "tolist") else list(raw)
            except KeyError:
                pass
        df = pd.DataFrame(data)

        elec_h5 = self.nwb.electrodes["group_name"].data.parent
        elrows = unit_electrode_rows(self._h5)
        df["electrode_row"] = elrows
        if "device_name" in df.columns:
            df["probe"] = df["device_name"].astype(str)
        else:
            group_names = np.array(elec_h5["group_name"].asstr()[:])
            df["probe"] = group_names[elrows]
        if "location" in elec_h5:
            locations = np.array(elec_h5["location"].asstr()[:])
            df["location"] = locations[elrows]
            df = enrich_unit_locations(df)

        # --- probe filter before loading spike_times ---
        if probe is not None:
            df = df[df["probe"].str.contains(probe, na=False)]

        # preserve original row numbers before reset — used to index spike_bounds
        orig_indices = df.index.tolist()
        df = df.reset_index(drop=True)

        if include_spikes:
            spike_flat   = h5u["spike_times"][:]
            spike_bounds = np.concatenate([[0], h5u["spike_times_index"][:]])
            df["spike_times"] = [
                spike_flat[spike_bounds[i]:spike_bounds[i + 1]]
                for i in orig_indices
            ]

        return df

    # def units_df(self, probe: str | None = None) -> pd.DataFrame:
    #     """Units table as a DataFrame, optionally filtered to one probe.

    #     Avoids pynwb's to_dataframe() which triggers one HTTP request per
    #     HDF5 chunk for spike_times and per-unit DynamicTableRegion expansion
    #     for electrodes. Instead, reads both as single bulk h5py reads.

    #     Adds a 'probe' column (electrode group_name) and, when the electrodes
    #     table has it, a 'location' column — CCF structure acronym with
    #     cortical layer suffix where applicable, e.g. 'VISp5'.

    #     probe: substring matched against electrode group_name, e.g. 'ProbeB'.
    #     """
    #     _require_modality(self.modality, "ecephys", "units_df")
    #     h5u = self._h5["units"]

    #     # --- scalar columns (small, one read each) ---
    #     skip = {"spike_times", "spike_times_index", "electrodes", "electrodes_index",
    #             "waveform_mean", "waveform_sd", "waveform_mean_index", "waveform_sd_index"}
    #     data = {}
    #     for col in self.nwb.units.colnames:
    #         if col in skip:
    #             continue
    #         try:
    #             raw = h5u[col][:]
    #             data[col] = raw.tolist() if hasattr(raw, "tolist") else list(raw)
    #         except KeyError:
    #             pass
    #     df = pd.DataFrame(data)

    #     # --- probe / location columns: one bulk read of the electrodes table ---
    #     # A unit's 'electrodes' region spans its *whole probe's* electrode
    #     # array, not just its own channel, so we must pick out the unit's
    #     # peak channel (extremum_channel_index) rather than the first entry —
    #     # otherwise every unit on a probe collapses onto the same electrode.
    #     elec_h5     = self.nwb.electrodes["group_name"].data.parent
    #     group_names = np.array(elec_h5["group_name"].asstr()[:])
    #     elec_flat   = h5u["electrodes"][:]
    #     elec_starts = np.concatenate([[0], h5u["electrodes_index"][:]])[:-1]
    #     if "extremum_channel_index" in h5u:
    #         peak_offset = h5u["extremum_channel_index"][:]
    #     else:
    #         peak_offset = np.zeros(len(df), dtype=int)
    #     peak_elec = elec_flat[elec_starts + peak_offset]
    #     df["probe"] = group_names[peak_elec]
    #     if "location" in elec_h5:
    #         locations = np.array(elec_h5["location"].asstr()[:])
    #         df["location"] = locations[peak_elec]

    #     # --- probe filter before loading spike_times ---
    #     if probe is not None:
    #         df = df[df["probe"].str.contains(probe, na=False)]

    #     # preserve original row numbers before reset — used to index spike_bounds
    #     orig_indices = df.index.tolist()
    #     df = df.reset_index(drop=True)

    #     # --- spike_times: two bulk reads, reconstruct ragged array ---
    #     spike_flat   = h5u["spike_times"][:]
    #     spike_bounds = np.concatenate([[0], h5u["spike_times_index"][:]])
    #     df["spike_times"] = [
    #         spike_flat[spike_bounds[i]:spike_bounds[i + 1]]
    #         for i in orig_indices
    #     ]

    #     return df

    def probes(self) -> list[str]:
        """Probe names in the order units_df()['probe'].unique() gives, without reading
        spike times."""
        _require_modality(self.modality, "ecephys", "probes")
        h5u = self._h5["units"]
        group_names = np.array(
            self.nwb.electrodes["group_name"].data.parent["group_name"].asstr()[:]
        )
        elec_flat = h5u["electrodes"][:]
        first_elec = np.concatenate([[0], h5u["electrodes_index"][:-1]])
        return list(pd.unique(group_names[elec_flat[first_elec]]))

    def mesoscope_plane_areas(self) -> pd.DataFrame:
        """One row per imaging plane: area and depth from optophysiology.location."""
        _require_modality(self.modality, "mesoscope", "mesoscope_plane_areas")
        from .ccf import parse_mesoscope_location

        rows = []
        opto = self._h5.get("general/optophysiology")
        for plane in self.imaging_planes():
            loc = ""
            if opto is not None and plane in opto and "location" in opto[plane]:
                raw = opto[plane]["location"][()]
                loc = raw.decode() if isinstance(raw, bytes) else str(raw)
            parsed = parse_mesoscope_location(loc, plane_fallback=plane)
            rows.append(dict(plane=plane, area=parsed["area"], depth_um=parsed["depth_um"],
                             location=loc))
        return pd.DataFrame(rows)

    def zebra_df(self) -> pd.DataFrame:
        """Zebra noise stimulus presentation table (start_time, stop_time, ...).

        SLAP2 sessions list the Zebra movie as a block inside the 'movie'
        table — one row per repeat rather than one row per frame; see
        zebra_frame_times() for reconstructed per-frame onsets.
        """
        # _require_modality(self.modality, "ecephys", "zebra_df")
        if self.modality == "slap2":
            movie = self.nwb.intervals["movie"].to_dataframe()
            return movie[movie["BlockLabel"] == "Zebra"].reset_index(drop=True)
        return self.nwb.intervals["Zebra_presentations"].to_dataframe()

    def gabor_rf_df(self) -> pd.DataFrame:
        """Gabor RF mapping stimulus table (X, Y, Orientation, start_time, ...)."""
        _require_modality(self.modality, "ecephys", "gabor_rf_df")
        return self.nwb.intervals["RF mapping_presentations"].to_dataframe()

    # --- Mesoscope ---

    def imaging_planes(self) -> list[str]:
        """Names of processing groups that represent imaging planes (e.g. VISp_0)."""
        _require_modality(self.modality, "mesoscope", "imaging_planes")
        return [k for k in self.nwb.processing if k.startswith("VIS")]

    def dff_df(self, plane: str) -> pd.DataFrame:
        """ΔF/F traces for a given imaging plane.

        Returns a DataFrame with shape (n_rois, n_timepoints).
        plane: one of the names returned by imaging_planes().
        """
        _require_modality(self.modality, "mesoscope", "dff_df")
        module = self.nwb.processing[plane]
        dff_ts = module["dff_timeseries"]["dff_timeseries"]
        return pd.DataFrame(
            dff_ts.data[:].T,
            columns=dff_ts.timestamps[:],
        )

    def events_df(self, plane: str) -> pd.DataFrame:
        """OASIS-deconvolved events for a given imaging plane.

        Same layout, ROI order and timestamps as dff_df(plane). The NWB events
        are the output of aind-ophys-oasis-event-detection with its default
        (auto-estimated) parameters, so no deconvolution is needed here.
        """
        _require_modality(self.modality, "mesoscope", "events_df")
        events_ts = self.nwb.processing[plane]["event_timeseries"]
        return pd.DataFrame(
            events_ts.data[:].T,
            columns=events_ts.timestamps[:],
        )

    # --- SLAP2 ---

    def dmds(self) -> list[str]:
        """Names of the DMD imaging planes present, e.g. ['DMD1', 'DMD2']."""
        _require_modality(self.modality, "slap2", "dmds")
        ophys = self.nwb.processing["ophys"]
        return sorted(
            k.replace("Fluorescence_", "")
            for k in ophys.data_interfaces
            if k.startswith("Fluorescence_")
        )

    def _slap2_series(
        self,
        kind: str,
        dmd: str,
        channel: str,
        t_start: float | None,
        t_stop: float | None,
    ) -> pd.DataFrame:
        _require_modality(self.modality, "slap2", f"slap2_{kind.lower()}")
        rrs = self.nwb.processing["ophys"][f"Fluorescence_{dmd}"][f"{dmd}_{kind}_{channel}"]

        times = rrs.timestamps[:]
        i0 = 0 if t_start is None else int(np.searchsorted(times, t_start))
        i1 = len(times) if t_stop is None else int(np.searchsorted(times, t_stop))

        # stored as (n_timepoints, n_rois); transposed to match dff_df()
        return pd.DataFrame(rrs.data[i0:i1, :].T, columns=times[i0:i1])

    def slap2_dff(
        self,
        dmd: str = "DMD1",
        channel: str = "green",
        t_start: float | None = None,
        t_stop: float | None = None,
    ) -> pd.DataFrame:
        """ΔF/F traces for one DMD, shape (n_rois, n_timepoints).

        Columns are timestamps in seconds — same layout as dff_df().
        channel: 'green' (iGluSnFR4f) or 'red' (RCaMP3).
        t_start / t_stop: restrict to a time window (seconds) so that only that
        slice is read from disk; the full traces are several hundred MB.
        """
        return self._slap2_series("dFF", dmd, channel, t_start, t_stop)

    def slap2_f0(
        self,
        dmd: str = "DMD1",
        channel: str = "green",
        t_start: float | None = None,
        t_stop: float | None = None,
    ) -> pd.DataFrame:
        """Raw F0 fluorescence traces for one DMD. Same layout as slap2_dff()."""
        return self._slap2_series("F0", dmd, channel, t_start, t_stop)

    def slap2_rois(self, dmd: str = "DMD1") -> pd.DataFrame:
        """ROI table for one DMD: id, pixel count, centroid, z range, pixel mask.

        Row order matches the row order of slap2_dff() / slap2_f0().
        Centroids are weighted by the pixel mask weights, in image pixels.
        """
        _require_modality(self.modality, "slap2", "slap2_rois")
        ps = self.nwb.processing["ophys"]["ImageSegmentation"][f"PlaneSegmentation_{dmd}"]

        rows = []
        for i, roi_id in enumerate(ps.id[:]):
            mask = np.asarray(ps["pixel_mask"][i])
            x, y, w = mask["x"], mask["y"], mask["weight"]
            wsum = w.sum()
            rows.append({
                "roi_id":     roi_id,
                "n_pixels":   len(mask),
                "x":          float((x * w).sum() / wsum) if wsum else float(x.mean()),
                "y":          float((y * w).sum() / wsum) if wsum else float(y.mean()),
                "z_min":      int(ps["z_min"][i]),
                "z_max":      int(ps["z_max"][i]),
                "pixel_mask": mask,
            })
        return pd.DataFrame(rows)

    def slap2_roi_labels(self, dmd: str = "DMD1") -> np.ndarray:
        """Label image (n_y, n_x) holding row-index + 1 inside each ROI, 0 outside.

        Shaped to match slap2_mean_image(); overlapping ROIs keep the later row.
        """
        rois   = self.slap2_rois(dmd)
        labels = np.zeros(self.slap2_mean_image(dmd).shape, dtype=int)
        for i, mask in enumerate(rois["pixel_mask"]):
            labels[mask["y"].astype(int), mask["x"].astype(int)] = i + 1
        return labels

    def slap2_mean_image(self, dmd: str = "DMD1", channel: int = 0) -> np.ndarray:
        """Mean image (n_y, n_x) for one DMD. channel: 0 (green) or 1 (red)."""
        _require_modality(self.modality, "slap2", "slap2_mean_image")
        img = self.nwb.processing["ophys"][f"{dmd}_mean_image_channel{channel}"]
        return np.asarray(img.data[0])

    def slap2_activity_image(self, dmd: str = "DMD1") -> np.ndarray:
        """Activity image (n_y, n_x) for one DMD."""
        _require_modality(self.modality, "slap2", "slap2_activity_image")
        img = self.nwb.processing["ophys"][f"{dmd}_activity_image"]
        return np.asarray(img.data[0]).squeeze()

    def slap2_segments(self, dmd: str = "DMD1", channel: str = "green") -> pd.DataFrame:
        """Continuous acquisition segments, inferred from gaps in the timestamps.

        SLAP2 does not image continuously: it records in bouts of ~30 s with a
        short blanking period in between. Returns one row per bout with its
        start/stop time, sample count, and index range into slap2_dff().
        """
        _require_modality(self.modality, "slap2", "slap2_segments")
        rrs = self.nwb.processing["ophys"][f"Fluorescence_{dmd}"][f"{dmd}_dFF_{channel}"]

        times = rrs.timestamps[:]
        dt    = np.diff(times)
        gaps  = np.where(dt > 5 * np.median(dt))[0]

        starts = np.concatenate([[0], gaps + 1])
        stops  = np.concatenate([gaps, [len(times) - 1]])
        return pd.DataFrame({
            "start_time": times[starts],
            "stop_time":  times[stops],
            "duration":   times[stops] - times[starts],
            "n_samples":  stops - starts + 1,
            "i_start":    starts,
            "i_stop":     stops,
        })

    # --- Stimulus tables (all modalities) ---

    def stim_tables(self) -> list[str]:
        """Names of the stimulus interval tables in this session."""
        return list(self.nwb.intervals)

    def stim_df(self, name: str) -> pd.DataFrame:
        """One stimulus interval table as a DataFrame."""
        return self.nwb.intervals[name].to_dataframe()

    def zebra_frame_times(self, fps: float = 30.0) -> pd.DataFrame:
        """Per-frame onset times of the Zebra movie, one row per frame.

        The SLAP2 NWB stores the Zebra movie as a single interval per repeat
        instead of one row per frame, so frame onsets are reconstructed by
        assuming a constant `fps` within each block. Columns: TrialNumber,
        frame, start_time, stop_time.

        SLAP2 only: the ecephys and mesoscope zebra_df() already has one row per
        frame, which this would turn into frame 0 for every row.
        """
        _require_modality(self.modality, "slap2", "zebra_frame_times")
        blocks = self.zebra_df()
        out = []
        for _, b in blocks.iterrows():
            n = int(round((b["stop_time"] - b["start_time"]) * fps))
            frames = np.arange(n)
            out.append(pd.DataFrame({
                "TrialNumber": b["TrialNumber"],
                "frame":       frames,
                "start_time":  b["start_time"] + frames / fps,
                "stop_time":   b["start_time"] + (frames + 1) / fps,
            }))
        return pd.concat(out, ignore_index=True)

    # --- Behaviour (all modalities) ---

    def running_df(self) -> pd.DataFrame:
        """Running speed (cm/s) against time, as a two-column DataFrame."""
        ts = self.nwb.processing["running"]["running_speed"]
        return pd.DataFrame({"time": ts.timestamps[:], "speed": ts.data[:]})

    def pupil_df(self) -> pd.DataFrame:
        """Pupil tracking table (position, width, height, area) against time.

        A boolean 'blink' column is joined in from likely_blink_times when the
        session has one. Beware the two different missing-data conventions:
        'area' marks unfitted frames with -1, every other column uses NaN — so
        mask on 'blink' rather than trusting 'area'.
        """
        eye = self.nwb.processing["eye_tracking"]
        df  = eye["pupil"].to_dataframe()
        if "likely_blink_times" in eye.data_interfaces:
            df["blink"] = np.asarray(eye["likely_blink_times"].data[:], dtype=bool)
        return df


# ---------------------------------------------------------------------------
# DandiSession — asset discovery and opening
# ---------------------------------------------------------------------------

class DandiSession:
    """Lists and opens NWB assets from a DANDI dandiset."""

    def __init__(self, dandiset_id: str = DANDISET_ID) -> None:
        self._dandiset_id = dandiset_id
        client = DandiAPIClient()
        self._ds = client.get_dandiset(dandiset_id)

    def assets(self):
        """All assets sorted by path. Each entry has .identifier, .path, .size."""
        return sorted(self._ds.get_assets(), key=lambda a: a.path)

    def open(self, asset_id: str) -> NWBStream:
        """Resolve DANDI redirect → remfile → h5py → pynwb → NWBStream."""
        url = _resolve_url(asset_id)
        h5  = h5py.File(remfile.File(url), "r")
        io  = pynwb.NWBHDF5IO(file=h5, load_namespaces=True, mode="r")
        nwb = io.read()
        return NWBStream(
            nwb=nwb,
            io=io,
            _h5=h5,
            modality=_detect_modality(nwb),
            asset_id=asset_id,
        )

    def open_path(self, asset_path: str) -> NWBStream:
        """Stream an asset by its path in the dandiset.

        For example 'sub-830794/sub-830794_ses-..._ecephys.nwb'.
        """
        return self.open(self._ds.get_asset_by_path(asset_path).identifier)

    def download(self, asset_id: str, dest: str | Path) -> Path:
        """Download a DANDI asset to a local file via the DANDI API. Returns the saved path."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        asset = self._ds.get_asset(asset_id)
        downloader = asset.get_download_file_iter()
        with dest.open("wb") as f, tqdm(
            total=asset.size, unit="B", unit_scale=True, unit_divisor=1024,
            desc=dest.name,
        ) as bar:
            for chunk in downloader(0):
                f.write(chunk)
                bar.update(len(chunk))
        return dest


# ---------------------------------------------------------------------------
# Public shortcut
# ---------------------------------------------------------------------------

def open_nwb(asset_id: str, dandiset_id: str = DANDISET_ID) -> NWBStream:
    """Stream a DANDI NWB file by asset ID without downloading it."""
    return DandiSession(dandiset_id).open(asset_id)


def open_session(nwb_path: str | Path, dandiset_id: str | None = None) -> NWBStream:
    """Stream nwb_path as an asset path from dandiset_id.

    Opens it from disk instead when dandiset_id is None.
    """
    if dandiset_id is None:
        return open_local(nwb_path)
    return DandiSession(dandiset_id).open_path(str(nwb_path))


def open_local(path: str | Path, asset_id: str = "") -> NWBStream:
    """Open a locally saved NWB file as an NWBStream.

    Identical interface to open_nwb() — all NWBStream methods work the same.
    asset_id is optional metadata; leave blank if the file wasn't from DANDI.
    """
    h5  = h5py.File(Path(path), "r")
    io  = pynwb.NWBHDF5IO(file=h5, load_namespaces=True, mode="r")
    nwb = io.read()
    return NWBStream(
        nwb=nwb,
        io=io,
        _h5=h5,
        modality=_detect_modality(nwb),
        asset_id=asset_id,
    )
