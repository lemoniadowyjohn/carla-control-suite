
from ultimate_pipeline.settings import tile_qa_controller_allows_carla
def run_tile_qa(tile_metadata_path):
    if not tile_qa_controller_allows_carla():
        from ultimate_pipeline.tools.tile_qa_batch import run_tile_qa_batch
        return run_tile_qa_batch(tile_metadata_path)
    raise RuntimeError("Controller CARLA access disabled")
