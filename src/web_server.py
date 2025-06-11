import os
import mimetypes
import yaml
import subprocess
import threading
import time
import json
import atexit
import re
from pathlib import Path
from typing import Optional, Tuple, List
from datetime import datetime
import yt_dlp

from flask import Flask, Response, request, send_file, render_template, abort, jsonify
from werkzeug.utils import secure_filename
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

try:
    from .utils import (
        setup_logging,
        get_video_files,
        sanitize_channel_name,
        ensure_directory,
    )
    from .rss_generator import RSSGenerator
except ImportError:
    from utils import (
        setup_logging,
        get_video_files,
        sanitize_channel_name,
        ensure_directory,
    )
    from rss_generator import RSSGenerator


class YouTubePodcastServer:
    """Flask-based web server for serving RSS feeds and media files."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5000,
        videos_dir: str = "appdata/podcasts",
        config_dir: str = "appdata/config",
    ):
        self.host = host
        self.port = port
        # Use absolute paths to avoid Flask app instance path issues
        self.videos_dir = Path(videos_dir).resolve()
        self.config_dir = Path(config_dir).resolve()
        self.logger = setup_logging()

        # Refresh state tracking
        self.refresh_status = {"running": False, "start_time": None, "duration": 0}

        # Initialize scheduler
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        atexit.register(lambda: self.scheduler.shutdown())

        # Start automatic refresh schedule
        self._setup_scheduler()

        # Initialize Flask app with templates and static folders
        self.app = Flask(__name__, template_folder="templates", static_folder="static")
        self._setup_routes()

        # Enable MIME type for MP4 files
        mimetypes.add_type("video/mp4", ".mp4")

    def _load_refresh_timestamps(self):
        """Load refresh timestamps from file"""
        timestamps_file = self.config_dir / "refresh_timestamps.json"
        if not timestamps_file.exists():
            return {}
        try:
            with open(timestamps_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            self.logger.error(f"Error loading refresh timestamps: {e}")
            return {}

    def _format_timestamp(self, iso_timestamp: str) -> str:
        """Format ISO timestamp for display - returns raw ISO for client-side formatting"""
        try:
            # Validate the timestamp and return it as-is for client-side processing
            datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            return iso_timestamp
        except (ValueError, AttributeError):
            return ""

    def _load_channel_config(self):
        """Load channel configuration from YAML file."""
        config_file = self.config_dir / "channels.yaml"
        if not config_file.exists():
            return {"channels": [], "refresh_interval_hours": 24}

        try:
            with open(config_file, "r") as f:
                config = yaml.safe_load(f)
                # Ensure defaults
                if "channels" not in config:
                    config["channels"] = []
                if "refresh_interval_hours" not in config:
                    config["refresh_interval_hours"] = 24
                return config
        except Exception as e:
            self.logger.error(f"Error loading config: {e}")
            return {"channels": [], "refresh_interval_hours": 24}

    def _setup_scheduler(self):
        """Setup automatic refresh scheduler based on config."""
        try:
            config = self._load_channel_config()
            interval_hours = config.get("refresh_interval_hours", 24)

            # Remove existing job if any
            if self.scheduler.get_job("auto_refresh"):
                self.scheduler.remove_job("auto_refresh")

            # Add new job
            self.scheduler.add_job(
                func=self._run_automation_script,
                trigger=IntervalTrigger(hours=interval_hours),
                id="auto_refresh",
                name="Automatic Refresh",
                replace_existing=True,
            )

            self.logger.info(
                f"Scheduled automatic refresh every {interval_hours} hours"
            )

        except Exception as e:
            self.logger.error(f"Error setting up scheduler: {e}")

    def _restart_scheduler(self, new_interval_hours: int):
        """Restart scheduler with new interval."""
        try:
            # Remove existing job
            if self.scheduler.get_job("auto_refresh"):
                self.scheduler.remove_job("auto_refresh")

            # Add job with new interval
            self.scheduler.add_job(
                func=self._run_automation_script,
                trigger=IntervalTrigger(hours=new_interval_hours),
                id="auto_refresh",
                name="Automatic Refresh",
                replace_existing=True,
            )

            self.logger.info(
                f"Rescheduled automatic refresh to every {new_interval_hours} hours"
            )
            return True

        except Exception as e:
            self.logger.error(f"Error restarting scheduler: {e}")
            return False

    def _save_channel_config(self, config):
        """Save channel configuration to YAML file."""
        # Ensure config directory exists
        ensure_directory(str(self.config_dir))

        config_file = self.config_dir / "channels.yaml"
        try:
            with open(config_file, "w") as f:
                yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
            return True
        except Exception as e:
            self.logger.error(f"Error saving config: {e}")
            return False

    def _setup_routes(self):
        """Setup Flask routes."""

        @self.app.route("/")
        def index():
            """Index page listing available feeds."""
            return self._serve_index()

        @self.app.route("/feeds/<channel_name>")
        def serve_feed(channel_name: str):
            """Serve RSS feed for a channel."""
            return self._serve_rss_feed(channel_name)

        @self.app.route("/podcasts/<channel_name>/<filename>")
        def serve_video(channel_name: str, filename: str):
            """Serve video file with range request support."""
            return self._serve_video_file(channel_name, filename)

        @self.app.route("/thumbnails/<channel_name>/<filename>")
        def serve_thumbnail(channel_name: str, filename: str):
            """Serve thumbnail image."""
            return self._serve_thumbnail_file(channel_name, filename)

        # API Routes for config management
        @self.app.route("/api/channels", methods=["GET"])
        def get_channels():
            """Get all channel configurations."""
            return jsonify(self._load_channel_config())

        @self.app.route("/api/channels", methods=["POST"])
        def add_channel():
            """Add a new channel configuration."""
            return self._handle_add_channel()

        @self.app.route("/api/channels/<channel_name>", methods=["PUT"])
        def update_channel(channel_name: str):
            """Update an existing channel configuration."""
            return self._handle_update_channel(channel_name)

        @self.app.route("/api/channels/<channel_name>", methods=["DELETE"])
        def delete_channel(channel_name: str):
            """Delete a channel configuration."""
            return self._handle_delete_channel(channel_name)

        @self.app.route("/api/refresh", methods=["POST"])
        def trigger_refresh():
            """Trigger the automation script refresh."""
            return self._handle_refresh_trigger()

        @self.app.route("/api/refresh/status", methods=["GET"])
        def refresh_status():
            """Get current refresh status."""
            return self._handle_refresh_status()

        @self.app.route("/api/config/refresh-interval", methods=["GET"])
        def get_refresh_interval():
            """Get current refresh interval."""
            return self._handle_get_refresh_interval()

        @self.app.route("/api/config/refresh-interval", methods=["PUT"])
        def update_refresh_interval():
            """Update refresh interval."""
            return self._handle_update_refresh_interval()

        @self.app.route("/api/channels/<channel_name>/purge", methods=["POST"])
        def purge_channel_episodes(channel_name: str):
            """Purge downloaded episodes for a channel and regenerate RSS."""
            return self._handle_purge_episodes(channel_name)

        @self.app.after_request
        def after_request(response):
            """Add CORS headers for compatibility."""
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, HEAD, OPTIONS, POST, PUT, DELETE"
            )
            response.headers["Access-Control-Allow-Headers"] = "Range, Content-Type"
            return response

    def _run_automation_script(self):
        """Run the automation script in a separate thread."""
        process = None
        try:
            # Get the project root directory
            project_root = Path(__file__).parent.parent
            cron_runner_script = project_root / "src" / "cron_runner.py"

            self.logger.info("Starting cron runner refresh")
            self.refresh_status["running"] = True
            self.refresh_status["start_time"] = time.time()

            # Run the cron runner with live output streaming
            process = subprocess.Popen(
                ["python", str(cron_runner_script)],
                cwd=str(project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            # Stream output line by line
            if process.stdout:
                for line in iter(process.stdout.readline, ""):
                    if line:
                        # Remove trailing newline and log through webserver logger
                        self.logger.info(f"[CRON] {line.rstrip()}")

            # Wait for process to complete
            return_code = process.wait(timeout=3600)  # 1 hour timeout

            self.refresh_status["running"] = False
            self.refresh_status["duration"] = (
                time.time() - self.refresh_status["start_time"]
            )

            if return_code == 0:
                self.logger.info("Cron runner completed successfully")
            else:
                self.logger.error(f"Cron runner failed with return code {return_code}")

        except subprocess.TimeoutExpired:
            self.logger.error("Cron runner timed out")
            if process:
                process.kill()
            self.refresh_status["running"] = False
            self.refresh_status["duration"] = (
                time.time() - self.refresh_status["start_time"]
            )
        except Exception as e:
            self.logger.error(f"Error running cron runner: {e}")
            self.refresh_status["running"] = False
            self.refresh_status["duration"] = (
                time.time() - self.refresh_status["start_time"]
            )

    def _handle_refresh_trigger(self):
        """Handle refresh trigger request."""
        try:
            if self.refresh_status["running"]:
                return jsonify({"error": "Refresh already in progress"}), 409

            # Start the automation script in a background thread
            thread = threading.Thread(target=self._run_automation_script)
            thread.daemon = True
            thread.start()

            return jsonify({"message": "Refresh started successfully"}), 200

        except Exception as e:
            self.logger.error(f"Error triggering refresh: {e}")
            return jsonify({"error": "Failed to start refresh"}), 500

    def _handle_refresh_status(self):
        """Handle refresh status request."""
        try:
            status = self.refresh_status.copy()

            # Calculate current duration if running
            if status["running"] and status["start_time"]:
                status["duration"] = int(time.time() - status["start_time"])
            else:
                status["duration"] = (
                    int(status["duration"]) if status["duration"] else 0
                )

            return jsonify(status), 200

        except Exception as e:
            self.logger.error(f"Error getting refresh status: {e}")
            return jsonify({"error": "Failed to get refresh status"}), 500

    def _handle_get_refresh_interval(self):
        """Handle get refresh interval request."""
        try:
            config = self._load_channel_config()
            interval_hours = config.get("refresh_interval_hours", 24)

            # Get next scheduled run info
            next_run = None
            job = self.scheduler.get_job("auto_refresh")
            if job and job.next_run_time:
                next_run = job.next_run_time.isoformat()

            return jsonify(
                {"refresh_interval_hours": interval_hours, "next_run": next_run}
            ), 200

        except Exception as e:
            self.logger.error(f"Error getting refresh interval: {e}")
            return jsonify({"error": "Failed to get refresh interval"}), 500

    def _handle_update_refresh_interval(self):
        """Handle update refresh interval request."""
        try:
            data = request.get_json()
            if not data or "refresh_interval_hours" not in data:
                return jsonify({"error": "refresh_interval_hours is required"}), 400

            new_interval = data["refresh_interval_hours"]

            # Validate interval
            if not isinstance(new_interval, (int, float)) or new_interval <= 0:
                return jsonify(
                    {"error": "refresh_interval_hours must be a positive number"}
                ), 400

            # Reload config immediately before saving to ensure we have the latest state
            config = self._load_channel_config()

            # Update interval
            config["refresh_interval_hours"] = new_interval

            # Save config
            if not self._save_channel_config(config):
                return jsonify({"error": "Failed to save configuration"}), 500

            # Restart scheduler with new interval
            if not self._restart_scheduler(int(new_interval)):
                return jsonify({"error": "Failed to restart scheduler"}), 500

            # Get next scheduled run info
            next_run = None
            job = self.scheduler.get_job("auto_refresh")
            if job and job.next_run_time:
                next_run = job.next_run_time.isoformat()

            return jsonify(
                {
                    "message": "Refresh interval updated successfully",
                    "refresh_interval_hours": new_interval,
                    "next_run": next_run,
                }
            ), 200

        except Exception as e:
            self.logger.error(f"Error updating refresh interval: {e}")
            return jsonify({"error": "Internal server error"}), 500

    def _validate_display_name(
        self,
        display_name: str,
        existing_ids: Optional[List[str]] = None,
        existing_display_names: Optional[List[str]] = None,
    ) -> Tuple[bool, str, str]:
        """Validate display name and generate sanitized ID.

        Returns:
            Tuple[bool, str, str]: (is_valid, error_message, sanitized_id)
        """
        if not display_name:
            return False, "Display name cannot be empty", ""

        if not isinstance(display_name, str):
            return False, "Display name must be a string", ""

        # Check length
        if len(display_name.strip()) < 2:
            return False, "Display name must be at least 2 characters long", ""

        if len(display_name) > 100:
            return False, "Display name must be 100 characters or less", ""

        # Generate sanitized ID
        sanitized_id = sanitize_channel_name(display_name)

        if not sanitized_id:
            return (
                False,
                "Display name must contain at least some alphanumeric characters",
                "",
            )

        # Check ID uniqueness
        if existing_ids and sanitized_id in existing_ids:
            return (
                False,
                f"A channel with similar name already exists (would create same ID: {sanitized_id})",
                "",
            )

        # Check display name uniqueness
        if existing_display_names and display_name in existing_display_names:
            return False, "A channel with this display name already exists", ""

        return True, "", sanitized_id

    def _verify_youtube_channel(self, url: str) -> Tuple[bool, str, dict]:
        """Verify if YouTube channel URL is accessible and valid.

        Returns:
            Tuple[bool, str, dict]: (is_valid, error_message, channel_info)
        """
        if not url:
            return False, "YouTube URL cannot be empty", {}

        # Basic URL format validation
        if not url.startswith(("https://www.youtube.com/", "https://youtube.com/")):
            return False, "URL must be a valid YouTube channel URL", {}

        # Normalize URL to use www
        if url.startswith("https://youtube.com/"):
            url = url.replace("https://youtube.com/", "https://www.youtube.com/")

        # Check if it's a valid channel URL format
        valid_patterns = [
            r"https://www\.youtube\.com/@[\w\.-]+",
            r"https://www\.youtube\.com/c/[\w\.-]+",
            r"https://www\.youtube\.com/channel/[\w\.-]+",
            r"https://www\.youtube\.com/user/[\w\.-]+",
            r"https://www\.youtube\.com/playlist\?list=[\w\.-]+",
        ]

        if not any(re.match(pattern, url) for pattern in valid_patterns):
            return False, "Invalid YouTube channel URL format", {}

        # Try to extract channel information using yt-dlp
        try:
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
                "playlistend": 1,  # Only get first video to verify channel exists
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

                if not info:
                    return False, "Channel not found or inaccessible", {}

                # Extract channel information
                channel_info = {
                    "title": info.get("title", "Unknown"),
                    "id": info.get("id", ""),
                    "url": info.get("webpage_url", url),
                    "subscriber_count": info.get("subscriber_count"),
                    "video_count": info.get("playlist_count", 0),
                }

                return True, "", channel_info

        except yt_dlp.DownloadError as e:
            error_msg = str(e).lower()
            if "private" in error_msg or "unavailable" in error_msg:
                return False, "Channel is private or unavailable", {}
            elif "not found" in error_msg or "does not exist" in error_msg:
                return False, "Channel does not exist", {}
            else:
                return False, f"Failed to access channel: {str(e)}", {}
        except Exception as e:
            self.logger.error(f"Error verifying YouTube channel {url}: {e}")
            return False, "Unable to verify channel accessibility", {}

    def _handle_add_channel(self):
        """Handle adding a new channel."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "No data provided"}), 400

            # Validate required fields - now expecting display_name instead of name
            required_fields = ["display_name", "url"]
            for field in required_fields:
                if field not in data:
                    return jsonify({"error": f"Missing required field: {field}"}), 400

            # Load current config
            config = self._load_channel_config()
            existing_ids = [ch["name"] for ch in config.get("channels", [])]
            existing_display_names = [
                ch.get("display_name", ch["name"]) for ch in config.get("channels", [])
            ]

            # Validate display name and generate ID
            name_valid, name_error, sanitized_id = self._validate_display_name(
                data["display_name"], existing_ids, existing_display_names
            )
            if not name_valid:
                return jsonify({"error": name_error}), 400

            # Verify YouTube channel accessibility
            url_valid, url_error, channel_info = self._verify_youtube_channel(
                data["url"]
            )
            if not url_valid:
                return jsonify({"error": url_error}), 400

            # Create new channel with defaults
            new_channel = {
                "name": sanitized_id,  # This is the sanitized ID for filesystem/URL usage
                "display_name": data["display_name"],  # This is the human-readable name
                "url": data["url"],
                "max_episodes": data.get("max_episodes", 10),
                "download_delay_hours": data.get("download_delay_hours", 6),
                "format": data.get("format", "video"),
                "quality": data.get("quality", "max"),
                "sponsorblock_categories": data.get("sponsorblock_categories", []),
            }

            # Reload config to ensure we have the latest state before modifying
            config = self._load_channel_config()

            # Add to config
            if "channels" not in config:
                config["channels"] = []
            config["channels"].append(new_channel)

            # Save config
            if self._save_channel_config(config):
                response_data = {
                    "message": "Channel added successfully",
                    "channel": new_channel,
                    "channel_info": channel_info,
                }
                return jsonify(response_data), 201
            else:
                return jsonify({"error": "Failed to save configuration"}), 500

        except Exception as e:
            self.logger.error(f"Error adding channel: {e}")
            return jsonify({"error": "Internal server error"}), 500

    def _handle_update_channel(self, channel_name: str):
        """Handle updating an existing channel."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "No data provided"}), 400

            # Load current config
            config = self._load_channel_config()
            channels = config.get("channels", [])

            # Find the channel to update
            channel_index = None
            for i, channel in enumerate(channels):
                if channel["name"] == channel_name:
                    channel_index = i
                    break

            if channel_index is None:
                return jsonify({"error": "Channel not found"}), 404

            # Update channel fields
            channel = channels[channel_index]
            channel_info = {}

            if "display_name" in data:
                # Validate new display name but keep existing ID
                existing_ids = [
                    ch["name"] for i, ch in enumerate(channels) if i != channel_index
                ]
                existing_display_names = [
                    ch.get("display_name", ch["name"])
                    for i, ch in enumerate(channels)
                    if i != channel_index
                ]

                name_valid, name_error, _ = self._validate_display_name(
                    data["display_name"], existing_ids, existing_display_names
                )
                if not name_valid:
                    return jsonify({"error": name_error}), 400

                # Update display name but KEEP the existing ID
                channel["display_name"] = data["display_name"]

            if "url" in data:
                # Verify YouTube channel accessibility
                url_valid, url_error, channel_info = self._verify_youtube_channel(
                    data["url"]
                )
                if not url_valid:
                    return jsonify({"error": url_error}), 400
                channel["url"] = data["url"]
            if "max_episodes" in data:
                channel["max_episodes"] = data["max_episodes"]
            if "download_delay_hours" in data:
                channel["download_delay_hours"] = data["download_delay_hours"]
            if "format" in data:
                channel["format"] = data["format"]
            if "quality" in data:
                channel["quality"] = data["quality"]
            if "sponsorblock_categories" in data:
                channel["sponsorblock_categories"] = data["sponsorblock_categories"]

            # Reload config to ensure we have the latest state before saving
            config = self._load_channel_config()

            # Find and update the channel again in the reloaded config
            channel_index = None
            for i, ch in enumerate(config.get("channels", [])):
                if ch["name"] == channel_name:
                    channel_index = i
                    break

            if channel_index is None:
                return jsonify({"error": "Channel not found after reload"}), 404

            # Apply all the updates to the reloaded channel
            channel = config["channels"][channel_index]
            if "display_name" in data:
                # Re-validate display name against current channels
                existing_ids = [
                    ch["name"]
                    for i, ch in enumerate(config["channels"])
                    if i != channel_index
                ]
                existing_display_names = [
                    ch.get("display_name", ch["name"])
                    for i, ch in enumerate(config["channels"])
                    if i != channel_index
                ]

                name_valid, name_error, _ = self._validate_display_name(
                    data["display_name"], existing_ids, existing_display_names
                )
                if not name_valid:
                    return jsonify({"error": name_error}), 400
                channel["display_name"] = data["display_name"]
            if "url" in data:
                channel["url"] = data["url"]
            if "max_episodes" in data:
                channel["max_episodes"] = data["max_episodes"]
            if "download_delay_hours" in data:
                channel["download_delay_hours"] = data["download_delay_hours"]
            if "format" in data:
                channel["format"] = data["format"]
            if "quality" in data:
                channel["quality"] = data["quality"]
            if "sponsorblock_categories" in data:
                channel["sponsorblock_categories"] = data["sponsorblock_categories"]

            # Save config
            if self._save_channel_config(config):
                response_data = {
                    "message": "Channel updated successfully",
                    "channel": channel,
                }
                if channel_info:
                    response_data["channel_info"] = channel_info
                return jsonify(response_data), 200
            else:
                return jsonify({"error": "Failed to save configuration"}), 500

        except Exception as e:
            self.logger.error(f"Error updating channel: {e}")
            return jsonify({"error": "Internal server error"}), 500

    def _handle_delete_channel(self, channel_name: str):
        """Handle deleting a channel."""
        try:
            # Load current config
            config = self._load_channel_config()
            channels = config.get("channels", [])

            # Reload config to ensure we have the latest state before modifying
            config = self._load_channel_config()
            channels = config.get("channels", [])

            # Find and remove the channel
            original_length = len(channels)
            config["channels"] = [ch for ch in channels if ch["name"] != channel_name]

            if len(config["channels"]) == original_length:
                return jsonify({"error": "Channel not found"}), 404

            # Save config
            if self._save_channel_config(config):
                return jsonify({"message": "Channel deleted successfully"}), 200
            else:
                return jsonify({"error": "Failed to save configuration"}), 500

        except Exception as e:
            self.logger.error(f"Error deleting channel: {e}")
            return jsonify({"error": "Internal server error"}), 500

    def _handle_purge_episodes(self, channel_name: str):
        """Handle purging episodes for a channel."""
        try:
            import shutil

            # Validate channel exists in config
            config = self._load_channel_config()
            channels = config.get("channels", [])
            channel_exists = any(ch["name"] == channel_name for ch in channels)

            if not channel_exists:
                return jsonify({"error": "Channel not found"}), 404

            # Path to channel's video directory
            channel_video_dir = self.videos_dir / channel_name

            if not channel_video_dir.exists():
                return jsonify({"message": "No episodes found to purge"}), 200

            # Remove all video files and directories for this channel
            try:
                shutil.rmtree(str(channel_video_dir))
                self.logger.info(f"Purged all episodes for channel: {channel_name}")
            except FileNotFoundError:
                pass  # Directory already doesn't exist
            except Exception as e:
                self.logger.error(
                    f"Error removing channel directory {channel_video_dir}: {e}"
                )
                return jsonify({"error": "Failed to delete episode files"}), 500

            # Clear refresh timestamp for this channel
            timestamps_file = self.config_dir / "refresh_timestamps.json"
            if timestamps_file.exists():
                try:
                    with open(timestamps_file, "r", encoding="utf-8") as f:
                        timestamps = json.load(f)

                    if channel_name in timestamps:
                        del timestamps[channel_name]

                        with open(timestamps_file, "w", encoding="utf-8") as f:
                            json.dump(timestamps, f, indent=2)

                        self.logger.info(
                            f"Cleared refresh timestamp for channel: {channel_name}"
                        )
                except Exception as e:
                    self.logger.error(f"Error updating refresh timestamps: {e}")
                    # Don't fail the whole operation for this

            return jsonify(
                {
                    "message": f"Successfully purged all episodes for channel '{channel_name}'. RSS feed will reflect changes immediately."
                }
            ), 200

        except Exception as e:
            self.logger.error(f"Error purging episodes for channel {channel_name}: {e}")
            return jsonify({"error": "Internal server error"}), 500

    def _serve_index(self) -> str:
        """Generate and serve modern index page."""
        # Load channel configuration and refresh timestamps
        config = self._load_channel_config()
        channels = config.get("channels", [])
        refresh_timestamps = self._load_refresh_timestamps()

        # Prepare podcast data
        podcasts = []
        for channel in channels:
            channel_id = channel.get("name", "")
            display_name = channel.get(
                "display_name", channel_id.replace("_", " ").title()
            )
            # Use BASE_URL environment variable if set, otherwise use request host
            base_url = os.getenv("BASE_URL", request.host_url.rstrip("/"))
            feed_url = f"{base_url}/feeds/{channel_id}"

            # Get episode count for this channel (both video and audio files)
            channel_dir = self.videos_dir / channel_id
            episode_count = (
                len(get_video_files(str(channel_dir))) if channel_dir.exists() else 0
            )

            # Get last refresh time
            last_refresh_raw = refresh_timestamps.get(channel_id)
            last_refresh = (
                self._format_timestamp(last_refresh_raw) if last_refresh_raw else None
            )

            podcasts.append(
                {
                    "name": display_name,
                    "original_name": channel_id,
                    "display_name": display_name,
                    "url": channel.get("url", ""),
                    "feed_url": feed_url,
                    "episode_count": episode_count,
                    "max_episodes": channel.get("max_episodes", "N/A"),
                    "download_delay_hours": channel.get("download_delay_hours", "N/A"),
                    "format": channel.get("format", "video"),
                    "quality": channel.get("quality", "max"),
                    "sponsorblock_categories": channel.get(
                        "sponsorblock_categories", []
                    ),
                    "last_refresh": last_refresh,
                }
            )

        return render_template("index.html", podcasts=podcasts)

    def _serve_rss_feed(self, channel_name: str) -> Response:
        """Dynamically generate and serve RSS feed."""
        channel_name = secure_filename(channel_name)

        # Load channel config to get display name
        config = self._load_channel_config()
        channels = config.get("channels", [])
        channel_config = None
        for ch in channels:
            if ch["name"] == channel_name:
                channel_config = ch
                break

        if not channel_config:
            self.logger.warning(f"Channel configuration not found: {channel_name}")
            abort(404)

        # Initialize RSS generator with base URL
        base_url = os.getenv("BASE_URL", request.host_url.rstrip("/"))
        rss_generator = RSSGenerator(base_url)

        # Generate RSS feed dynamically from filesystem
        try:
            display_name = channel_config.get("display_name")
            rss_content = rss_generator.generate_rss_feed_from_filesystem(
                channel_name, self.videos_dir, display_name
            )

            # Return RSS content directly (works even with empty feeds)
            return Response(
                rss_content,
                mimetype="application/rss+xml",
                headers={"Content-Type": "application/rss+xml; charset=utf-8"},
            )

        except Exception as e:
            self.logger.error(f"Error generating RSS feed for {channel_name}: {e}")
            abort(500)

    def _serve_video_file(self, channel_name: str, filename: str) -> Response:
        """Serve episode file (video/audio) with range request support."""
        channel_name = secure_filename(channel_name)
        filename = secure_filename(filename)
        episode_file = self.videos_dir / channel_name / filename

        if not episode_file.exists():
            self.logger.warning(f"Episode file not found: {episode_file}")
            abort(404)

        # Determine MIME type based on file extension
        file_ext = episode_file.suffix.lower()
        mime_type_map = {
            ".mp4": "video/mp4",
            ".m4a": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".webm": "video/webm",
            ".mkv": "video/x-matroska",
            ".avi": "video/avi",
        }
        mime_type = mime_type_map.get(file_ext, "video/mp4")

        # Get file size
        file_size = episode_file.stat().st_size

        # Handle range requests for streaming
        range_header = request.headers.get("Range")
        if range_header:
            return self._serve_partial_content(
                episode_file, file_size, range_header, mime_type
            )
        else:
            # Serve full file
            try:
                return send_file(
                    str(episode_file), mimetype=mime_type, as_attachment=False
                )
            except Exception as e:
                self.logger.error(f"Error serving episode file {episode_file}: {e}")
                abort(500)

    def _serve_partial_content(
        self,
        file_path: Path,
        file_size: int,
        range_header: str,
        mime_type: str = "video/mp4",
    ) -> Response:
        """Serve partial content for range requests."""
        try:
            # Parse range header (e.g., "bytes=0-1023")
            range_match = range_header.replace("bytes=", "")
            range_start, range_end = range_match.split("-")

            start = int(range_start) if range_start else 0
            end = int(range_end) if range_end else file_size - 1

            # Ensure valid range
            start = max(0, start)
            end = min(file_size - 1, end)
            content_length = end - start + 1

            # Read file chunk
            with open(file_path, "rb") as f:
                f.seek(start)
                data = f.read(content_length)

            response = Response(
                data,
                206,  # Partial Content
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(content_length),
                    "Content-Type": mime_type,
                },
            )

            return response

        except Exception as e:
            self.logger.error(f"Error serving partial content: {e}")
            abort(500)

    def _serve_thumbnail_file(self, channel_name: str, filename: str) -> Response:
        """Serve thumbnail image."""
        channel_name = secure_filename(channel_name)
        filename = secure_filename(filename)
        thumbnail_file = self.videos_dir / channel_name / "thumbnails" / filename

        if not thumbnail_file.exists():
            self.logger.warning(f"Thumbnail file not found: {thumbnail_file}")
            abort(404)

        # Determine MIME type based on file extension
        mime_type, _ = mimetypes.guess_type(str(thumbnail_file))
        if not mime_type:
            mime_type = "image/jpeg"  # Default fallback

        try:
            return send_file(
                str(thumbnail_file), mimetype=mime_type, as_attachment=False
            )
        except Exception as e:
            self.logger.error(f"Error serving thumbnail {thumbnail_file}: {e}")
            abort(500)

    def run(self, debug: bool = False):
        """Start the Flask server."""
        self.logger.info(f"Starting YouTube Podcast Server on {self.host}:{self.port}")

        # Log scheduler status
        config = self._load_channel_config()
        interval_hours = config.get("refresh_interval_hours", 24)
        job = self.scheduler.get_job("auto_refresh")
        if job and job.next_run_time:
            self.logger.info(
                f"Automatic refresh scheduled every {interval_hours} hours, next run: {job.next_run_time}"
            )

        self.app.run(host=self.host, port=self.port, debug=debug)


def main():
    """Main entry point for web server."""
    server = YouTubePodcastServer()
    server.run()


if __name__ == "__main__":
    main()
