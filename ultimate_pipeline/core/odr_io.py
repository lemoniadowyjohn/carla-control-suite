# ultimate_pipeline/core/odr_io.py

from typing import Tuple
import xml.etree.ElementTree as ET

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.core.file_utils import read_xodr, write_xodr


def load_xodr(path: str) -> Tuple[ET.ElementTree, ET.Element]:
    """
    Wrapper around read_xodr that returns (tree, root).
    """
    return read_xodr(path)


def save_xodr(tree: ET.ElementTree, path: str) -> None:
    """
    Wrapper around write_xodr.
    """
    write_xodr(tree, path)


def force_georeference(root, lat0: float | None = None, lon0: float | None = None) -> None:
    """
    Ensure <geoReference> exists on the <header> and matches coordinates.json.

    If lat0/lon0 are provided explicitly, they override coordinates.json.
    Otherwise, they are taken from SETTINGS.load_gps_bounds().
    """
    # fallback to coordinates.json if explicit values not given
    if lat0 is None or lon0 is None:
        gps = SETTINGS.load_gps_bounds()
        lat0 = gps["lat_min"]
        lon0 = gps["lon_min"]

    header = root.find("header")
    if header is None:
        raise RuntimeError("OpenDRIVE root has no <header> element")

    geo = header.find("geoReference")
    if geo is None:
        geo = ET.SubElement(header, "geoReference")

    geo.text = (
        f"+proj=tmerc +lat_0={lat0} +lon_0={lon0} "
        "+k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
    )
