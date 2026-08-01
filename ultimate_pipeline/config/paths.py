from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
CITY_DIR = PROJECT_ROOT / "cities"
CARLA_CACHE = Path.home() / "AppData" / "Local" / "CarlaUE4"
