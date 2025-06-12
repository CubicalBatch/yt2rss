"""
Simplified tests for cron_runner module.

Tests the AutomationRunner class without calling yt-dlp.
Only includes tests that work reliably.
"""

import pytest
import json
import yaml
from pathlib import Path
from unittest.mock import Mock, patch, mock_open

from src.cron_runner import AutomationRunner


@pytest.fixture
def test_config():
    """Create test configuration data."""
    return {
        "channels": [
            {
                "name": "test_channel_1",
                "display_name": "Test Channel 1",
                "url": "https://www.youtube.com/@test1",
                "max_episodes": 5,
                "download_delay_hours": 6,
                "format": "audio",
                "quality": "best",
            },
            {
                "name": "test_channel_2",
                "display_name": "Test Channel 2",
                "url": "https://www.youtube.com/@test2",
                "max_episodes": 10,
                "download_delay_hours": 12,
                "format": "video",
                "quality": "480p",
                "sponsorblock_categories": ["sponsor", "selfpromo"],
            },
        ],
        "default_interval_hours": 24,
    }


@pytest.fixture
def temp_directory():
    """Create temporary directory for testing."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def automation_runner(temp_directory, test_config):
    """Create AutomationRunner instance with temporary directory."""
    # Create the expected config directory structure
    config_dir = temp_directory / "appdata" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "channels.yaml"
    with open(config_file, "w") as f:
        yaml.dump(test_config, f)

    with (
        patch.object(AutomationRunner, "setup_logging") as mock_logging,
        patch("src.cron_runner.YouTubeDownloader") as mock_downloader,
    ):
        mock_logging.return_value = Mock()
        mock_downloader.return_value = Mock()
        runner = AutomationRunner(str(temp_directory))
        # Add a mock logger since we mocked setup_logging
        runner.logger = Mock()
        return runner


class TestAutomationRunner:
    """Test AutomationRunner class functionality."""

    def test_initialization(self, automation_runner, test_config):
        """Test AutomationRunner initialization."""
        assert automation_runner.config_path is not None
        assert automation_runner.base_dir is not None
        assert automation_runner.videos_dir is not None
        assert automation_runner.lock_file_path is not None
        assert (
            not hasattr(automation_runner, "lock_file")
            or automation_runner.lock_file is None
        )

    @patch("fcntl.flock")
    @patch("builtins.open", new_callable=mock_open)
    def test_acquire_lock_success(self, mock_file, mock_flock, automation_runner):
        """Test successful lock acquisition."""
        result = automation_runner.acquire_lock()
        assert result is True
        mock_flock.assert_called_once()

    def test_validate_channel_config_valid(self, automation_runner):
        """Test validation of a valid channel configuration."""
        valid_config = {
            "name": "test_channel",
            "url": "https://www.youtube.com/@test",
            "max_episodes": 10,
        }
        result = automation_runner.validate_channel_config(valid_config)
        assert result is True

    def test_validate_channel_config_missing_name(self, automation_runner):
        """Test validation with missing name."""
        invalid_config = {
            "url": "https://www.youtube.com/@test",
            "max_episodes": 10,
        }
        result = automation_runner.validate_channel_config(invalid_config)
        assert result is False

    def test_validate_channel_config_missing_url(self, automation_runner):
        """Test validation with missing URL."""
        invalid_config = {
            "name": "test_channel",
            "max_episodes": 10,
        }
        result = automation_runner.validate_channel_config(invalid_config)
        assert result is False

    def test_validate_channel_config_invalid_max_episodes(self, automation_runner):
        """Test validation with invalid max_episodes."""
        invalid_config = {
            "name": "test_channel",
            "url": "https://www.youtube.com/@test",
            "max_episodes": "invalid",
        }
        result = automation_runner.validate_channel_config(invalid_config)
        assert result is False

    def test_cleanup_old_videos_no_cleanup_needed(
        self, automation_runner, temp_directory
    ):
        """Test cleanup when no cleanup is needed."""
        # Create test directory with recent episodes
        channel_dir = temp_directory / "appdata" / "podcasts" / "test_channel"
        channel_dir.mkdir(parents=True, exist_ok=True)

        # Create recent episodes (should not be cleaned up)
        for i in range(3):
            episode_data = {"id": f"recent{i}", "upload_date": "20241201"}
            (channel_dir / f"recent{i}.json").write_text(json.dumps(episode_data))
            (channel_dir / f"recent{i}.m4a").write_text("audio data")

        # Should not clean up any files
        automation_runner.cleanup_old_videos("test_channel", 5)

        # Verify all files still exist
        remaining_count = len(list(channel_dir.glob("*.json")))
        assert remaining_count == 3

    def test_cleanup_old_videos_nonexistent_channel(self, automation_runner):
        """Test cleanup for nonexistent channel."""
        # Should not raise exception
        automation_runner.cleanup_old_videos("nonexistent_channel", 5)

    @patch("src.cron_runner.AutomationRunner.acquire_lock")
    def test_run_lock_failure(self, mock_acquire, automation_runner):
        """Test run when lock acquisition fails."""
        mock_acquire.return_value = False
        result = automation_runner.run()
        assert result == 1


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_cleanup_with_corrupted_metadata(self, automation_runner, temp_directory):
        """Test cleanup with corrupted metadata files."""
        channel_dir = temp_directory / "appdata" / "podcasts" / "test_channel"
        channel_dir.mkdir(parents=True, exist_ok=True)

        # Create corrupted metadata file
        (channel_dir / "corrupted.json").write_text("invalid json content")
        (channel_dir / "corrupted.m4a").write_text("audio data")

        # Should not raise exception
        automation_runner.cleanup_old_videos("test_channel", 1)

    def test_file_system_errors_during_cleanup(self, automation_runner, temp_directory):
        """Test cleanup with file system errors."""
        channel_dir = temp_directory / "appdata" / "podcasts" / "test_channel"
        channel_dir.mkdir(parents=True, exist_ok=True)

        # Create test files
        episode_data = {"id": "test", "upload_date": "20241101"}
        (channel_dir / "test.json").write_text(json.dumps(episode_data))
        (channel_dir / "test.m4a").write_text("audio data")

        # Mock file removal to raise permission error
        with patch("pathlib.Path.unlink", side_effect=PermissionError("Access denied")):
            # Should not raise exception
            automation_runner.cleanup_old_videos("test_channel", 1)
