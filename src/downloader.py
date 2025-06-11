import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import yt_dlp
import yaml
from PIL import Image


from rss_generator import RSSGenerator


class YouTubeDownloader:
    def __init__(self, config_path: str = "appdata/config/channels.yaml", base_dir: str = "."):
        self.config_path = config_path
        self.base_dir = Path(base_dir)
        self.videos_dir = self.base_dir / "appdata" / "podcasts"

        # Ensure directories exist
        self.videos_dir.mkdir(exist_ok=True)

        # Setup logging
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", handlers=[logging.StreamHandler()]
        )
        self.logger = logging.getLogger(__name__)

        # Initialize RSS generator for timestamp updates
        self.rss_generator = RSSGenerator()

    def load_config(self) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Load channel configuration from YAML file."""
        try:
            with open(self.config_path, "r") as f:
                config = yaml.safe_load(f)
                channels = config.get("channels", [])
                global_config = {k: v for k, v in config.items() if k != "channels"}
                return channels, global_config
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            return [], {}

    def get_channel_videos(self, channel_url: str, max_episodes: int = 10) -> List[Dict[str, Any]]:
        """Get video information from a YouTube channel."""
        self.logger.info(f"📡 Fetching video list from channel (max {max_episodes} episodes)...")

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "playlist_items": f"1:{max_episodes}",
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)

                if not info or "entries" not in info:
                    self.logger.warning(f"❌ No videos found for channel: {channel_url}")
                    return []

                videos = []
                for entry in info["entries"] if info else []:
                    if entry:
                        videos.append(
                            {
                                "id": entry.get("id"),
                                "title": entry.get("title"),
                                "url": f"https://www.youtube.com/watch?v={entry.get('id')}",
                                "upload_date": entry.get("upload_date"),
                                "duration": entry.get("duration"),
                            }
                        )

                self.logger.info(f"✅ Found {len(videos)} videos in channel")
                return videos

        except Exception as e:
            self.logger.error(f"Failed to get channel videos: {e}")
            return []

    def get_video_metadata(self, video_url: str) -> Dict[str, Any]:
        """Get detailed metadata for a single video."""
        ydl_opts = {"quiet": True, "no_warnings": True}

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                if info:
                    return {
                        "id": info.get("id"),
                        "title": info.get("title"),
                        "upload_date": info.get("upload_date"),
                        "duration": info.get("duration"),
                        "url": video_url,
                    }
                else:
                    return {}
        except Exception as e:
            self.logger.error(f"Failed to get video metadata for {video_url}: {e}")
            return {}

    def video_exists(self, channel_name: str, video_id: str, format_type: str = "video") -> bool:
        """Check if video has already been downloaded."""
        channel_dir = self.videos_dir / channel_name

        # Check for different file extensions based on format
        if format_type == "audio":
            video_file = channel_dir / f"{video_id}.m4a"
        else:
            video_file = channel_dir / f"{video_id}.mp4"

        metadata_file = channel_dir / f"{video_id}.json"

        return video_file.exists() and metadata_file.exists()

    def is_video_too_new(self, video_info: Dict[str, Any], download_delay_hours: int) -> bool:
        """Check if video is too new based on download_delay_hours."""
        if download_delay_hours <= 0:
            return False

        upload_date_str = video_info.get("upload_date")
        if not upload_date_str:
            return False

        try:
            # Parse upload date (format: YYYYMMDD)
            upload_date = datetime.strptime(upload_date_str, "%Y%m%d")

            # Calculate minimum age required
            min_age = timedelta(hours=download_delay_hours)
            current_time = datetime.now()

            # Check if video is too new
            video_age = current_time - upload_date
            return video_age < min_age

        except (ValueError, TypeError) as e:
            self.logger.warning(f"Failed to parse upload date {upload_date_str}: {e}")
            return False

    def download_video(
        self,
        video_info: Dict[str, Any],
        channel_name: str,
        sponsorblock_categories: Optional[List[str]] = None,
        format_type: str = "video",
        quality: str = "max",
    ) -> bool:
        """Download a single video with SponsorBlock integration."""
        video_id = video_info["id"]
        video_url = video_info["url"]
        video_title = video_info.get("title", "Unknown Title")

        self.logger.info(f"\n🎬 Starting download: {video_title}")
        self.logger.info(f"   📺 Video ID: {video_id}")
        self.logger.info(f"   🎯 Format: {format_type}")
        self.logger.info(f"   🔧 Quality: {quality}")

        if sponsorblock_categories:
            self.logger.info(f"   🚫 SponsorBlock categories: {', '.join(sponsorblock_categories)}")

        # Create channel directory
        channel_dir = self.videos_dir / channel_name
        channel_dir.mkdir(exist_ok=True)

        # Create thumbnails subdirectory
        thumbnails_dir = channel_dir / "thumbnails"
        thumbnails_dir.mkdir(exist_ok=True)

        # Configure format string based on format_type and quality
        if format_type == "audio":
            format_string = "bestaudio[ext=m4a]/bestaudio"
            self.logger.info(f"   🎵 Audio format selected: {format_string}")
        else:  # video
            if quality == "480p":
                format_string = "best[height<=480][ext=mp4]/best[ext=mp4]/best"
                self.logger.info(f"   📹 Video format selected: 480p (format: {format_string})")
            else:  # max quality
                format_string = "best[ext=mp4]/best"
                self.logger.info(f"   📹 Video format selected: max quality (format: {format_string})")

        # Configure yt-dlp options
        ydl_opts = {
            "outtmpl": str(channel_dir / f"{video_id}.%(ext)s"),
            "format": format_string,
            "writeinfojson": True,
            "writethumbnail": True,
            "writedescription": False,
            "writesubtitles": False,
            "writeautomaticsub": False,
        }

        # Add SponsorBlock postprocessor if categories specified
        if sponsorblock_categories:
            ydl_opts["postprocessors"] = [
                {
                    "key": "SponsorBlock",
                    "categories": sponsorblock_categories,
                    "when": "after_move",
                },
                {
                    "key": "ModifyChapters",
                    "remove_sponsor_segments": sponsorblock_categories,
                    "when": "after_move",
                },
            ]

        try:
            self.logger.info("   ⬇️  Downloading video file...")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])

            self.logger.info("   ✅ Video download completed")

            # Move thumbnail to thumbnails directory and convert WebP to JPG
            thumbnail_extensions = [".jpg", ".jpeg", ".png", ".webp"]
            final_thumbnail_ext = None
            for ext in thumbnail_extensions:
                thumbnail_path = channel_dir / f"{video_id}{ext}"
                if thumbnail_path.exists():
                    if ext == ".webp":
                        # Convert WebP to JPG for iTunes compatibility
                        jpg_path = thumbnails_dir / f"{video_id}.jpg"
                        try:
                            self.logger.info("   🖼️  Converting WebP thumbnail to JPG...")
                            with Image.open(thumbnail_path) as img:
                                # Convert to RGB if necessary (WebP can have transparency)
                                if img.mode in ("RGBA", "LA", "P"):
                                    rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                                    if img.mode == "P":
                                        img = img.convert("RGBA")
                                    rgb_img.paste(
                                        img,
                                        mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None,
                                    )
                                    img = rgb_img
                                img.save(jpg_path, "JPEG", quality=90)
                            thumbnail_path.unlink()  # Remove original WebP
                            final_thumbnail_ext = ".jpg"
                            self.logger.info("   ✅ Thumbnail converted to JPG")
                        except Exception as e:
                            self.logger.error(f"Failed to convert WebP thumbnail for {video_id}: {e}")
                            # Fallback: move WebP as-is
                            new_thumbnail_path = thumbnails_dir / f"{video_id}{ext}"
                            thumbnail_path.rename(new_thumbnail_path)
                            final_thumbnail_ext = ext
                    else:
                        # Move non-WebP thumbnails as-is
                        new_thumbnail_path = thumbnails_dir / f"{video_id}{ext}"
                        thumbnail_path.rename(new_thumbnail_path)
                        final_thumbnail_ext = ext
                    break

            # Load and enhance metadata
            metadata_file = channel_dir / f"{video_id}.info.json"
            if metadata_file.exists():
                with open(metadata_file, "r") as f:
                    metadata = json.load(f)

                # Create simplified metadata file
                simplified_metadata = {
                    "id": video_id,
                    "title": metadata.get("title"),
                    "description": metadata.get("description", ""),
                    "upload_date": metadata.get("upload_date"),
                    "duration": metadata.get("duration"),
                    "thumbnail": f"thumbnails/{video_id}{final_thumbnail_ext}" if final_thumbnail_ext else None,
                    "file_size": metadata.get("filesize", 0),
                    "uploader": metadata.get("uploader"),
                    "view_count": metadata.get("view_count", 0),
                }

                # Save simplified metadata
                simple_metadata_file = channel_dir / f"{video_id}.json"
                with open(simple_metadata_file, "w") as f:
                    json.dump(simplified_metadata, f, indent=2)

                # Remove the detailed info.json file
                metadata_file.unlink()

            self.logger.info(f"🎉 Successfully downloaded: {video_title}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Failed to download: {video_title} - {e}")
            return False

    def process_channel(self, channel_config: Dict[str, Any], global_config: Dict[str, Any]) -> int:
        """Process a single channel configuration."""
        channel_name = channel_config["name"]
        channel_url = channel_config["url"]
        max_episodes = channel_config.get("max_episodes", 10)
        sponsorblock_categories = channel_config.get("sponsorblock_categories", [])
        download_delay_hours = channel_config.get("download_delay_hours", 0)
        download_delay_seconds = global_config.get("download_delay_seconds", 20)  # Default 20 seconds
        format_type = channel_config.get("format", "video")  # Default to video
        quality = channel_config.get("quality", "max")  # Default to max quality

        self.logger.info(f"\n📻 Processing channel: {channel_name}")
        self.logger.info(f"   🔗 URL: {channel_url}")
        self.logger.info(f"   📊 Max episodes: {max_episodes}")
        self.logger.info(f"   🎯 Format: {format_type}")
        self.logger.info(f"   🔧 Quality: {quality}")
        self.logger.info(f"   ⏰ Download delay: {download_delay_seconds}s between episodes")
        if download_delay_hours > 0:
            self.logger.info(f"   ⌛ Skip videos newer than: {download_delay_hours} hours")

        # Get video list
        videos = self.get_channel_videos(channel_url, max_episodes)
        if not videos:
            self.logger.warning(f"⚠️  No videos found for channel: {channel_name}")
            return 0

        # Download videos
        downloaded_count = 0
        self.logger.info(f"\n🔍 Checking {len(videos)} videos for download...")

        for i, video in enumerate(videos, 1):
            video_id = video["id"]
            video_title = video.get("title", "Unknown Title")

            self.logger.info(f"\n[{i}/{len(videos)}] 🔎 Checking: {video_title}")

            # Check if already downloaded
            if self.video_exists(channel_name, video_id, format_type):
                self.logger.info("   ⏭️  Already downloaded, skipping")
                continue

            # Get detailed metadata to check upload date
            self.logger.info("   📊 Fetching detailed metadata...")
            detailed_metadata = self.get_video_metadata(video["url"])
            if not detailed_metadata:
                self.logger.warning("   ❌ Failed to get metadata, skipping")
                continue

            # Update video info with detailed metadata
            video.update(detailed_metadata)

            # Check if video is too new
            if self.is_video_too_new(video, download_delay_hours):
                self.logger.info(f"   ⌛ Video too new (< {download_delay_hours}h old), skipping for SponsorBlock data")
                continue

            # Download the video
            self.logger.info("   ▶️  Starting download...")
            if self.download_video(video, channel_name, sponsorblock_categories, format_type, quality):
                downloaded_count += 1

                # Add delay between downloads to avoid rate limiting
                if download_delay_seconds > 0 and i < len(videos):
                    self.logger.info(f"   ⏸️  Waiting {download_delay_seconds}s before next download...")
                    time.sleep(download_delay_seconds)

        self.logger.info("\n✨ Channel processing complete!")
        self.logger.info(f"   📥 Downloaded: {downloaded_count} new episodes")
        self.logger.info(f"   📻 Channel: {channel_name}")

        # Update refresh timestamp for this channel
        self.rss_generator.update_channel_refresh_time(channel_name)

        return downloaded_count

    def process_all_channels(self) -> int:
        """Process all configured channels."""
        channels, global_config = self.load_config()
        if not channels:
            self.logger.error("No channels configured")
            return 0

        total_downloaded = 0
        for channel_config in channels:
            try:
                downloaded = self.process_channel(channel_config, global_config)
                total_downloaded += downloaded
            except Exception as e:
                self.logger.error(f"Failed to process channel {channel_config.get('name', 'unknown')}: {e}")
                continue

        self.logger.info(f"Total videos downloaded: {total_downloaded}")
        return total_downloaded


if __name__ == "__main__":
    downloader = YouTubeDownloader()
    downloader.process_all_channels()
