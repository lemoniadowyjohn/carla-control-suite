"""Road Link Validation for OpenDRIVE."""
from __future__ import annotations
from ultimate_pipeline.topology.canonical_index import TopologyIndex

class RoadValidator:
    def __init__(self, topo_index: TopologyIndex):
        self.topo_index = topo_index

    def validate_links(self) -> list[str]:
        errors = []
        for r_id, r_idx in self.topo_index.roads.items():
            for elem_type, elem_id in r_idx.predecessors:
                if elem_type == "road":
                    if elem_id not in self.topo_index.roads:
                        errors.append(f"Road {r_id}: predecessor road {elem_id} does not exist")
                elif elem_type == "junction":
                    if elem_id not in self.topo_index.junctions:
                        errors.append(f"Road {r_id}: predecessor junction {elem_id} does not exist")

            for elem_type, elem_id in r_idx.successors:
                if elem_type == "road":
                    if elem_id not in self.topo_index.roads:
                        errors.append(f"Road {r_id}: successor road {elem_id} does not exist")
                elif elem_type == "junction":
                    if elem_id not in self.topo_index.junctions:
                        errors.append(f"Road {r_id}: successor junction {elem_id} does not exist")
        return errors
