import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, List


def setup_logging() -> logging.Logger:
    """Setup logging configuration to stdout only."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )

    return logging.getLogger(__name__)


def ensure_directory(path: str) -> Path:
    """Ensure directory exists and return Path object."""
    dir_path = Path(path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def load_json_file(file_path: str) -> Dict[str, Any]:
    """Load JSON file and return data."""
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Failed to load JSON file {file_path}: {e}")
        return {}


def save_json_file(data: Dict[str, Any], file_path: str) -> bool:
    """Save data to JSON file."""
    try:
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logging.error(f"Failed to save JSON file {file_path}: {e}")
        return False


def get_episode_files(channel_dir: str) -> List[Dict[str, Any]]:
    """Get all episode files (video/audio) and metadata from channel directory."""
    channel_path = Path(channel_dir)
    if not channel_path.exists():
        return []

    episodes = []
    # Support both video and audio file extensions
    supported_extensions = [".mp4", ".m4a", ".mp3", ".webm", ".mkv", ".avi"]

    for json_file in channel_path.glob("*.json"):
        episode_id = json_file.stem
        episode_file = None

        # Check for episode file with any supported extension
        for ext in supported_extensions:
            potential_file = channel_path / f"{episode_id}{ext}"
            if potential_file.exists():
                episode_file = potential_file
                break

        if episode_file and episode_file.exists():
            metadata = load_json_file(str(json_file))
            if metadata:
                metadata["file_path"] = str(episode_file)
                episodes.append(metadata)

    # Sort by upload date (newest first)
    episodes.sort(key=lambda x: x.get("upload_date", ""), reverse=True)
    return episodes


def get_video_files(channel_dir: str) -> List[Dict[str, Any]]:
    """Legacy function name for backward compatibility."""
    return get_episode_files(channel_dir)


def clean_filename(filename: str) -> str:
    """Clean filename for filesystem compatibility."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, "_")
    return filename.strip()


def format_duration(seconds: int) -> str:
    """Format duration in seconds to human readable format."""
    if not seconds:
        return "Unknown"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"


def get_file_size_mb(file_path: str) -> float:
    """Get file size in MB."""
    try:
        size_bytes = os.path.getsize(file_path)
        return round(size_bytes / (1024 * 1024), 2)
    except Exception:
        return 0.0


def sanitize_channel_name(display_name: str) -> str:
    """Sanitize display name to create a valid channel ID for filesystem usage.

    Args:
        display_name: The display name that may contain spaces and special characters

    Returns:
        A sanitized string safe for use as filesystem directory names and URLs
    """
    if not display_name:
        return ""

    import re

    # Convert to lowercase
    sanitized = display_name.lower()

    # Replace spaces and common separators with underscores
    sanitized = re.sub(r"[\s\-\.]+", "_", sanitized)

    # Remove any characters that aren't alphanumeric or underscores
    sanitized = re.sub(r"[^a-z0-9_]", "", sanitized)

    # Remove leading/trailing underscores and collapse multiple underscores
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")

    # Ensure minimum length
    if len(sanitized) < 2:
        sanitized = f"channel_{sanitized}" if sanitized else "channel"

    return sanitized
