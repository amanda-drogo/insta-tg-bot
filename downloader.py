"""
Instagram download engine.

Uses yt-dlp (fast, no login needed for public content) as the primary
downloader and falls back to instaloader for profile scraping, profile
pictures, and stories.

Every public method is async and returns a DownloadResult that the caller
must .cleanup() after it is done sending files.
"""
import os
import glob
import asyncio
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import instaloader
import requests
import yt_dlp

from config import MAX_TELEGRAM_FILE_SIZE


# ─── Data types ──────────────────────────────────────────────

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}
ALL_MEDIA_EXTS = VIDEO_EXTS | PHOTO_EXTS


def _media_type(filepath: str) -> str:
    """Return 'video' or 'photo' based on file extension."""
    return "video" if Path(filepath).suffix.lower() in VIDEO_EXTS else "photo"


@dataclass
class MediaFile:
    path: str
    media_type: str          # 'video' | 'photo'


@dataclass
class DownloadResult:
    tmpdir: str
    files: list[MediaFile] = field(default_factory=list)

    def cleanup(self):
        if self.tmpdir and os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir, ignore_errors=True)


# ─── Helpers ─────────────────────────────────────────────────

def _collect_media(directory: str) -> list[MediaFile]:
    """Recursively collect all media files under *directory*."""
    found: list[MediaFile] = []
    for fpath in sorted(glob.glob(os.path.join(directory, "**", "*"), recursive=True)):
        if os.path.isfile(fpath) and Path(fpath).suffix.lower() in ALL_MEDIA_EXTS:
            found.append(MediaFile(path=fpath, media_type=_media_type(fpath)))
    return found


def compress_video(input_path: str, max_bytes: int = MAX_TELEGRAM_FILE_SIZE - 1_000_000) -> str:
    """
    If *input_path* exceeds *max_bytes*, re-encode to fit.
    Returns the path to use (original or compressed).
    """
    if os.path.getsize(input_path) <= max_bytes:
        return input_path

    output_path = input_path.rsplit(".", 1)[0] + "_compressed.mp4"

    # Probe duration
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            input_path,
        ],
        capture_output=True, text=True,
    )
    try:
        duration = float(probe.stdout.strip())
    except (ValueError, AttributeError):
        return input_path          # can't probe → give up

    target_kbps = int((max_bytes * 8) / (duration * 1024))
    if target_kbps < 100:
        return input_path          # would be unwatchable

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", input_path,
            "-b:v", f"{target_kbps}k",
            "-maxrate", f"{target_kbps}k",
            "-bufsize", f"{target_kbps * 2}k",
            "-vf", "scale=-2:min(720\\,ih)",       # cap at 720p
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ],
        capture_output=True,
    )

    if os.path.exists(output_path) and os.path.getsize(output_path) <= max_bytes:
        return output_path

    # Compression didn't help enough — return original
    if os.path.exists(output_path):
        os.remove(output_path)
    return input_path


# ─── Main engine ─────────────────────────────────────────────

class InstaDownloader:

    def __init__(self, username: str = "", password: str = ""):
        self._lock = threading.Lock()
        self._username = username
        self._password = password
        self._logged_in = False
        self._loader = self._make_loader()

    # ── instaloader setup ────────────────────────────────────

    def _make_loader(self) -> instaloader.Instaloader:
        loader = instaloader.Instaloader(
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            post_metadata_txt_pattern="",
            max_connection_attempts=3,
        )
        if self._username and self._password:
            try:
                loader.login(self._username, self._password)
                self._logged_in = True
                print("✅ Instagram login successful")
            except Exception as exc:
                print(f"⚠️  Instagram login failed: {exc}")
        return loader

    # ── yt-dlp helper ────────────────────────────────────────

    @staticmethod
    def _ytdlp_download(url: str, output_dir: str) -> list[MediaFile]:
        """Download with yt-dlp.  Returns list of MediaFile."""
        ydl_opts = {
            "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
            "format": "best",
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "socket_timeout": 30,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return []

            entries = info.get("entries", [info]) if info.get("entries") else [info]
            files: list[MediaFile] = []
            for entry in entries:
                fname = ydl.prepare_filename(entry)
                if os.path.exists(fname):
                    files.append(MediaFile(path=fname, media_type=_media_type(fname)))

            # Fallback: scan directory
            if not files:
                files = _collect_media(output_dir)

            return files

    # ────────────────────────────────────────────────────────
    # PUBLIC ASYNC API
    # ────────────────────────────────────────────────────────

    async def download_post(self, url: str, shortcode: str | None = None) -> DownloadResult:
        """Download a single post / reel / IGTV."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._dl_post_sync, url, shortcode)

    async def download_profile_pic(self, username: str) -> DownloadResult:
        """Download the HD profile picture."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._dl_pfp_sync, username)

    async def download_profile(
        self,
        username: str,
        max_posts: int = 50,
        progress: Optional[Callable[[int], None]] = None,
    ) -> DownloadResult:
        """Download all posts + profile pic from a public profile."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._dl_profile_sync, username, max_posts, progress)

    async def download_story(self, username: str, story_id: str | None = None) -> DownloadResult:
        """Download story/stories (requires Instagram login)."""
        if not self._logged_in:
            raise RuntimeError(
                "⚠️ Instagram login is required for story downloads.\n"
                "Set INSTA_USERNAME and INSTA_PASSWORD environment variables."
            )
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._dl_story_sync, username, story_id)

    # ────────────────────────────────────────────────────────
    # SYNC IMPLEMENTATIONS  (run in thread executor)
    # ────────────────────────────────────────────────────────

    def _dl_post_sync(self, url: str, shortcode: str | None) -> DownloadResult:
        tmpdir = tempfile.mkdtemp(prefix="insta_post_")
        result = DownloadResult(tmpdir=tmpdir)

        # ① Try yt-dlp first (fast, no login)
        try:
            files = self._ytdlp_download(url, tmpdir)
            if files:
                result.files = files
                return result
        except Exception:
            pass

        # ② Fallback to instaloader
        if shortcode:
            try:
                with self._lock:
                    self._loader.dirname_pattern = os.path.join(tmpdir, "{target}")
                    post = instaloader.Post.from_shortcode(self._loader.context, shortcode)
                    self._loader.download_post(post, target="media")
                media_dir = os.path.join(tmpdir, "media")
                result.files = _collect_media(media_dir) if os.path.isdir(media_dir) else []
                if result.files:
                    return result
            except Exception:
                pass

        if not result.files:
            result.cleanup()
            raise RuntimeError("Download failed — the post may be private, deleted, or Instagram is blocking requests.")

        return result

    # ── profile picture ──────────────────────────────────────

    def _dl_pfp_sync(self, username: str) -> DownloadResult:
        tmpdir = tempfile.mkdtemp(prefix="insta_pfp_")
        try:
            with self._lock:
                profile = instaloader.Profile.from_username(self._loader.context, username)
                pic_url = profile.profile_pic_url

            resp = requests.get(pic_url, stream=True, timeout=30)
            resp.raise_for_status()
            filepath = os.path.join(tmpdir, f"{username}_profile_pic.jpg")
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)

            return DownloadResult(
                tmpdir=tmpdir,
                files=[MediaFile(path=filepath, media_type="photo")],
            )
        except Exception as exc:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise RuntimeError(f"Failed to download profile picture: {exc}")

    # ── full profile ─────────────────────────────────────────

    def _dl_profile_sync(
        self,
        username: str,
        max_posts: int,
        progress: Optional[Callable[[int], None]],
    ) -> DownloadResult:
        tmpdir = tempfile.mkdtemp(prefix="insta_profile_")
        result = DownloadResult(tmpdir=tmpdir)

        try:
            with self._lock:
                self._loader.dirname_pattern = os.path.join(tmpdir, "{target}")
                profile = instaloader.Profile.from_username(self._loader.context, username)
                pic_url = profile.profile_pic_url

            # Profile pic
            try:
                resp = requests.get(pic_url, stream=True, timeout=30)
                resp.raise_for_status()
                pfp_path = os.path.join(tmpdir, f"{username}_pfp.jpg")
                with open(pfp_path, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                result.files.append(MediaFile(path=pfp_path, media_type="photo"))
            except Exception:
                pass   # non-fatal

            # Posts
            count = 0
            with self._lock:
                for post in profile.get_posts():
                    if count >= max_posts:
                        break
                    try:
                        self._loader.download_post(post, target=username)
                        count += 1
                        if progress:
                            progress(count)
                    except Exception:
                        continue

            profile_dir = os.path.join(tmpdir, username)
            if os.path.isdir(profile_dir):
                result.files.extend(_collect_media(profile_dir))

            if not result.files:
                result.cleanup()
                raise RuntimeError("No media found — the profile may be private or empty.")

            return result

        except RuntimeError:
            raise
        except Exception as exc:
            result.cleanup()
            raise RuntimeError(f"Profile download failed: {exc}")

    # ── stories ──────────────────────────────────────────────

    def _dl_story_sync(self, username: str, story_id: str | None) -> DownloadResult:
        tmpdir = tempfile.mkdtemp(prefix="insta_story_")
        result = DownloadResult(tmpdir=tmpdir)

        try:
            with self._lock:
                self._loader.dirname_pattern = os.path.join(tmpdir, "{target}")
                profile = instaloader.Profile.from_username(self._loader.context, username)

                for story in self._loader.get_stories(userids=[profile.userid]):
                    for item in story.get_items():
                        if story_id and str(item.mediaid) != str(story_id):
                            continue
                        self._loader.download_storyitem(item, target=f"{username}_stories")
                        if story_id:
                            break

            stories_dir = os.path.join(tmpdir, f"{username}_stories")
            if os.path.isdir(stories_dir):
                result.files = _collect_media(stories_dir)

            if not result.files:
                result.cleanup()
                raise RuntimeError("No stories found — they may have expired or the account has no active stories.")

            return result

        except RuntimeError:
            raise
        except Exception as exc:
            result.cleanup()
            raise RuntimeError(f"Story download failed: {exc}")
