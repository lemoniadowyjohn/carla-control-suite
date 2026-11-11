# ultimate_pipeline/core/file_utils.py

import json
import os
import shutil
import tempfile
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


def atomic_write_json(path: str, value, **json_kwargs) -> None:
    """Serialize JSON to a same-directory temporary file, then publish it."""
    payload = json.dumps(value, **json_kwargs).encode("utf-8")
    _atomic_write_bytes(path, payload)


def _atomic_write_bytes(path: str, payload: bytes) -> None:
    """Replace *path* only after complete same-volume durable temp output."""
    destination = os.path.abspath(path)
    parent = os.path.dirname(destination)
    ensure_dir(parent)
    fd, temporary = tempfile.mkstemp(prefix=f".{os.path.basename(destination)}.", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def write_xodr(tree: ET.ElementTree, path: str) -> None:
    destination = os.path.abspath(path)
    ensure_dir(os.path.dirname(destination))
    try:
        root = tree.getroot()
        header = root.find("header")
        if header is not None:
            geo = header.find("geoReference")
            if geo is not None and geo.text:
                geo.text = normalize_georeference(geo.text)
    except Exception:
        pass
    fd, temporary = tempfile.mkstemp(
        prefix=f".{os.path.basename(destination)}.", suffix=".tmp",
        dir=os.path.dirname(destination),
    )
    os.close(fd)
    try:
        tree.write(temporary, encoding="utf-8", xml_declaration=True)
        with open(temporary, "r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
