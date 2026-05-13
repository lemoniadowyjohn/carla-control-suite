#!/bin/bash

python run_pipeline.py --no-elevation
python run_pipeline.py --no-buildings
python run_pipeline.py --no-traffic
python run_pipeline.py --deterministic

python run_full_domain_gap.py
