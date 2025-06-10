#!/bin/bash
# YouTube to Podcast Automation Runner
# This script activates the virtual environment and runs the automation script

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Change to the project directory
cd "$SCRIPT_DIR"

# Activate virtual environment
source venv/bin/activate

# Run the automation script
python src/cron_runner.py

# Exit with the same code as the automation script
exit $?