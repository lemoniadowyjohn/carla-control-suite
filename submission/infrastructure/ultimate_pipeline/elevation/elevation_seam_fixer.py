def fix_elevation_seams(
    xodr_in: str,
    out_xodr: str,
    max_snap_m: float = 0.25
) -> dict:
    """
    Aligns z-values at road/geometry boundaries to remove elevation seams.
    Does NOT re-sample DEM.
    Returns stats: seams_checked, seams_fixed, max_delta.
    """
