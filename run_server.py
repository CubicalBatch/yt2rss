#!/usr/bin/env python3
"""Standalone server runner for testing."""

import sys
from pathlib import Path

# Add src to path and run from project root
sys.path.insert(0, str(Path(__file__).parent / "src"))
import os
os.chdir(Path(__file__).parent)

from web_server import YouTubePodcastServer

if __name__ == "__main__":
    server = YouTubePodcastServer(config_dir="appdata/config")
    print("Starting YouTube Podcast Server...")
    print(f"Server will serve:")
    print(f"  - Videos from: {server.videos_dir.absolute()}")
    print(f"  - Config from: {server.config_dir.absolute()}")
    print(f"  - Accessible at: http://{server.host}:{server.port}")
    server.run()
