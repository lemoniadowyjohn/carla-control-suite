# ultimate_pipeline/core/file_utils.py

import os
import shutil
from typing import Tuple
import xml.etree.ElementTree as ET
from ultimate_pipeline.core.georef_utils import normalize_georeference


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def copy_file(src: str, dst: str) -> None:
    ensure_dir(os.path.dirname(dst))
    shutil.copy2(src, dst)


def read_xodr(path: str) -> Tuple[ET.ElementTree, ET.Element]:
    tree = ET.parse(path)
    root = tree.getroot()
    return tree, root


def write_xodr(tree: ET.ElementTree, path: str) -> None:
    ensure_dir(os.path.dirname(path))
    try:
        root = tree.getroot()
        header = root.find("header")
        if header is not None:
            geo = header.find("geoReference")
            if geo is not None and geo.text:
                geo.text = normalize_georeference(geo.text)
    except Exception:
        pass
    tree.write(path, encoding="utf-8", xml_declaration=True)
