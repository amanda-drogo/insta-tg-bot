"""
Smart Instagram URL parser.

Handles the messy case where a user pastes multiple links concatenated
without any separator:

    https://instagram.com/reel/ABC123/?igsh=xxhttps://instagram.com/p/XYZ/

Splits them cleanly, classifies each one, and extracts metadata.
"""
import re
from enum import Enum


class URLType(Enum):
    REEL = "reel"
    POST = "post"
    STORY = "story"
    PROFILE = "profile"
    UNKNOWN = "unknown"


# ─── URL extraction ─────────────────────────────────────────

def extract_instagram_urls(text: str) -> list[str]:
    """
    Pull every Instagram URL out of *text*, even when they're glued together
    with no whitespace between them.

    Strategy:
      1. Insert a space before every `http` that is preceded by a non-space
         character.  This cleanly splits concatenated URLs.
      2. Run a regex to grab all instagram.com URLs.
      3. Deduplicate while preserving order.
    """
    # Step 1 — break concatenated URLs apart
    spaced = re.sub(r'(?<=\S)(https?://)', r' \1', text)

    # Step 2 — grab every instagram URL
    pattern = r'https?://(?:www\.)?instagram\.com/[^\s<>"\'{}|\\^`\[\]]*'
    raw_urls = re.findall(pattern, spaced, re.IGNORECASE)

    # Step 3 — deduplicate, preserve order
    seen: set[str] = set()
    urls: list[str] = []
    for url in raw_urls:
        # Strip trailing garbage characters that sometimes stick
        url = url.rstrip(".,;!?)")
        canonical = url.split("?")[0].rstrip("/")   # ignore query params for dedup
        if canonical not in seen:
            seen.add(canonical)
            urls.append(url)

    return urls


# ─── URL classification ─────────────────────────────────────

def classify_url(url: str) -> URLType:
    """Return the type of an Instagram URL."""
    path = _extract_path(url)

    if path.startswith("reel/") or path.startswith("reels/"):
        return URLType.REEL
    if path.startswith("p/"):
        return URLType.POST
    if path.startswith("tv/"):
        return URLType.REEL          # IGTV ≈ reel
    if path.startswith("stories/"):
        return URLType.STORY

    # Bare username → profile
    # Profile paths look like: "username" or "username/"
    if "/" not in path and path and not path.startswith("explore"):
        return URLType.PROFILE

    return URLType.UNKNOWN


# ─── Metadata helpers ───────────────────────────────────────

def extract_shortcode(url: str) -> str | None:
    """Extract the shortcode from a /p/, /reel/, or /tv/ URL."""
    m = re.search(r'/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)', url)
    return m.group(1) if m else None


def extract_username(url: str) -> str:
    """Extract the username from any Instagram URL."""
    path = _extract_path(url)
    # For /stories/username/…
    if path.startswith("stories/"):
        parts = path.split("/")
        return parts[1] if len(parts) > 1 else ""
    # For anything else, the first path segment is the username
    return path.split("/")[0]


def extract_story_info(url: str) -> tuple[str | None, str | None]:
    """Return (username, story_media_id) from a story URL."""
    m = re.search(r'/stories/([^/?]+)/(\d+)', url)
    if m:
        return m.group(1), m.group(2)
    # Only username, no specific story ID
    m2 = re.search(r'/stories/([^/?]+)', url)
    if m2:
        return m2.group(1), None
    return None, None


# ─── internal ───────────────────────────────────────────────

def _extract_path(url: str) -> str:
    """Return the path after instagram.com/, without query string."""
    after = url.split("instagram.com/", 1)[-1]
    return after.split("?")[0].strip("/")
