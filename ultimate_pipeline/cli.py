import click

from ultimate_pipeline.utils.bootstrap import bootstrap_console

# Must run before any prints/logs that may contain Unicode.
bootstrap_console()

from ultimate_pipeline.utils.timestamped_print import enable_timestamped_print

enable_timestamped_print()


@click.group()
def cli() -> None:
    """Ultimate Pipeline CLI."""
    pass


@cli.command()
def build_map() -> None:
    """Run the main map-building pipeline."""
    # Lazy import so `--help` works even if CARLA/perception deps are missing.
    from ultimate_pipeline.main_pipeline import main as pipeline_main

    pipeline_main()


@cli.command()
@click.option("--dataset", default="auto_dataset", show_default=True)
@click.option("--frames", default=200, show_default=True, type=int)
@click.option("--fps", default=20, show_default=True, type=int)
@click.option("--calib", default=None, help="Path to calib_data.json; defaults to SETTINGS.SENSOR_CALIB_JSON")
@click.option("--camera", default=None, help="Record only this camera (e.g., front_left_camera)")
@click.option("--all-cameras", is_flag=True, help="Record all calibrated cameras")
@click.option("--no-aug", is_flag=True, help="Disable augmentation")
def generate_dataset(dataset: str, frames: int, fps: int, calib: str | None, camera: str | None, all_cameras: bool, no_aug: bool) -> None:
    """Generate a perception dataset inside CARLA (calibrated sensors)."""
    if camera and all_cameras:
        raise click.ClickException("Use either --camera or --all-cameras, not both.")
    if fps <= 0:
        raise click.ClickException("--fps must be > 0")
    if frames <= 0:
        raise click.ClickException("--frames must be > 0")
    try:
        from ultimate_pipeline.perception.perception_runner_local_aug import PerceptionRunnerLocalAug
        from ultimate_pipeline.config.settings import SETTINGS
    except ImportError as e:
        raise click.ClickException(f"Dataset capture runner not available: {e}") from e

    runner = PerceptionRunnerLocalAug(
        fps=fps,
        calib_file=(calib or getattr(SETTINGS, "SENSOR_CALIB_JSON", "calib_data.json")),
        enable_augmentation=(not no_aug),
        verbose=True,
    )
    try:
        out_dir = runner.run_capture_session(
            dataset,
            num_frames=frames,
            camera_name=camera,
            record_all_cameras=all_cameras,
        )
    except Exception as e:
        raise click.ClickException(f"Capture failed: {e}") from e
    click.echo(f"[OK] Dataset written to: {out_dir}")


@cli.command()
@click.option("--duration-ticks", default=45, show_default=True, type=int)
@click.option("--warmup-ticks", default=30, show_default=True, type=int)
@click.option("--npc-cap", default=20, show_default=True, type=int)
@click.option("--spawn-index", default=0, show_default=True, type=int)
def run_perception(duration_ticks: int, warmup_ticks: int, npc_cap: int, spawn_index: int) -> None:
    """Run local perception QA on the currently loaded CARLA map."""
    if duration_ticks <= 0:
        raise click.ClickException("--duration-ticks must be > 0")
    if warmup_ticks < 0:
        raise click.ClickException("--warmup-ticks must be >= 0")
    if npc_cap < 0:
        raise click.ClickException("--npc-cap must be >= 0")
    if spawn_index < 0:
        raise click.ClickException("--spawn-index must be >= 0")
    try:
        import carla
        from ultimate_pipeline.carla_tools.local_perception_runner import LocalPerceptionRunner
        from ultimate_pipeline.config.settings import SETTINGS
    except ImportError as e:
        raise click.ClickException(f"Perception runner dependencies missing: {e}") from e

    host = getattr(SETTINGS, "CARLA_HOST", "127.0.0.1")
    port = int(getattr(SETTINGS, "CARLA_PORT", 2000))
    timeout = float(getattr(SETTINGS, "CARLA_TIMEOUT", 30.0))

    try:
        client = carla.Client(host, port)
        client.set_timeout(timeout)
        client.get_server_version()
    except Exception as e:
        raise click.ClickException(f"Could not reach CARLA at {host}:{port}: {e}") from e

    runner = LocalPerceptionRunner(
        client,
        duration_ticks=duration_ticks,
        warmup_ticks=warmup_ticks,
        npc_cap=npc_cap,
        spawn_point_index=spawn_index,
    )
    try:
        runner.run()
    except Exception as e:
        raise click.ClickException(f"Perception run failed: {e}") from e

if __name__ == "__main__":
    cli()
