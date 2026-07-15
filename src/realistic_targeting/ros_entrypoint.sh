#!/bin/bash
set -e

source /opt/ros/jazzy/setup.bash
source /app/install/setup.bash

ros2 launch realistic_targeting realistic_targeting.launch.py
