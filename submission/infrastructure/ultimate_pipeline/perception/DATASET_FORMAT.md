# Perception Dataset Format

This document defines the dataset layout produced by the CARLA-based
OSM → OpenDRIVE → simulation pipeline.

## Directory Structure

dataset/
├── rgb/
│   ├── <camera_name>/
├── lidar/
│   ├── <lidar_name>/
├── semseg_raw/
│   ├── <camera_name>/
├── timestamps.json
├── recorder_manifest.json
└── sensor_transforms.json

## Image Naming Convention

<frame_id>.png (or .jpg)

Example:
00000123.png

- frame_id: zero-padded integer (8 digits)

## Coordinate Frames

All data follows the CARLA coordinate convention:

- World frame: right-handed, Z up
- Vehicle frame: origin at ego vehicle center
- Camera frame: defined by cTv (vehicle → camera)

Camera intrinsics:
- Pinhole model
- K_undistortion is used
- Distortion parameters ignored

## LiDAR

- Stored as .bin
- Coordinates in LiDAR frame
- Transformation to vehicle frame via vTl

## Labels

- Stored per-frame as JSON
- Object classes follow CARLA taxonomy
- Bounding boxes in camera frame

## Timestamps

timestamps.txt contains simulation time (seconds)
for each frame, aligned across sensors.

## Determinism

Each dataset includes metadata:
- map hash
- CARLA version
- random seed
