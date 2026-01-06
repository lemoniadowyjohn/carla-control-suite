# ultimate_pipeline/topology/sumo_repair.py

import os
import subprocess
from ultimate_pipeline.core.file_utils import copy_file, ensure_dir
from ultimate_pipeline.config.settings import SETTINGS


class SUMORepair:
    """
    Optional: use SUMO netconvert to reconstruct topology and export a cleaned OpenDRIVE.
    """

    @staticmethod
    def repair(input_xodr: str, output_xodr: str) -> str:
        exe = getattr(SETTINGS, "SUMO_NETCONVERT", "")
        ensure_dir(os.path.dirname(output_xodr))

        if (not getattr(SETTINGS, "ENABLE_SUMO_REPAIR", False)) or (not exe) or (not os.path.exists(exe)):
            print("ℹ SUMORepair: SUMO not available or disabled; copying input.")
            copy_file(input_xodr, output_xodr)
            return output_xodr

        temp_net = output_xodr + ".net.xml"

        cmd = [
            exe,
            "--opendrive", input_xodr,
            "-o", temp_net,
            "--opendrive-output", output_xodr,
            "--geometry.remove", "true",
            "--ignore-errors",
        ]
        print("▶ Running SUMO netconvert for topology repair...")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                print("⚠ SUMORepair: netconvert failed; stderr tail:")
                print("\n".join(result.stderr.splitlines()[-20:]))
                # fall back to original
                copy_file(input_xodr, output_xodr)
            else:
                print(f"✓ SUMORepair: repaired XODR → {output_xodr}")
        except Exception as e:
            print(f"⚠ SUMORepair: exception {e}; using original file.")
            copy_file(input_xodr, output_xodr)
        finally:
            try:
                if os.path.exists(temp_net):
                    os.remove(temp_net)
            except Exception:
                pass

        return output_xodr
