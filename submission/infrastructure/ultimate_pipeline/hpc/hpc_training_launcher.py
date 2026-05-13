# hpc_training_launcher.py
import json
import os
import subprocess
from pathlib import Path


class HPCTrainingLauncher:
    def __init__(self):
        self.project_root = Path(__file__).parent
        self.hpc_configs = self.project_root / "hpc_configs"

    def create_domain_experiments(self):
        """Create domain adaptation experiments for HPC"""
        experiments = [
            {
                'name': 'osm_only',
                'train_cities': ['berlin', 'cologne', 'frankfurt'],
                'test_cities': ['ingolstadt'],
                'description': 'Train on OSM cities, test on Ingolstadt'
            },
            {
                'name': 'mixed_domains',
                'train_cities': ['berlin', 'hamburg', 'munich'],
                'test_cities': ['ingolstadt'],
                'description': 'Train on mixed OSM cities, test on Ingolstadt'
            },
            {
                'name': 'all_osm',
                'train_cities': ['berlin', 'cologne', 'frankfurt', 'hamburg', 'munich'],
                'test_cities': ['ingolstadt'],
                'description': 'Train on all OSM cities, test on Ingolstadt'
            }
        ]

        for exp in experiments:
            config = {
                'experiment_name': f"domain_adaptation_{exp['name']}",
                'training_cities': exp['train_cities'],
                'testing_cities': exp['test_cities'],
                'model': 'yolov8n',
                'epochs': 50,  # Reduced for testing
                'batch_size': 16,
                'learning_rate': 0.001,
                'domain_adaptation': True,
                'description': exp['description']
            }

            config_path = self.hpc_configs / f"domain_exp_{exp['name']}.json"
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
            print(f"✅ Created HPC config: {config_path}")

    def launch_local_training(self, config_name):
        """Launch training locally (for testing before HPC)"""
        config_path = self.hpc_configs / f"domain_exp_{config_name}.json"

        if not config_path.exists():
            print(f"❌ Config not found: {config_path}")
            return False

        print(f"🚀 Launching LOCAL training: {config_name}")

        # Use your existing thesis perception trainer
        cmd = [
            'python', 'thesis_perception_trainer.py',
            '--config', str(config_path),
            '--local-test',
            '--epochs', '5'  # Short test run
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print("✅ Local training completed successfully")
                print(result.stdout)
            else:
                print("❌ Local training failed")
                print(result.stderr)
            return result.returncode == 0
        except FileNotFoundError:
            print("❌ thesis_perception_trainer.py not found")
            return False

    def generate_hpc_script(self, config_name):
        """Generate HPC submission script"""
        script_content = f"""#!/bin/bash
#SBATCH --job-name=thesis_{config_name}
#SBATCH --output=thesis_logs/hpc_{config_name}_%j.out
#SBATCH --error=thesis_logs/hpc_{config_name}_%j.err
#SBATCH --time=24:00:00
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G

# Load modules
module purge
module load python/3.8
module load cuda/11.7
module load cudnn/8.4

# Setup environment
cd $SLURM_SUBMIT_DIR
source .venv/bin/activate

# Run training
python thesis_perception_trainer.py \\
    --config hpc_configs/domain_exp_{config_name}.json \\
    --epochs 50 \\
    --batch_size 16

echo "HPC training completed for {config_name}"
"""

        script_path = self.hpc_configs / f"submit_{config_name}.sh"
        with open(script_path, 'w') as f:
            f.write(script_content)

        print(f"✅ Generated HPC script: {script_path}")
        return script_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description='HPC Training Launcher')
    parser.add_argument('--create-configs', action='store_true', help='Create domain experiment configs')
    parser.add_argument('--launch', type=str, help='Launch training for specific config')
    parser.add_argument('--generate-scripts', action='store_true', help='Generate HPC submission scripts')

    args = parser.parse_args()
    launcher = HPCTrainingLauncher()

    if args.create_configs:
        launcher.create_domain_experiments()

    if args.launch:
        # First test locally
        success = launcher.launch_local_training(args.launch)
        if success:
            print(f"🎯 Ready for HPC submission: {args.launch}")
        else:
            print(f"❌ Fix local training first: {args.launch}")

    if args.generate_scripts:
        for config in ['osm_only', 'mixed_domains', 'all_osm']:
            launcher.generate_hpc_script(config)


if __name__ == "__main__":
    main()