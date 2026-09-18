# REFAC_VERSION = "v4_2026-02-21"
# Auto-generated stage module extracted from ultimate_pipeline.main_pipeline
from __future__ import annotations

def _inject_main_pipeline_globals() -> None:
    """Populate this module's globals with symbols from ultimate_pipeline.main_pipeline.

    This avoids duplicating the monolith's import surface while keeping stage code unchanged.
    Import is performed lazily at runtime (after main_pipeline is loaded).
    """
    g = globals()
    if g.get("_UP_STAGE_GLOBALS_INJECTED"):
        return
    from ultimate_pipeline import main_pipeline as _mp
    for k, v in _mp.__dict__.items():
        if k not in g:
            g[k] = v
    g["_UP_STAGE_GLOBALS_INJECTED"] = True



def _run_quality_gates_wrapper(self, final_out: str) -> None:
    _inject_main_pipeline_globals()
    s = self.settings
    if not getattr(s, "ENABLE_QUALITY_GATES_WRAPPER", True):
        print("\n⏭️ Quality gates wrapper disabled.")
        return
    print("\n============== 🚦 QUALITY GATE WRAPPER ==============")

    # Strict mode: re-raise exceptions from quality gates
    strict_mode = os.getenv("UP_STRICT_QUALITY_GATES", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    try:
        from ultimate_pipeline.quality.quality_gates import run_quality_gates
        from ultimate_pipeline.quality.quality_gates import DRIVABILITY_GATES

        failures = run_quality_gates(final_out, out_dir=self.out_dir)

        drivability_failures = sorted(set(failures.keys()) & set(DRIVABILITY_GATES))
        if drivability_failures:
            raise RuntimeError(
                f"❌ Drivability gates failed: {drivability_failures}"
            )

        # In strict mode, raise on any gate failure.
        if strict_mode and failures:
            raise RuntimeError(
                f"❌ Quality gate failures in strict mode: {sorted(failures.keys())}"
            )
    except Exception as e:
        if strict_mode:
            raise  # Re-raise in strict mode
        print(f"⚠️ Quality gates wrapper failed: {e}")


def _run_geometric_continuity_gate(self, xodr_path: str, context: str) -> None:
    _inject_main_pipeline_globals()
    strict_mode = os.getenv("UP_STRICT_QUALITY_GATES", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    strict_fail_on_gate = bool(
        getattr(self.settings, "STRICT_FAIL_ON_GEOMETRIC_CONTINUITY_GATE", False)
    )
    strict_fail_env = os.getenv("UP_STRICT_FAIL_ON_GEOMETRIC_CONTINUITY_GATE")
    if strict_fail_env is not None and strict_fail_env.strip():
        strict_fail_on_gate = strict_fail_env.strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
    fail_closed = bool(strict_mode and strict_fail_on_gate)

    def _percentile(values: List[float], q: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(float(v) for v in values)
        if len(ordered) == 1:
            return float(ordered[0])
        rank = (len(ordered) - 1) * float(q)
        lo = int(math.floor(rank))
        hi = int(math.ceil(rank))
        if lo == hi:
            return float(ordered[lo])
        frac = rank - lo
        return float(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)

    def _stats(values: List[float]) -> Dict[str, float]:
        return {
            "max": float(max(values)) if values else 0.0,
            "p95": float(_percentile(values, 0.95)),
            "p99": float(_percentile(values, 0.99)),
        }

    def _write_artifact(
        *,
        report: Dict[str, Any],
        error_text: str | None,
    ) -> None:
        issues = report.get("issues", []) if isinstance(report, dict) else []
        if not isinstance(issues, list):
            issues = []

        seam_values: List[float] = []
        jump_values: List[float] = []
        sample_road_ids: List[str] = []
        seen_ids = set()
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            try:
                if "dxy" in issue:
                    seam_values.append(float(issue.get("dxy")))
            except Exception:
                pass
            try:
                if "dhdg" in issue:
                    jump_values.append(float(issue.get("dhdg")))
            except Exception:
                pass
            for road_key in ("from_road", "to_road"):
                rid = issue.get(road_key)
                rid_text = str(rid).strip() if rid is not None else ""
                if not rid_text or rid_text in seen_ids:
                    continue
                seen_ids.add(rid_text)
                sample_road_ids.append(rid_text)
                if len(sample_road_ids) >= 10:
                    break

        report_ok = bool(report.get("ok", True)) if isinstance(report, dict) else False
        decision_pass = bool(report_ok and not error_text)
        if error_text:
            decision_reason = f"gate_error: {error_text}"
        elif decision_pass:
            decision_reason = "all observed seams/jumps within thresholds"
        else:
            decision_reason = (
                f"{int(report.get('num_issues', len(issues)) or 0)} offending segments "
                "exceed continuity thresholds"
            )

        artifact = {
            "stage": str(getattr(self, "_run_stage", "unknown")),
            "substage": str(context),
            "xodr_path": str(xodr_path),
            "thresholds": {
                "max_seam_distance_m": float(report.get("eps_xy", 0.0) or 0.0),
                "max_heading_jump_rad": float(report.get("eps_hdg", 0.0) or 0.0),
            },
            "observed": {
                "seam_distance_m": _stats(seam_values),
                "heading_jump_rad": _stats(jump_values),
            },
            "offending_segments": {
                "count": int(report.get("num_issues", len(issues)) or 0),
                "sample_road_ids": sample_road_ids,
            },
            "decision": {
                "pass": decision_pass,
                "reason": decision_reason,
                "strict_mode": bool(strict_mode),
                "strict_fail_on_geometric_continuity_gate": bool(strict_fail_on_gate),
                "fail_closed_active": bool(fail_closed),
            },
        }
        artifact_path = os.path.join(self.out_dir, "geometric_continuity_gate.json")
        try:
            with open(artifact_path, "w", encoding="utf-8") as f:
                json.dump(artifact, f, indent=2, ensure_ascii=True, sort_keys=True)
        except Exception as write_exc:
            print(
                f"[geometric_continuity] Gate artifact write failed ({context}): {write_exc}"
            )

    try:
        report = self.qgate.gate_geometric_continuity(xodr_path)
    except Exception as e:
        _write_artifact(report={}, error_text=str(e))
        if fail_closed:
            raise RuntimeError(
                f"❌ Geometric continuity gate errored ({context}): {e}"
            ) from e
        print(f"[geometric_continuity] Gate errored ({context}): {e}")
        return

    _write_artifact(report=report, error_text=None)

    if not report.get("ok", True):
        if fail_closed:
            raise RuntimeError(
                f"❌ Geometric continuity gate failed ({context}): "
                f"{report.get('num_issues', 0)} issues"
            )
        if strict_mode:
            print(
                f"[geometric_continuity] Gate failed ({context}); continuing "
                "(strict mode, fail-closed disabled)."
            )
            return
        print(
            f"[geometric_continuity] Gate failed ({context}); continuing (non-strict mode)."
        )


def _final_summary_and_llm(self, final_out: str) -> None:
    _inject_main_pipeline_globals()
    s = self.settings
    vreport_path = os.path.join(s.logs_dir(), "validation_report_full.json")
    print("\n============== 📋 FINAL SUMMARY ==============")

    stats = self.vreport.data.get("map_statistics", {})
    total_roads = stats.get("total_roads", "N/A")

    try:
        total_buildings = self.vreport.data.get("buildings", {}).get(
            "inserted", "N/A"
        )
    except Exception:
        total_buildings = "N/A"

    try:
        tl = self.vreport.data.get("enrichment", {}).get(
            "traffic_lights_added", "N/A"
        )
    except Exception:
        tl = "N/A"

    try:
        tiles_created = len(os.listdir(os.path.join(self.out_dir, "tiles")))
    except Exception:
        tiles_created = 0

    max_lat = max_hdg = max_dz = None
    if "seam_statistics" in self.vreport.data:
        seam_list = self.vreport.data["seam_statistics"]
        if seam_list:
            max_lat = safe_max(item["lat"] for item in seam_list)
            max_hdg = safe_max(item["hdg"] for item in seam_list)
            max_dz = safe_max(item["dz"] for item in seam_list)

    print(f"✅ Roads:              {total_roads}")
    print(f"✅ Buildings:          {total_buildings}")
    print(f"✅ Traffic lights:     {tl}")
    print(f"✅ Tiles created:      {tiles_created}")
    print(f"✅ Tile seam max lat:  {max_lat}")
    print(f"✅ Tile seam max hdg:  {max_hdg}")
    print(f"✅ Tile seam max dz:   {max_dz}")
    db_info = self.vreport.data.get("database", {})
    if db_info:
        print(f"✅ DB path:           {db_info.get('path')}")
        print(f"?o. DB schema sha256:  {db_info.get('schema_hash_sha256')}")
        print(f"?o. DB schema md5:     {db_info.get('schema_hash_md5')}")

    # Domain gap RMSE if available
    try:
        dg = self.vreport.data.get("domain_gap_summary", {})
        if dg:
            rmse = dg.get("whole_geometry_gap", {}).get("rmse_xy", "N/A")
            print(f"✅ Domain gap RMSE:    {rmse}")
    except Exception:
        pass

    # final map hash
    final_hash = _hash_file(final_out)
    final_md5 = safe_md5_file(final_out)
    self.vreport.add_dict(
        "output_hashes",
        {"final_xodr": {"path": final_out, "sha256": final_hash, "md5": final_md5}},
    )
    print(f"✅ Final map SHA-256:      {final_hash}")
    if final_md5:
        print(f"?o. Final map MD5:          {final_md5}")

    # ---------------------------------------------------------
    # 📋 [INFO] RUN MANIFEST (final outputs; best-effort)
    # ---------------------------------------------------------
    try:
        update_run_manifest(
            self.out_dir,
            outputs={
                "final_xodr": final_out,
                "validation_report": vreport_path,
                "tile_metadata": os.path.join(self.out_dir, "tile_metadata.json"),
            },
        )
    except Exception as _e:
        print(f"⚠️ Final run manifest update skipped: {_e}")
    try:
        from ultimate_pipeline.utils.finalize_run_pack import (
            write_signature_json,
            write_success_txt,
        )

        key_paths = [
            final_out,
            os.path.join(self.out_dir, "tile_metadata.json"),
            vreport_path,
            os.path.join(self.out_dir, "domain_gap", "full_report.json"),
            os.path.join(self.out_dir, "domain_gap", "summary.csv"),
            os.path.join(self.out_dir, "perception_status.json"),
        ]
        write_signature_json(self.out_dir, key_paths)
        write_success_txt(self.out_dir, summary="main_pipeline")
    except Exception:
        pass

    repair_diff_path = os.path.join(self.out_dir, "repair_diff.json")
    diff_log.save(repair_diff_path)
    print(f"[INFO] Repair diff saved to {repair_diff_path}")

    print("===========================================")
    print("✅ Pipeline completed successfully.")

    self.vreport.save_json(vreport_path)
    print(f"\n📝 Validation report written → {vreport_path}")

    # gate failure summary
    gate_failures = self.qgate.get_failures()
    gate_failures_path = os.path.join(self.out_dir, "gate_failures.json")
    with open(gate_failures_path, "w", encoding="utf-8") as f:
        json.dump(gate_failures, f, indent=2)
    print(f"[INFO] Quality gate summary written → {gate_failures_path}")

    # 🤖 LLM review
    if getattr(s, "ENABLE_LLM_REVIEW", False):
        try:
            llm = LLMQualityGate()
            if gate_failures:
                md = llm.review_gate_failures(gate_failures)
                out_md = os.path.join(self.out_dir, "quality_gates_review.md")
                with open(out_md, "w", encoding="utf-8") as f:
                    f.write(md)
                print(f"🤖 LLM review (failures) written → {out_md}")

            final_md = os.path.join(self.out_dir, "quality_full_review.md")
            llm.review(
                xodr_path=final_out,
                validation_report_path=vreport_path,
                out_md_path=final_md,
            )
            print(f"🧠 Full LLM QA review written → {final_md}")
        except Exception as e:
            print(f"⚠️ LLM review failed (safe to ignore): {e}")
    else:
        print("[LLM] Review disabled by settings.")


def _write_determinism_fingerprint(self, final_out: str) -> None:
    _inject_main_pipeline_globals()
    """Write a lightweight determinism fingerprint (best-effort)."""
    try:
        import hashlib
        import platform

        def _sha256_text(text: str) -> str:
            return hashlib.sha256(text.encode("utf-8")).hexdigest()

        def _read_text_norm(path: str) -> Optional[str]:
            if not os.path.exists(path):
                return None
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = f.read()
                return data.replace("\r\n", "\n").replace("\r", "\n")
            except Exception:
                return None

        payload: Dict[str, Any] = {
            "final_xodr": None,
            "enrichments_json": None,
            "settings_snapshot": None,
            "seed": getattr(self.settings, "DETERMINISTIC_SEED", None),
            "seeds": {
                "deterministic_seed": getattr(
                    self.settings, "DETERMINISTIC_SEED", None
                ),
                "python_hash_seed": os.getenv("PYTHONHASHSEED"),
            },
            "env": {k: v for k, v in os.environ.items() if k.startswith("UP_")},
            "python_version": sys.version,
            "os_info": platform.platform(),
            "git_commit": None,
        }
        try:
            payload["git_commit"] = (
                subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
                )
                .decode("utf-8")
                .strip()
            )
        except Exception:
            payload["git_commit"] = None

        xodr_text = _read_text_norm(final_out)
        if xodr_text is not None:
            payload["final_xodr"] = _sha256_text(xodr_text)

        enrichments_path = os.path.join(self.out_dir, "enrichments.json")
        enrichments_text = _read_text_norm(enrichments_path)
        if enrichments_text is not None:
            payload["enrichments_json"] = _sha256_text(enrichments_text)

        settings_snapshot_path = os.path.join(
            self.out_dir, "settings_snapshot.json"
        )
        settings_text = _read_text_norm(settings_snapshot_path)
        if settings_text is not None:
            payload["settings_snapshot"] = _sha256_text(settings_text)

        out_path = os.path.join(self.out_dir, "determinism_fingerprint.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=True)
    except Exception:
        pass


def _write_run_summary(self, final_out: str) -> None:
    _inject_main_pipeline_globals()
    """
    Write a comprehensive run_summary.json with paths to all key artifacts,
    including preflight status if run.
    """
    from datetime import datetime, timezone

    s = self.settings
    summary_path = os.path.join(self.out_dir, "run_summary.json")

    # Collect artifact paths
    input_osm_path = getattr(s, "OSM_FILE", "")
    bbox_path = (
        os.path.join(s.data_dir(), "bbox.json") if hasattr(s, "data_dir") else ""
    )

    # Handle semantic xodr (if it exists)
    semantic_xodr = final_out.replace(".xodr", "_semantic.xodr")
    if not os.path.exists(semantic_xodr):
        semantic_xodr = ""

    # Preflight status
    preflight_status = None
    preflight_report_path = None
    carla_loadability_path = os.path.join(
        self.out_dir, "carla_loadability_status.json"
    )
    if os.path.exists(carla_loadability_path):
        try:
            with open(carla_loadability_path, "r", encoding="utf-8") as f:
                loadability_data = json.load(f)
                preflight_status = loadability_data.get("status")
                preflight_report_path = loadability_data.get(
                    "preflight_report_path"
                )
        except Exception:
            pass

    # Tile QA status (prefer STEP10 status, with legacy fallback)
    tile_qa_status = None
    tile_qa_status_path = None
    for candidate in ("step10_tile_qa_status.json", "tile_qa_status.json"):
        p = os.path.join(self.out_dir, candidate)
        if not os.path.exists(p):
            continue
        tile_qa_status_path = p
        try:
            with open(p, "r", encoding="utf-8") as f:
                tile_qa_data = json.load(f) or {}
            if isinstance(tile_qa_data, dict):
                tile_qa_status = tile_qa_data.get("status")
        except Exception:
            tile_qa_status = None
        break

    # Settings snapshot hash
    settings_hash = None
    settings_snapshot_path = os.path.join(self.out_dir, "settings_snapshot.json")
    if os.path.exists(settings_snapshot_path):
        settings_hash = _hash_file(settings_snapshot_path)

    run_summary = {
        "pipeline_version": "thesis_final",
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "run_dir": self.out_dir,
        "inputs": {
            "osm_file": input_osm_path,
            "bbox_json": bbox_path if os.path.exists(bbox_path) else None,
        },
        "outputs": {
            "final_xodr": final_out,
            "semantic_xodr": semantic_xodr if semantic_xodr else None,
        },
        "validation": {
            "preflight_status": preflight_status,
            "preflight_report": preflight_report_path,
            "tile_qa_status": tile_qa_status,
            "tile_qa_status_path": tile_qa_status_path,
        },
        "settings": {
            "snapshot_path": settings_snapshot_path,
            "snapshot_sha256": settings_hash,
            "snapshot_md5": safe_md5_file(settings_snapshot_path),
        },
    }

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(run_summary, f, indent=2, ensure_ascii=False)

    print(f"🧾 Run summary manifest written → {summary_path}")
    try:
        from ultimate_pipeline.utils.environment_snapshot import (
            write_environment_snapshot,
        )

        write_environment_snapshot(Path(self.out_dir) / "environment_snapshot.json")
    except Exception:
        pass

