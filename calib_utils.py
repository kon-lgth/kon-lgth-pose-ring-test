"""
calib_utils.py
==============
Shared helpers for auto-discovering the latest calibration session.

Usage in any script
-------------------
from calib_utils import find_latest_npz, find_latest_session_dir

# Auto-find the latest B-set .npz (override by setting CALIB_FILE = "path/to/file.npz")
calib_file = find_latest_npz(prefix="calib_B_")

# Auto-find the latest B-set IMAGE folder (for stereo_calibrate_B.py)
session_dir = find_latest_session_dir(prefix="calib_B_")

Prefix conventions
------------------
  "calib_B_"  →  B-set  (capture_calibration_pairs_B.py output)
  "calib_A_"  →  A-set  (if capture script uses that prefix)
  "calib_"    →  any session (A, B, or un-prefixed)
"""

import glob
import os


_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration_images")


def find_latest_npz(prefix: str = "calib_", base_dir: str = _BASE) -> str:
    """
    Return the path to the most recent stereo_calibration_result.npz whose
    parent folder name starts with *prefix*.

    Raises FileNotFoundError if nothing is found.
    """
    pattern = os.path.join(base_dir, f"{prefix}*", "stereo_calibration_result.npz")
    matches = sorted(glob.glob(pattern))   # lexicographic = chronological (YYYYMMDD_HHMMSS)
    if not matches:
        raise FileNotFoundError(
            f"No calibration .npz found matching:\n  {pattern}\n"
            "Run the capture + calibrate scripts first."
        )
    chosen = matches[-1]
    print(f"[calib_utils] Auto-selected calibration: {chosen}")
    return chosen


def find_latest_session_dir(prefix: str = "calib_B_", base_dir: str = _BASE) -> str:
    """
    Return the path to the most recent calibration IMAGE folder whose name
    starts with *prefix* AND contains cam0/ and cam1/ sub-directories.

    Used by stereo_calibrate_B.py which needs the raw image pairs, not the .npz.

    Raises FileNotFoundError if nothing is found.
    """
    pattern = os.path.join(base_dir, f"{prefix}*")
    candidates = sorted(glob.glob(pattern))
    valid = [
        d for d in candidates
        if os.path.isdir(os.path.join(d, "cam0"))
        and os.path.isdir(os.path.join(d, "cam1"))
    ]
    if not valid:
        raise FileNotFoundError(
            f"No image-pair folder found matching:\n  {pattern}\n"
            "Run the capture script first."
        )
    chosen = valid[-1]
    print(f"[calib_utils] Auto-selected session dir: {chosen}")
    return chosen


def resolve_npz(override: str, prefix: str = "calib_") -> str:
    """
    Return *override* if it is a non-empty path that exists,
    otherwise fall back to find_latest_npz(prefix).

    Typical use at the top of a game/calibration script:
        CALIB_FILE = ""           # leave empty for auto-discovery
        calib_file = resolve_npz(CALIB_FILE, prefix="calib_B_")
    """
    if override and os.path.isfile(override):
        print(f"[calib_utils] Using manually specified calibration: {override}")
        return override
    return find_latest_npz(prefix)


def resolve_session_dir(override: str, prefix: str = "calib_B_") -> str:
    """
    Return *override* if non-empty and exists,
    otherwise fall back to find_latest_session_dir(prefix).
    """
    if override and os.path.isdir(override):
        print(f"[calib_utils] Using manually specified session dir: {override}")
        return override
    return find_latest_session_dir(prefix)
