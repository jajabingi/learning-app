"""Provider-agnostic video resolution.

A video is always stored as a URL. This module turns it into a safe playback descriptor. Only allow-listed embed
hosts are ever produced, so a teacher (or a compromised account) cannot make students' browsers load arbitrary
iframes. To support another host (Mux, Cloudflare Stream, Bunny, S3 signed URLs...) add a resolver to RESOLVERS.
Video bytes are never stored in this application or its database.
"""
import re
from urllib.parse import parse_qs, urlparse

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_VIMEO_ID = re.compile(r"^\d{5,12}$")
DIRECT_EXT = (".mp4", ".webm", ".ogg", ".m3u8")


class VideoError(ValueError):
    pass


def _youtube(u):
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    vid = None
    if host in ("youtube.com", "youtube-nocookie.com"):
        if u.path == "/watch":
            vid = parse_qs(u.query).get("v", [None])[0]
        elif u.path.startswith(("/embed/", "/shorts/", "/live/")):
            vid = u.path.split("/")[2]
    elif host == "youtu.be":
        vid = u.path.lstrip("/").split("/")[0]
    else:
        return None
    if not vid or not _YT_ID.match(vid):
        raise VideoError("Could not read the YouTube video id")
    return {"provider": "youtube", "kind": "embed", "embed_url": f"https://www.youtube-nocookie.com/embed/{vid}", "external_id": vid}


def _vimeo(u):
    host = (u.hostname or "").lower().removeprefix("www.")
    if host not in ("vimeo.com", "player.vimeo.com"):
        return None
    parts = [p for p in u.path.split("/") if p]
    vid = next((p for p in parts if _VIMEO_ID.match(p)), None)
    if not vid:
        raise VideoError("Could not read the Vimeo video id")
    return {"provider": "vimeo", "kind": "embed", "embed_url": f"https://player.vimeo.com/video/{vid}", "external_id": vid}


def _direct(u):
    if (u.path or "").lower().endswith(DIRECT_EXT):
        return {"provider": "direct", "kind": "file", "embed_url": None, "external_id": None}
    return None


RESOLVERS = (_youtube, _vimeo, _direct)


def resolve_video(url: str) -> dict:
    """Return {provider, kind: embed|file, embed_url, url, external_id}. Raises VideoError for unsupported URLs."""
    url = (url or "").strip()
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname:
        raise VideoError("Video URL must start with https://")
    for r in RESOLVERS:
        res = r(u)
        if res:
            return {**res, "url": url}
    raise VideoError("Unsupported video host. Use YouTube, Vimeo, or a direct https .mp4/.webm/.m3u8 link.")
