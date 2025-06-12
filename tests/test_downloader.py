"""Tests for the YouTube downloader module."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
import pytest
import yaml

from src.downloader import YouTubeDownloader


class TestYouTubeDownloader:
    """Test cases for YouTubeDownloader class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def mock_config(self):
        """Mock configuration data."""
        return {
            "channels": [
                {
                    "name": "test-channel",
                    "url": "https://www.youtube.com/channel/UC123",
                    "max_episodes": 5,
                    "sponsorblock_categories": ["sponsor"],
                    "download_delay_hours": 24,
                    "format": "video",
                    "quality": "480p",
                }
            ],
            "download_delay_seconds": 30,
        }

    @pytest.fixture
    def downloader(self, temp_dir):
        """Create YouTubeDownloader instance with temp directory."""
        config_path = Path(temp_dir) / "config.yaml"
        with patch("src.downloader.RSSGenerator"):
            return YouTubeDownloader(str(config_path), temp_dir)

    def test_init(self, temp_dir):
        """Test YouTubeDownloader initialization."""
        config_path = Path(temp_dir) / "config.yaml"

        with patch("src.downloader.RSSGenerator") as mock_rss:
            downloader = YouTubeDownloader(str(config_path), temp_dir)

            assert downloader.config_path == str(config_path)
            assert downloader.base_dir == Path(temp_dir)
            assert downloader.videos_dir == Path(temp_dir) / "appdata" / "podcasts"
            assert downloader.videos_dir.exists()
            mock_rss.assert_called_once()

    def test_load_config_success(self, downloader, temp_dir, mock_config):
        """Test successful config loading."""
        config_path = Path(temp_dir) / "config.yaml"

        with open(config_path, "w") as f:
            yaml.dump(mock_config, f)

        downloader.config_path = str(config_path)
        channels, global_config = downloader.load_config()

        assert len(channels) == 1
        assert channels[0]["name"] == "test-channel"
        assert global_config["download_delay_seconds"] == 30

    def test_load_config_file_not_found(self, downloader):
        """Test config loading when file doesn't exist."""
        downloader.config_path = "nonexistent.yaml"

        channels, global_config = downloader.load_config()

        assert channels == []
        assert global_config == {}

    def test_load_config_invalid_yaml(self, downloader, temp_dir):
        """Test config loading with invalid YAML."""
        config_path = Path(temp_dir) / "config.yaml"

        with open(config_path, "w") as f:
            f.write("invalid: yaml: content: {")

        downloader.config_path = str(config_path)
        channels, global_config = downloader.load_config()

        assert channels == []
        assert global_config == {}

    @patch("src.downloader.yt_dlp.YoutubeDL")
    def test_get_channel_videos_success(self, mock_ytdl, downloader):
        """Test successful channel video retrieval."""
        mock_info = {
            "entries": [
                {
                    "id": "video1",
                    "title": "Test Video 1",
                    "upload_date": "20231201",
                    "duration": 300,
                },
                {
                    "id": "video2",
                    "title": "Test Video 2",
                    "upload_date": "20231202",
                    "duration": 600,
                },
            ]
        }

        mock_ytdl_instance = Mock()
        mock_ytdl_instance.extract_info.return_value = mock_info
        mock_ytdl.return_value.__enter__.return_value = mock_ytdl_instance

        videos = downloader.get_channel_videos("https://youtube.com/channel/UC123", 5)

        assert len(videos) == 2
        assert videos[0]["id"] == "video1"
        assert videos[0]["title"] == "Test Video 1"
        assert videos[0]["url"] == "https://www.youtube.com/watch?v=video1"
        assert videos[1]["id"] == "video2"

    @patch("src.downloader.yt_dlp.YoutubeDL")
    def test_get_channel_videos_no_entries(self, mock_ytdl, downloader):
        """Test channel video retrieval with no entries."""
        mock_ytdl_instance = Mock()
        mock_ytdl_instance.extract_info.return_value = {"entries": []}
        mock_ytdl.return_value.__enter__.return_value = mock_ytdl_instance

        videos = downloader.get_channel_videos("https://youtube.com/channel/UC123")

        assert videos == []

    @patch("src.downloader.yt_dlp.YoutubeDL")
    def test_get_channel_videos_exception(self, mock_ytdl, downloader):
        """Test channel video retrieval with exception."""
        mock_ytdl_instance = Mock()
        mock_ytdl_instance.extract_info.side_effect = Exception("Network error")
        mock_ytdl.return_value.__enter__.return_value = mock_ytdl_instance

        videos = downloader.get_channel_videos("https://youtube.com/channel/UC123")

        assert videos == []

    @patch("src.downloader.yt_dlp.YoutubeDL")
    def test_get_video_metadata_success(self, mock_ytdl, downloader):
        """Test successful video metadata retrieval."""
        mock_info = {
            "id": "video123",
            "title": "Test Video",
            "upload_date": "20231201",
            "duration": 300,
        }

        mock_ytdl_instance = Mock()
        mock_ytdl_instance.extract_info.return_value = mock_info
        mock_ytdl.return_value.__enter__.return_value = mock_ytdl_instance

        metadata = downloader.get_video_metadata("https://youtube.com/watch?v=video123")

        assert metadata["id"] == "video123"
        assert metadata["title"] == "Test Video"
        assert metadata["url"] == "https://youtube.com/watch?v=video123"

    @patch("src.downloader.yt_dlp.YoutubeDL")
    def test_get_video_metadata_exception(self, mock_ytdl, downloader):
        """Test video metadata retrieval with exception."""
        mock_ytdl_instance = Mock()
        mock_ytdl_instance.extract_info.side_effect = Exception("Network error")
        mock_ytdl.return_value.__enter__.return_value = mock_ytdl_instance

        metadata = downloader.get_video_metadata("https://youtube.com/watch?v=video123")

        assert metadata == {}

    def test_video_exists_true(self, downloader, temp_dir):
        """Test video_exists when video and metadata files exist."""
        channel_dir = Path(temp_dir) / "appdata" / "podcasts" / "test-channel"
        channel_dir.mkdir(parents=True)

        # Create video and metadata files
        (channel_dir / "video123.mp4").touch()
        (channel_dir / "video123.json").touch()

        assert downloader.video_exists("test-channel", "video123", "video")

    def test_video_exists_audio_format(self, downloader, temp_dir):
        """Test video_exists for audio format."""
        channel_dir = Path(temp_dir) / "appdata" / "podcasts" / "test-channel"
        channel_dir.mkdir(parents=True)

        # Create audio and metadata files
        (channel_dir / "video123.m4a").touch()
        (channel_dir / "video123.json").touch()

        assert downloader.video_exists("test-channel", "video123", "audio")

    def test_video_exists_false_missing_video(self, downloader, temp_dir):
        """Test video_exists when video file is missing."""
        channel_dir = Path(temp_dir) / "appdata" / "podcasts" / "test-channel"
        channel_dir.mkdir(parents=True)

        # Create only metadata file
        (channel_dir / "video123.json").touch()

        assert not downloader.video_exists("test-channel", "video123", "video")

    def test_video_exists_false_missing_metadata(self, downloader, temp_dir):
        """Test video_exists when metadata file is missing."""
        channel_dir = Path(temp_dir) / "appdata" / "podcasts" / "test-channel"
        channel_dir.mkdir(parents=True)

        # Create only video file
        (channel_dir / "video123.mp4").touch()

        assert not downloader.video_exists("test-channel", "video123", "video")

    def test_is_video_too_new_true(self, downloader):
        """Test is_video_too_new returns True for recent video."""
        # Video uploaded 1 hour ago
        upload_date = (datetime.now() - timedelta(hours=1)).strftime("%Y%m%d")
        video_info = {"upload_date": upload_date}

        assert downloader.is_video_too_new(video_info, 24)

    def test_is_video_too_new_false(self, downloader):
        """Test is_video_too_new returns False for old video."""
        # Video uploaded 2 days ago
        upload_date = (datetime.now() - timedelta(days=2)).strftime("%Y%m%d")
        video_info = {"upload_date": upload_date}

        assert not downloader.is_video_too_new(video_info, 24)

    def test_is_video_too_new_no_delay(self, downloader):
        """Test is_video_too_new returns False when delay is 0."""
        video_info = {"upload_date": "20231201"}

        assert not downloader.is_video_too_new(video_info, 0)

    def test_is_video_too_new_invalid_date(self, downloader):
        """Test is_video_too_new with invalid date format."""
        video_info = {"upload_date": "invalid-date"}

        assert not downloader.is_video_too_new(video_info, 24)

    def test_is_video_too_new_missing_date(self, downloader):
        """Test is_video_too_new with missing upload date."""
        video_info = {}

        assert not downloader.is_video_too_new(video_info, 24)

    @patch("src.downloader.yt_dlp.YoutubeDL")
    @patch("src.downloader.Image")
    def test_download_video_success(self, mock_image, mock_ytdl, downloader, temp_dir):
        """Test successful video download."""
        video_info = {
            "id": "video123",
            "title": "Test Video",
            "url": "https://youtube.com/watch?v=video123",
        }

        # Mock yt-dlp
        mock_ytdl_instance = Mock()
        mock_ytdl.return_value.__enter__.return_value = mock_ytdl_instance

        # Create mock files that would be created by yt-dlp
        channel_dir = Path(temp_dir) / "appdata" / "podcasts" / "test-channel"
        channel_dir.mkdir(parents=True)
        thumbnails_dir = channel_dir / "thumbnails"
        thumbnails_dir.mkdir(parents=True)

        # Create mock metadata file
        metadata = {
            "title": "Test Video",
            "description": "Test description",
            "upload_date": "20231201",
            "duration": 300,
            "filesize": 1000000,
            "uploader": "Test Channel",
            "view_count": 1000,
        }

        metadata_file = channel_dir / "video123.info.json"
        with open(metadata_file, "w") as f:
            json.dump(metadata, f)

        # Create mock thumbnail
        thumbnail_file = channel_dir / "video123.jpg"
        thumbnail_file.touch()

        result = downloader.download_video(
            video_info, "test-channel", ["sponsor"], "video", "480p"
        )

        assert result is True
        mock_ytdl_instance.download.assert_called_once()

        # Check simplified metadata was created
        simple_metadata_file = channel_dir / "video123.json"
        assert simple_metadata_file.exists()

        with open(simple_metadata_file) as f:
            simple_metadata = json.load(f)

        assert simple_metadata["id"] == "video123"
        assert simple_metadata["title"] == "Test Video"

    @patch("src.downloader.yt_dlp.YoutubeDL")
    def test_download_video_exception(self, mock_ytdl, downloader):
        """Test video download with exception."""
        video_info = {
            "id": "video123",
            "title": "Test Video",
            "url": "https://youtube.com/watch?v=video123",
        }

        mock_ytdl_instance = Mock()
        mock_ytdl_instance.download.side_effect = Exception("Download failed")
        mock_ytdl.return_value.__enter__.return_value = mock_ytdl_instance

        result = downloader.download_video(video_info, "test-channel")

        assert result is False

    @patch.object(YouTubeDownloader, "get_channel_videos")
    @patch.object(YouTubeDownloader, "get_video_metadata")
    @patch.object(YouTubeDownloader, "video_exists")
    @patch.object(YouTubeDownloader, "is_video_too_new")
    @patch.object(YouTubeDownloader, "download_video")
    @patch("time.sleep")
    def test_process_channel_success(
        self,
        mock_sleep,
        mock_download,
        mock_too_new,
        mock_exists,
        mock_metadata,
        mock_get_videos,
        downloader,
    ):
        """Test successful channel processing."""
        channel_config = {
            "name": "test-channel",
            "url": "https://youtube.com/channel/UC123",
            "max_episodes": 2,
            "sponsorblock_categories": ["sponsor"],
            "download_delay_hours": 0,
            "format": "video",
            "quality": "480p",
        }
        global_config = {"download_delay_seconds": 30}

        # Mock video list
        videos = [
            {
                "id": "video1",
                "title": "Video 1",
                "url": "https://youtube.com/watch?v=video1",
            },
            {
                "id": "video2",
                "title": "Video 2",
                "url": "https://youtube.com/watch?v=video2",
            },
        ]
        mock_get_videos.return_value = videos

        # Mock detailed metadata
        mock_metadata.side_effect = [
            {"id": "video1", "title": "Video 1", "upload_date": "20231201"},
            {"id": "video2", "title": "Video 2", "upload_date": "20231202"},
        ]

        # Mock video doesn't exist and isn't too new
        mock_exists.return_value = False
        mock_too_new.return_value = False

        # Mock successful downloads
        mock_download.return_value = True

        result = downloader.process_channel(channel_config, global_config)

        assert result == 2
        assert mock_download.call_count == 2
        assert mock_sleep.call_count == 1  # Sleep between downloads

    @patch.object(YouTubeDownloader, "get_channel_videos")
    def test_process_channel_no_videos(self, mock_get_videos, downloader):
        """Test channel processing with no videos found."""
        channel_config = {
            "name": "test-channel",
            "url": "https://youtube.com/channel/UC123",
        }
        global_config = {}

        mock_get_videos.return_value = []

        result = downloader.process_channel(channel_config, global_config)

        assert result == 0

    @patch.object(YouTubeDownloader, "load_config")
    @patch.object(YouTubeDownloader, "process_channel")
    def test_process_all_channels_success(self, mock_process, mock_load, downloader):
        """Test processing all channels successfully."""
        channels = [
            {"name": "channel1", "url": "https://youtube.com/channel/UC1"},
            {"name": "channel2", "url": "https://youtube.com/channel/UC2"},
        ]
        global_config = {"download_delay_seconds": 30}

        mock_load.return_value = (channels, global_config)
        mock_process.side_effect = [3, 2]  # Return download counts

        result = downloader.process_all_channels()

        assert result == 5
        assert mock_process.call_count == 2

    @patch.object(YouTubeDownloader, "load_config")
    def test_process_all_channels_no_config(self, mock_load, downloader):
        """Test processing all channels with no configuration."""
        mock_load.return_value = ([], {})

        result = downloader.process_all_channels()

        assert result == 0

    @patch.object(YouTubeDownloader, "load_config")
    @patch.object(YouTubeDownloader, "process_channel")
    def test_process_all_channels_with_exception(
        self, mock_process, mock_load, downloader
    ):
        """Test processing all channels with exception in one channel."""
        channels = [
            {"name": "channel1", "url": "https://youtube.com/channel/UC1"},
            {"name": "channel2", "url": "https://youtube.com/channel/UC2"},
        ]
        global_config = {}

        mock_load.return_value = (channels, global_config)
        mock_process.side_effect = [Exception("Process failed"), 2]

        result = downloader.process_all_channels()

        assert result == 2  # Only successful channel counted
        assert mock_process.call_count == 2
