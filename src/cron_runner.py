#!/usr/bin/env python3

import os
import sys
import time
import json
import fcntl
import logging
import argparse
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
import yaml

# Add the src directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Handle both relative and absolute imports
try:
    from .downloader import YouTubeDownloader
except ImportError:
    from downloader import YouTubeDownloader


class AutomationRunner:
    def __init__(self, base_dir: str = "."):
        self.base_dir = Path(base_dir)
        self.config_path = self.base_dir / "appdata" / "config" / "channels.yaml"
        self.lock_file_path = self.base_dir / "cron_runner.lock"
        self.videos_dir = self.base_dir / "appdata" / "podcasts"

        # Setup logging
        self.setup_logging()

        # Initialize modules
        self.downloader = YouTubeDownloader(str(self.config_path), str(self.base_dir))

    def setup_logging(self):
        """Setup comprehensive logging for the automation runner"""
        # Create logger
        self.logger = logging.getLogger("cron_runner")
        self.logger.setLevel(logging.INFO)

        # Remove existing handlers to avoid duplicate logs
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)

        # Create formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        # Console handler only
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

    def acquire_lock(self) -> bool:
        """Acquire lock file to prevent concurrent runs"""
        try:
            self.lock_file = open(self.lock_file_path, "w")
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.lock_file.write(f"{os.getpid()}\n")
            self.lock_file.flush()
            self.logger.info("Lock acquired successfully")
            return True
        except (OSError, IOError) as e:
            self.logger.warning(f"Could not acquire lock: {e}")
            return False

    def release_lock(self):
        """Release the lock file"""
        try:
            if hasattr(self, "lock_file"):
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                self.lock_file.close()
                if self.lock_file_path.exists():
                    self.lock_file_path.unlink()
                self.logger.info("Lock released successfully")
        except Exception as e:
            self.logger.error(f"Error releasing lock: {e}")

    def load_and_validate_config(self) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Load and validate configuration from channels.yaml"""
        try:
            if not self.config_path.exists():
                self.logger.error(f"Configuration file not found: {self.config_path}")
                return [], {}

            with open(self.config_path, "r") as f:
                config = yaml.safe_load(f)

            channels = config.get("channels", [])
            global_config = {k: v for k, v in config.items() if k != "channels"}

            if not channels:
                self.logger.warning("No channels configured")
                return [], global_config

            # Validate each channel configuration
            valid_channels = []
            for channel in channels:
                if self.validate_channel_config(channel):
                    valid_channels.append(channel)
                else:
                    self.logger.warning(f"Skipping invalid channel config: {channel}")

            self.logger.info(f"Loaded {len(valid_channels)} valid channel(s)")
            return valid_channels, global_config

        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            return [], {}

    def validate_channel_config(self, channel: Dict[str, Any]) -> bool:
        """Validate individual channel configuration"""
        required_fields = ["name", "url", "max_episodes"]

        for field in required_fields:
            if field not in channel:
                self.logger.error(f"Missing required field '{field}' in channel config")
                return False

        if not isinstance(channel["max_episodes"], int) or channel["max_episodes"] <= 0:
            self.logger.error("max_episodes must be a positive integer")
            return False

        if not channel["url"].startswith("https://www.youtube.com/"):
            self.logger.error(f"Invalid YouTube URL: {channel['url']}")
            return False

        return True

    def cleanup_old_videos(self, channel_name: str, max_episodes: int):
        """Remove oldest videos exceeding the limit"""
        try:
            channel_dir = self.videos_dir / channel_name
            if not channel_dir.exists():
                self.logger.info("   📁 No channel directory found, skipping cleanup")
                return

            # Get all video files with their metadata
            video_files = []
            for json_file in channel_dir.glob("*.json"):
                try:
                    with open(json_file, "r") as f:
                        metadata = json.load(f)
                    video_id = metadata["id"]
                    upload_date = metadata.get("upload_date", "19700101")
                    video_files.append((upload_date, video_id, json_file))
                except Exception as e:
                    self.logger.warning(f"Error reading metadata from {json_file}: {e}")
                    continue

            self.logger.info(
                f"   📊 Found {len(video_files)} episodes in channel directory"
            )
            self.logger.info(f"   🎯 Max episodes allowed: {max_episodes}")

            # Sort by upload date (oldest first)
            video_files.sort(key=lambda x: x[0])

            # Remove excess videos
            if len(video_files) > max_episodes:
                videos_to_remove = video_files[:-max_episodes]
                self.logger.info(
                    f"   🗑️  Need to remove {len(videos_to_remove)} old episodes"
                )

                for upload_date, video_id, json_file in videos_to_remove:
                    try:
                        # Remove video file
                        video_file = channel_dir / f"{video_id}.mp4"
                        audio_file = (
                            channel_dir / f"{video_id}.m4a"
                        )  # Check for audio files too

                        removed_files = []
                        if video_file.exists():
                            video_file.unlink()
                            removed_files.append("video")
                            self.logger.info(f"Removed old video: {video_file}")

                        if audio_file.exists():
                            audio_file.unlink()
                            removed_files.append("audio")
                            self.logger.info(f"Removed old audio: {audio_file}")

                        # Remove JSON metadata
                        if json_file.exists():
                            json_file.unlink()
                            removed_files.append("metadata")
                            self.logger.info(f"Removed metadata: {json_file}")

                        # Remove thumbnail
                        thumbnails_dir = channel_dir / "thumbnails"
                        thumbnail_removed = False
                        for thumb_file in thumbnails_dir.glob(f"{video_id}.*"):
                            thumb_file.unlink()
                            thumbnail_removed = True
                            self.logger.info(f"Removed thumbnail: {thumb_file}")
                        if thumbnail_removed:
                            removed_files.append("thumbnail")

                        self.logger.info(
                            f"     🗑️  Removed {video_id}: {', '.join(removed_files)}"
                        )

                    except Exception as e:
                        self.logger.error(f"     ❌ Error removing {video_id}: {e}")
            else:
                self.logger.info("   ✅ No cleanup needed (within episode limit)")

        except Exception as e:
            self.logger.error(f"   ❌ Error during cleanup for {channel_name}: {e}")

    def process_channel(
        self, channel: Dict[str, Any], global_config: Dict[str, Any]
    ) -> bool:
        """Process a single channel: download videos and generate RSS feed"""
        channel_name = channel["name"]

        self.logger.info(
            f"\n🚀 ========== PROCESSING CHANNEL: {channel_name} =========="
        )

        try:
            # Download new videos
            self.logger.info("📥 Starting video download phase...")
            downloaded_count = self.downloader.process_channel(channel, global_config)

            if downloaded_count > 0:
                self.logger.info(
                    f"✅ Download phase complete - {downloaded_count} new episodes downloaded"
                )
            else:
                self.logger.info("💭 No new episodes to download")

            # Cleanup old videos
            self.logger.info("🧹 Starting cleanup phase...")
            self.cleanup_old_videos(channel_name, channel["max_episodes"])
            self.logger.info("✅ Cleanup phase complete")

            # RSS feeds are now generated dynamically when requested
            self.logger.info("🎉 Channel processing successful!")

            return True

        except Exception as e:
            self.logger.error(f"❌ Error processing channel {channel_name}: {e}")
            return False

    def run(self) -> int:
        """Main automation runner method"""
        start_time = time.time()

        self.logger.info("\n🚀 ========== YT2RSS AUTOMATION STARTING ==========\n")
        self.logger.info(
            f"🕰️  Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        # Acquire lock
        if not self.acquire_lock():
            self.logger.error("❌ Another instance is already running, exiting")
            return 1

        try:
            # Load and validate configuration
            self.logger.info("📄 Loading configuration...")
            channels, global_config = self.load_and_validate_config()
            if not channels:
                self.logger.error("❌ No valid channels to process")
                return 1

            self.logger.info("✅ Configuration loaded successfully")
            self.logger.info(f"📻 Found {len(channels)} channel(s) to process\n")

            # Process each channel
            processed_count = 0
            error_count = 0

            for i, channel in enumerate(channels, 1):
                try:
                    self.logger.info(
                        f"\n[{i}/{len(channels)}] Starting channel processing..."
                    )
                    if self.process_channel(channel, global_config):
                        processed_count += 1
                        self.logger.info(
                            f"[{i}/{len(channels)}] ✅ Channel processed successfully"
                        )
                    else:
                        error_count += 1
                        self.logger.error(
                            f"[{i}/{len(channels)}] ❌ Channel processing failed"
                        )
                except Exception as e:
                    self.logger.error(
                        f"[{i}/{len(channels)}] ❌ Unexpected error processing channel {channel.get('name', 'unknown')}: {e}"
                    )
                    error_count += 1

            # Summary
            elapsed_time = time.time() - start_time

            self.logger.info("\n\n🏁 ========== AUTOMATION COMPLETE ==========\n")
            self.logger.info(f"🕰️  Total time: {elapsed_time:.2f} seconds")
            self.logger.info(f"✅ Successful: {processed_count} channels")
            self.logger.info(f"❌ Errors: {error_count} channels")

            if error_count == 0:
                self.logger.info("🎉 All channels processed successfully!")
            else:
                self.logger.warning(
                    "⚠️  Some channels had errors - check logs for details"
                )

            return 0 if error_count == 0 else 1

        except Exception as e:
            self.logger.error(f"\n🔥 FATAL ERROR in automation runner: {e}")
            return 1
        finally:
            self.release_lock()


def main():
    """Main entry point for the automation script"""
    parser = argparse.ArgumentParser(description="YouTube to Podcast automation runner")
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Base directory for the project (default: current directory)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Run automation
    runner = AutomationRunner(args.base_dir)
    exit_code = runner.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
