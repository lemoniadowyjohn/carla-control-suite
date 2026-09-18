import xml.etree.ElementTree as ET
import shutil
import math
import json
import os

from ultimate_pipeline.config.settings import SETTINGS

GAP_THRESHOLD = getattr(SETTINGS, "MAX_GAP_FOR_FIX", 2.0)
HDG_THRESHOLD = getattr(SETTINGS, "MAX_HEADING_JUMP_FIX", math.radians(8))
LEN_THRESHOLD = getattr(SETTINGS, "MAX_SEGMENT_LENGTH_FIX", 1000.0)

MODE = getattr(SETTINGS, "CONTINUITY_MODE", "moderate")      # safe | moderate | aggressive
SELECTIVE = getattr(SETTINGS, "CONTINUITY_SELECTIVE", True)

class MeshContinuityRepairer:
    """
    Continuity checker / fixer for OpenDRIVE planView geometries.

    Modes (SETTINGS.CONTINUITY_MODE):
      - "safe": diagnostics only, NEVER modifies geometry
      - "moderate": small local smoothing only (gaps/heading)
      - "aggressive": reconstructs entire geometry chain per road

    All thresholds and toggles are controlled by settings.py.
    """

    def __init__(self, xodr_path: str):
        self.xodr_path = xodr_path
        self.tree = ET.parse(xodr_path)
        self.root = self.tree.getroot()

        # local convenience shortcuts
        self.mode = getattr(SETTINGS, "CONTINUITY_MODE", "safe")
        self.selective = getattr(SETTINGS, "CONTINUITY_SELECTIVE", True)

        # thresholds (Ingostadt-friendly defaults; override in settings.py)
        self.gap_threshold = getattr(SETTINGS, "MAX_GAP_FOR_FIX", 3.0)               # meters
        self.hdg_threshold = getattr(SETTINGS, "MAX_HEADING_JUMP_FIX",
                                     math.radians(10.0))                            # radians
        self.len_threshold = getattr(SETTINGS, "MAX_SEGMENT_LENGTH_FIX", 1500.0)     # meters

        # toggles
        self.strict_pass = getattr(SETTINGS, "STRICT_PASS_THROUGH", True)
        self.enable_interp = getattr(SETTINGS, "ENABLE_GAP_INTERPOLATION", True)
        self.enable_hdg_damp = getattr(SETTINGS, "ENABLE_HEADING_DAMPING", True)
        self.enable_curv_smooth = getattr(SETTINGS, "ENABLE_CURVATURE_SMOOTHING", False)

        # internal flag to know if we actually modified anything
        self.modified = False

    # -------------------------------------------------------------
    # PUBLIC ENTRY POINT
    # -------------------------------------------------------------
    @staticmethod
    def run(input_path, output_path):
        r = MeshContinuityRepairer(input_path)
        r.process()
        r.save(output_path)

    # -------------------------------------------------------------
    # MAIN PROCESSING
    # -------------------------------------------------------------
    def process(self):

        if self.mode == "safe":
            print("🔍 SAFE mode: continuity diagnostics only.")
            self.diagnose()
            return

        # Scan everything first
        scan = self.scan_roads()
        roads_to_fix = []

        if self.selective:
            for rid, info in scan.items():
                needs_fix = False

                # local anomaly rule
                for seg in info["local"]:
                    if seg["gap"] > self.gap_threshold:
                        needs_fix = True
                        break
                    if seg["hdg"] > self.hdg_threshold:
                        needs_fix = True
                        break

                # extra guard using global extremes
                if info["max_gap"] > self.gap_threshold * 1.5:
                    needs_fix = True
                if info["max_hdg"] > self.hdg_threshold * 2.0:
                    needs_fix = True

                if needs_fix:
                    roads_to_fix.append(rid)
        else:
            # repair ALL roads
            roads_to_fix = list(scan.keys())

        # STRICT-PASS mode → only repair when needed
        if self.strict_pass and not roads_to_fix:
            print("✓ No roads exceed thresholds. Copying map unchanged.")
            return

        print(f"⚙ Roads selected for repair: {len(roads_to_fix)}")

        if self.mode == "moderate":
            self.moderate_fix(roads_to_fix)
            self.recompute_s_values_postfix()
        elif self.mode == "aggressive":
            self.full_rewrite(roads_to_fix)
            self.recompute_s_values_postfix()

    # -------------------------------------------------------------
    # SAFE DIAGNOSTICS — never modifies geometry
    # -------------------------------------------------------------
    def diagnose(self):
        scan = self.scan_roads()
        bad = [r for r, d in scan.items()
               if d["max_gap"] > 2.0 or d["max_hdg"] > math.radians(5.0)]

        print(f"✓ Roads analyzed: {len(scan)}")
        print(f"⚠ Roads with large anomalies: {len(bad)}")
        for rid in bad[:20]:
            print(f"   - Road {rid} gap={scan[rid]['max_gap']:.2f} m "
                  f"hdg={math.degrees(scan[rid]['max_hdg']):.1f}°")

    # -------------------------------------------------------------
    # SCAN ROADS FOR DISCONTINUITIES
    # -------------------------------------------------------------
    def scan_roads(self):
        report = {}

        for road in self.root.findall("road"):
            rid = road.get("id", "?")

            geoms = list(road.findall("./planView/geometry"))
            if len(geoms) < 2:
                report[rid] = {
                    "max_gap": 0.0,
                    "max_hdg": 0.0,
                    "max_len": 0.0,
                    "local": [],
                }
                continue

            # FORCE SORT BY s (prevents broken geometry order for analysis)
            try:
                geoms.sort(key=lambda g: float(g.get("s", "0")))
            except Exception:
                pass

            max_gap = 0.0
            max_hdg = 0.0
            max_len = 0.0
            local = []

            prev = geoms[0]
            prev_x = float(prev.get("x", 0.0))
            prev_y = float(prev.get("y", 0.0))
            prev_h = float(prev.get("hdg", 0.0))
            prev_len = float(prev.get("length", 0.001))

            for geo in geoms[1:]:
                exp_x, exp_y, _ = self.endpoint(prev_x, prev_y, prev_h, prev_len, prev)
                real_x = float(geo.get("x", 0.0))
                real_y = float(geo.get("y", 0.0))
                real_h = float(geo.get("hdg", 0.0))
                seg_len = float(geo.get("length", 0.001))

                gap = math.hypot(exp_x - real_x, exp_y - real_y)
                hdg_jump = abs(self.normalize(real_h - prev_h))

                max_gap = max(max_gap, gap)
                max_hdg = max(max_hdg, hdg_jump)
                max_len = max(max_len, seg_len)

                local.append({
                    "gap": gap,
                    "hdg": hdg_jump,
                    "len": seg_len,
                })

                prev_x, prev_y = real_x, real_y
                prev_h = real_h
                prev_len = seg_len

            report[rid] = {
                "max_gap": max_gap,
                "max_hdg": max_hdg,
                "max_len": max_len,
                "local": local,
            }

        # debug dump
        debug_path = os.path.join(os.path.dirname(self.xodr_path),
                                  "continuity_debug.json")
        try:
            with open(debug_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
            print(f"📄 continuity_debug.json written → {debug_path}")
        except Exception:
            pass

        return report

    # -------------------------------------------------------------
    # MODERATE FIX: only smooth small discontinuities
    # -------------------------------------------------------------
    def moderate_fix(self, roads_to_fix):

        print("🔧 Applying moderate continuity smoothing…")
        self.modified = True

        for road in self.root.findall("road"):
            rid = road.get("id", "?")
            if rid not in roads_to_fix:
                continue

            geoms = list(road.findall("./planView/geometry"))
            if len(geoms) < 2:
                continue

            # Keep original XML order for writing, but use sorted copy for continuity logic
            try:
                geoms.sort(key=lambda g: float(g.get("s", "0")))
            except Exception:
                pass

            prev = geoms[0]
            prev_x = float(prev.get("x", 0.0))
            prev_y = float(prev.get("y", 0.0))
            prev_h = float(prev.get("hdg", 0.0))
            prev_len = float(prev.get("length", 0.001))

            for geo in geoms[1:]:
                exp_x, exp_y, _ = self.endpoint(prev_x, prev_y, prev_h, prev_len, prev)
                real_x = float(geo.get("x", 0.0))
                real_y = float(geo.get("y", 0.0))
                real_h = float(geo.get("hdg", 0.0))

                gap = math.hypot(exp_x - real_x, exp_y - real_y)
                hdg_jump = self.normalize(real_h - prev_h)

                # fix gap (only small gaps)
                if gap < self.gap_threshold and self.enable_interp:
                    w = getattr(SETTINGS, "CONT_SMOOTH_WEIGHT", 0.25)
                    # adjustable smoothing weight
                    geo.set("x", f"{real_x * (1 - w) + exp_x * w:.8f}")
                    geo.set("y", f"{real_y * (1 - w) + exp_y * w:.8f}")

                # fix heading (only small heading jumps)
                if abs(hdg_jump) < self.hdg_threshold and self.enable_hdg_damp:
                    geo.set("hdg", f"{(real_h + prev_h) / 2.0:.8f}")

                prev = geo
                prev_x = float(geo.get("x", 0.0))
                prev_y = float(geo.get("y", 0.0))
                prev_h = float(geo.get("hdg", 0.0))
                prev_len = float(geo.get("length", 0.001))

    # -------------------------------------------------------------
    # AGGRESSIVE REWRITE: reconstruct entire geometry chain
    # -------------------------------------------------------------
    def full_rewrite(self, roads_to_fix):

        print("⚠ AGGRESSIVE MODE: full geometry rewrite WARNING")
        self.modified = True

        for road in self.root.findall("road"):
            rid = road.get("id", "?")
            if rid not in roads_to_fix:
                continue

            geoms = list(road.findall("./planView/geometry"))
            if len(geoms) < 2:
                continue

            try:
                geoms.sort(key=lambda g: float(g.get("s", "0")))
                plan = road.find("planView")
                if plan is not None:
                    plan.clear()
                    for g in geoms:
                        plan.append(g)

            except Exception:
                pass

            # anchor first geometry
            prev = geoms[0]
            prev_x = float(prev.get("x", 0.0))
            prev_y = float(prev.get("y", 0.0))
            prev_h = float(prev.get("hdg", 0.0))
            prev_len = float(prev.get("length", 0.001))

            for geo in geoms[1:]:
                seg_len = float(geo.get("length", 0.001))

                # ABSURD LENGTH PROTECTION: only clamp if unrealistically long
                if seg_len > self.len_threshold * 10.0:
                    seg_len = self.len_threshold
                    geo.set("length", f"{seg_len:.6f}")

                end_x, end_y, _ = self.endpoint(prev_x, prev_y, prev_h, prev_len, prev)

                geo.set("x", f"{end_x:.8f}")
                geo.set("y", f"{end_y:.8f}")
                geo.set("hdg", f"{prev_h:.8f}")

                prev = geo
                prev_x, prev_y = end_x, end_y
                prev_len = seg_len

    # -------------------------------------------------------------
    # UTILS
    # -------------------------------------------------------------
    @staticmethod
    def normalize(h):
        while h > math.pi:
            h -= 2 * math.pi
        while h < -math.pi:
            h += 2 * math.pi
        return h

    @staticmethod
    def endpoint(x, y, hdg, length, geo_elem):
        """
        Compute endpoint of this geometry segment.
        Supports <arc>; treats <spiral> and <poly3> as straight-line for safety.
        """
        # ARC
        arc = geo_elem.find("arc")
        if arc is not None:
            try:
                k = float(arc.get("curvature", "0"))
            except Exception:
                k = 0.0

            if abs(k) < 1e-9:
                return (
                    x + length * math.cos(hdg),
                    y + length * math.sin(hdg),
                    hdg
                )

            hdg2 = hdg + k * length
            x2 = x + (math.sin(hdg2) - math.sin(hdg)) / k
            y2 = y - (math.cos(hdg2) - math.cos(hdg)) / k
            return x2, y2, hdg2

        # SPIRAL approx (fallback)
        if geo_elem.find("spiral") is not None:
            return (
                x + length * math.cos(hdg),
                y + length * math.sin(hdg),
                hdg
            )

        # POLY3 approx → treat as line (safe)
        if geo_elem.find("poly3") is not None:
            return (x + length * math.cos(hdg),
                    y + length * math.sin(hdg),
                    hdg)

        # LINE fallback
        return (
            x + length * math.cos(hdg),
            y + length * math.sin(hdg),
            hdg
        )

    def recompute_s_values_postfix(self):
        for road in self.root.findall("road"):
            geoms = list(road.findall("./planView/geometry"))
            if not geoms:
                continue

            try:
                geoms.sort(key=lambda g: float(g.get("s", "0")))
            except:
                pass

            plan = road.find("planView")
            if plan is None:
                continue

            plan.clear()
            for g in geoms:
                plan.append(g)

            s_acc = 0.0
            for g in geoms:
                g.set("s", f"{s_acc:.8f}")
                L = float(g.get("length", "0.001"))
                if L <= 0.0:
                    L = 0.001
                    g.set("length", f"{L:.8f}")
                s_acc += L

            road.set("length", f"{s_acc:.8f}")


    # -------------------------------------------------------------
    def save(self, output_path):
        # Realign lane sections before save
        try:
            self.realign_lane_sections()
        except Exception as e:
            print(f"⚠ LaneSection realignment failed: {e}")
        """
        Write output.

        - SAFE mode → always copy original.
        - STRICT_PASS_THROUGH:
              * if nothing was modified → copy original
              * if modified → write modified tree
        """

        if self.mode == "safe":
            shutil.copy(self.xodr_path, output_path)
            print(f"⏭ SAFE PASS-THROUGH → {output_path}")
            return

        if self.strict_pass and not self.modified:
            shutil.copy(self.xodr_path, output_path)
            print(f"⏭ STRICT PASS (no changes) → {output_path}")
            return

        self.tree.write(output_path, encoding="UTF-8", xml_declaration=True)
        print(f"✓ Continuity output saved → {output_path}")
    # -------------------------------------------------------------
    # REALIGN laneSection s-values after geometry smoothing
    # -------------------------------------------------------------
    def realign_lane_sections(self):
        """
        Fix laneSection s-offsets so they align with the recomputed geometry.
        This is required because:
          - geometry s-values change during smoothing / rewriting
          - laneSection@s MUST NOT exceed road length
          - laneSection@s MUST correspond to sorted geometry chain start
        """

        for road in self.root.findall("road"):
            length = float(road.get("length", "0.0"))
            lanes = road.find("lanes")
            if lanes is None:
                continue

            lsecs = lanes.findall("laneSection")
            if not lsecs:
                continue

            # Sort sections by their current s
            try:
                lsecs.sort(key=lambda ls: float(ls.get("s", "0")))
            except:
                pass

            # Reset laneSection s offsets
            new_s = 0.0
            for ls in lsecs:
                ls.set("s", f"{new_s:.8f}")

                # Estimate laneSection length = average of geometry segments
                # This is a safe fallback for OSM maps.
                new_s += max(0.1, length / max(1, len(lsecs)))

            # Final clamp
            last = lsecs[-1]
            last.set("s", f"{min(length - 0.01, float(last.get('s', '0'))):.8f}")

    def scan_for_discontinuities(self):
        pass
