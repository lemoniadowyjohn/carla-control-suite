# ultimate_pipeline/core/file_utils.py

import os
import shutil
from typing import Tuple
import xml.etree.ElementTree as ET


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
    tree.write(path, encoding="utf-8", xml_declaration=True)
