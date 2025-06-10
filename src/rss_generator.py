import json
import logging
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict
from urllib.parse import quote
import html
from feedgen.feed import FeedGenerator


class RSSGenerator:
    def __init__(self, base_url: str = None):
        if base_url is None:
            base_url = os.getenv('BASE_URL', 'http://localhost:5000')
        self.base_url = base_url.rstrip('/')
        self.logger = logging.getLogger(__name__)
        self.refresh_timestamps_file = Path(__file__).parent.parent / "appdata" / "config" / "refresh_timestamps.json"
        
    def sanitize_text(self, text: str) -> str:
        """Sanitize text for XML content"""
        if not text:
            return ""
        # Escape HTML entities and strip problematic control characters
        sanitized = html.escape(str(text), quote=False)
        # Remove or replace control characters that are invalid in XML
        sanitized = ''.join(char for char in sanitized if ord(char) >= 32 or char in '\t\n\r')
        return sanitized
        
    def format_duration(self, duration) -> str:
        """Convert duration to HH:MM:SS format"""
        if isinstance(duration, str):
            # If already in HH:MM:SS format, return as is
            if ':' in duration:
                return duration
            # If it's a string number, convert to int
            try:
                duration = int(float(duration))
            except (ValueError, TypeError):
                return "00:00:00"
        
        if isinstance(duration, (int, float)):
            # Convert seconds to HH:MM:SS
            hours = int(duration // 3600)
            minutes = int((duration % 3600) // 60)
            seconds = int(duration % 60)
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        
        return "00:00:00"
        
    def load_refresh_timestamps(self) -> Dict[str, str]:
        """Load refresh timestamps from file"""
        if not self.refresh_timestamps_file.exists():
            return {}
        try:
            with open(self.refresh_timestamps_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            self.logger.error(f"Error loading refresh timestamps: {e}")
            return {}
    
    def save_refresh_timestamps(self, timestamps: Dict[str, str]):
        """Save refresh timestamps to file"""
        try:
            with open(self.refresh_timestamps_file, 'w', encoding='utf-8') as f:
                json.dump(timestamps, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving refresh timestamps: {e}")
    
    def update_channel_refresh_time(self, channel_name: str):
        """Update the last refresh time for a channel"""
        timestamps = self.load_refresh_timestamps()
        timestamps[channel_name] = datetime.now(timezone.utc).isoformat()
        self.save_refresh_timestamps(timestamps)
        self.logger.info(f"Updated refresh timestamp for {channel_name}")
        
    def scan_channel_videos(self, channel_path: Path) -> List[Dict]:
        """Scan episode directory and extract metadata from JSON files"""
        episodes = []
        
        if not channel_path.exists():
            self.logger.warning(f"Channel path does not exist: {channel_path}")
            return episodes
            
        # Support both video and audio file extensions
        supported_extensions = ['.mp4', '.m4a', '.mp3', '.webm', '.mkv', '.avi']
            
        # Find all JSON metadata files
        for json_file in channel_path.glob("*.json"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                
                # Check for episode file with any supported extension
                episode_file = None
                for ext in supported_extensions:
                    potential_file = channel_path / f"{metadata['id']}{ext}"
                    if potential_file.exists():
                        episode_file = potential_file
                        break
                
                if not episode_file:
                    self.logger.warning(f"Episode file missing for {metadata['id']}")
                    continue
                    
                # Store the actual file extension found
                metadata['file_extension'] = episode_file.suffix
                    
                # Verify thumbnail exists
                thumbnail_file = channel_path / metadata['thumbnail']
                if not thumbnail_file.exists():
                    self.logger.warning(f"Thumbnail missing for {metadata['id']}")
                    metadata['thumbnail'] = None
                    
                episodes.append(metadata)
                self.logger.debug(f"Found episode: {metadata['title']}")
                
            except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
                self.logger.error(f"Error reading metadata from {json_file}: {e}")
                continue
                
        return episodes
    
    def generate_rss_feed(self, channel_name: str, videos: List[Dict], display_name: str = None) -> str:
        """Generate RSS 2.0 feed with podcast extensions"""
        fg = FeedGenerator()
        
        # Use display name if provided, otherwise fallback to formatted channel name
        display_title = display_name if display_name else channel_name.replace('_', ' ').title()
        
        # Set feed metadata
        feed_url = f"{self.base_url}/feeds/{quote(channel_name)}"
        feed_xml_url = f"{self.base_url}/feeds/{quote(channel_name)}.xml"
        
        fg.id(feed_url)
        fg.title(display_title)
        fg.link(href=f"{self.base_url}/media/{channel_name}/", rel='alternate')
        fg.description(f"YouTube videos from {display_title}")
        fg.language('en-us')
        # Note: Removed author and generator to match example format
        
        # Load podcast extension
        fg.load_extension('podcast')
        
        # Set podcast-specific metadata
        fg.podcast.itunes_explicit('no')
        fg.podcast.itunes_author(display_title)
        fg.podcast.itunes_summary(f"YouTube videos from {display_title}")
        # Note: Removed itunes_category and itunes_owner to match example
        
        # Add atom:link with rel="self"
        fg.link(href=feed_xml_url, rel='self', type='application/rss+xml')
        
        # Sort videos by upload date (newest first)
        sorted_videos = sorted(videos, key=lambda x: x['upload_date'], reverse=True)
        
        # Add episodes
        for video in sorted_videos:
            fe = fg.add_entry()
            
            # Get file extension and determine MIME type
            file_ext = video.get('file_extension', '.mp4')
            episode_filename = f"{video['id']}{file_ext}"
            encoded_episode_filename = quote(episode_filename)
            episode_url = f"{self.base_url}/podcasts/{quote(channel_name)}/{encoded_episode_filename}"
            
            # Determine MIME type based on file extension
            mime_type_map = {
                '.mp4': 'video/mp4',
                '.m4a': 'audio/mp4', 
                '.mp3': 'audio/mpeg',
                '.webm': 'video/webm',
                '.mkv': 'video/x-matroska',
                '.avi': 'video/avi'
            }
            mime_type = mime_type_map.get(file_ext.lower(), 'video/mp4')
            
            fe.id(episode_url)
            fe.guid(video['id'], permalink=False)
            fe.title(self.sanitize_text(video['title']))
            fe.description(video['description'])
            fe.link(href=episode_url)
            
            # Parse upload date with timezone (RFC 2822 format)
            upload_date = datetime.strptime(video['upload_date'], '%Y%m%d')
            # Set to a reasonable time (4:45 AM CST like in the example)
            upload_date = upload_date.replace(hour=4, minute=45, second=1)
            # Convert to Central Time (UTC-6 for CST, UTC-5 for CDT)
            from datetime import timedelta
            central_tz = timezone(timedelta(hours=-5))  # CDT
            upload_date = upload_date.replace(tzinfo=central_tz)
            fe.published(upload_date)
            
            # Add episode as enclosure with correct MIME type
            fe.enclosure(episode_url, str(video['file_size']), mime_type)
            
            # Add thumbnail as episode image (iTunes supports PNG/JPG, WebP for other clients)
            if video.get('thumbnail'):
                thumbnail_path = video['thumbnail']
                if thumbnail_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    thumbnail_url = f"{self.base_url}/podcasts/{quote(channel_name)}/{quote(thumbnail_path)}"
                    # Only add iTunes image for supported formats
                    if thumbnail_path.lower().endswith(('.png', '.jpg', '.jpeg')):
                        fe.podcast.itunes_image(thumbnail_url)
            
            # Add podcast-specific metadata
            fe.podcast.itunes_duration(self.format_duration(video['duration']))
            fe.podcast.itunes_author(self.sanitize_text(video.get('uploader', 'Unknown')))
            
            self.logger.debug(f"Added episode: {video['title']}")
            
        rss_content = fg.rss_str(pretty=True).decode('utf-8')
        
        # Post-process to match the exact format from the example
        # Remove unwanted elements
        rss_content = rss_content.replace('<docs>http://www.rssboard.org/rss-specification</docs>\n    ', '')
        rss_content = rss_content.replace('<generator>python-feedgen</generator>\n    ', '')
        
        # Remove lastBuildDate
        import re
        rss_content = re.sub(r'    <lastBuildDate>.*?</lastBuildDate>\n', '', rss_content)
        
        # Ensure descriptions are wrapped in CDATA and fix HTML entities
        def fix_description(match):
            content = match.group(1)
            # Unescape HTML entities inside CDATA
            content = content.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
            return f'<description><![CDATA[{content}]]></description>'
        
        rss_content = re.sub(r'<description>(.*?)</description>', fix_description, rss_content, flags=re.DOTALL)
        
        return rss_content
    
    
    def generate_rss_feed_from_filesystem(self, channel_name: str, videos_dir: Path, display_name: str = None) -> str:
        """Generate RSS feed content dynamically from filesystem without saving to file"""
        channel_path = videos_dir / channel_name
        
        # Scan for videos
        videos = self.scan_channel_videos(channel_path)
        if not videos:
            self.logger.info(f"No videos found for channel: {channel_name}, generating empty RSS feed")
            
        # Generate RSS content with display name (works with empty video list)
        rss_content = self.generate_rss_feed(channel_name, videos, display_name)
        
        display_title = display_name if display_name else channel_name
        self.logger.info(f"Generated dynamic RSS feed for {display_title} ({channel_name}) with {len(videos)} episodes")
        return rss_content
