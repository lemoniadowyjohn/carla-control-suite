#!/usr/bin/env python3
# -*- coding: utf-8 -*-

""" Convert OpenStreetMap file to OpenDRIVE file. """

import argparse
import os
import sys




from pathlib import Path


def _auto_detect_carla_root() -> Path | None:
    here = Path(__file__).resolve()
    for base in [here] + list(here.parents):
        if (base / "PythonAPI" / "carla" / "dist").exists():
            return base
    cwd = Path.cwd().resolve()
    for base in [cwd] + list(cwd.parents):
        if (base / "PythonAPI" / "carla" / "dist").exists():
            return base
    return None


def _ensure_carla_on_path(carla_root: Path | None) -> None:
    # Already importable?
    try:
        import carla  # type: ignore  # noqa: F401
        return
    except Exception:
        pass

    explicit = os.getenv("CARLA_PYTHONAPI_EGG") or os.getenv("CARLA_EGG")
    if explicit and Path(explicit).exists():
        sp = str(Path(explicit))
        if sp not in sys.path:
            sys.path.insert(0, sp)

    if not carla_root:
        return

    dist = carla_root / "PythonAPI" / "carla" / "dist"
    if dist.exists():
        for p in sorted(dist.glob("carla-*")):
            sp = str(p)
            if sp not in sys.path:
                sys.path.insert(0, sp)

    carla_pkg = carla_root / "PythonAPI" / "carla"
    if carla_pkg.exists():
        sp = str(carla_pkg)
        if sp not in sys.path:
            sys.path.insert(0, sp)


def _import_carla(carla_root: str | None = None):
    try:
        import carla  # type: ignore
        return carla
    except Exception:
        pass

    root = None
    if carla_root:
        p = Path(carla_root)
        root = p if p.exists() else None
    if root is None:
        env = os.getenv("CARLA_ROOT") or os.getenv("CARLA_HOME")
        if env and Path(env).exists():
            root = Path(env)
    if root is None:
        root = _auto_detect_carla_root()

    _ensure_carla_on_path(root)

    import carla  # type: ignore
    return carla
def convert(args):
    carla = _import_carla(getattr(args, 'carla_root', None))
    # Read the .osm data
    with open(args.input_path, mode="r", encoding="utf-8") as osmFile:
        osm_data = osmFile.read()

    # Define the desired settings
    settings = carla.Osm2OdrSettings()

    # Set OSM road types to export to OpenDRIVE
    settings.set_osm_way_types([
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "unclassified",
        "residential"
    ])
    settings.default_lane_width = args.lane_width
    settings.generate_traffic_lights = args.traffic_lights
    settings.all_junctions_with_traffic_lights = args.all_junctions_lights
    settings.center_map = args.center_map

    # Convert to .xodr
    xodr_data = carla.Osm2Odr.convert(osm_data, settings)

    # save opendrive file
    with open(args.output_path, "w", encoding="utf-8") as xodrFile:
        xodrFile.write(xodr_data)

# ==============================================================================
# -- main() --------------------------------------------------------------------
# ==============================================================================


def main():
    argparser = argparse.ArgumentParser(
        description=__doc__)
    argparser.add_argument(
        '-i', '--input-path',
        required=True,
        metavar='OSM_FILE_PATH',
        help='set the input OSM file path')
    argparser.add_argument(
        '-o', '--output-path',
        required=True,
        metavar='XODR_FILE_PATH',
        help='set the output XODR file path')

    argparser.add_argument(
        '--carla-root',
        default=None,
        help='CARLA root folder containing PythonAPI/carla/dist (optional; can use CARLA_ROOT env var)'
    )
    argparser.add_argument(
        '--lane-width',
        default=6.0,
        help='width of each road lane in meters')
    argparser.add_argument(
        '--traffic-lights',
        action='store_true',
        help='enable traffic light generation from OSM data')
    argparser.add_argument(
        '--all-junctions-lights',
        action='store_true',
        help='set traffic lights for all junctions')
    argparser.add_argument(
        '--center-map',
        action='store_true',
        help='set center of map to the origin coordinates')

    if len(sys.argv) < 2:
        argparser.print_help()
        return

    args = argparser.parse_args()

    if args.input_path is None or not os.path.exists(args.input_path):
        print('input file not found.')
    if args.output_path is None:
        print('output file path not found.')

    print(__doc__)

    try:
        convert(args)
    except:
        print('\nAn error has occurred in conversion.')


if __name__ == '__main__':

    try:
        main()
    except KeyboardInterrupt:
        print('\nCancelled by user. Bye!')
    except RuntimeError as e:
        print(e)
