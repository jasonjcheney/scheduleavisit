"""Therapist profile photos: validate, store on disk, import from a pasted URL."""
from __future__ import annotations

import ipaddress
import re
import secrets
import socket
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from capacity import uget
from db import ROOT

MAX_BYTES = 3 * 1024 * 1024
HTML_MAX_BYTES = 1_000_000
FETCH_TIMEOUT = 8.0
MAX_REDIRECTS = 3
AVATAR_REL = Path("data") / "uploads" / "avatars"

JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
WEBP_MAGIC_RIFF = b"RIFF"
WEBP_MAGIC_WEBP = b"WEBP"

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
CONTENT_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

SAFE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
SKIP_SRC_RE = re.compile(
    r"(logo|icon|sprite|pixel|tracking|badge|button|favicon|placeholder|spinner|avatar-default)",
    re.I,
)
HINT_RE = re.compile(r"(profile|photo|headshot|portrait|therapist|provider|avatar)", re.I)
BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "metadata.google.internal",
    "[::1]",
}

FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ScheduleAVisit/1.0; +https://scheduleavisit.com) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


class PhotoError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def avatar_dir() -> Path:
    path = ROOT / AVATAR_REL
    path.mkdir(parents=True, exist_ok=True)
    return path


def public_photo_url(user) -> str:
    slug = (uget(user, "slug", "") or "").strip()
    path = (uget(user, "photo_path", "") or "").strip()
    if not slug or not path:
        return ""
    return f"/media/avatar/{slug}"


def sniff_image(data: bytes) -> str | None:
    if not data or len(data) < 12:
        return None
    if data.startswith(JPEG_MAGIC):
        return ".jpg"
    if data.startswith(PNG_MAGIC):
        return ".png"
    if data[:4] == WEBP_MAGIC_RIFF and data[8:12] == WEBP_MAGIC_WEBP:
        return ".webp"
    return None


def safe_filename(user_id: int, ext: str) -> str:
    ext = ext.lower()
    if ext not in ALLOWED_EXTS:
        ext = ".jpg"
    return f"u{int(user_id)}_{secrets.token_hex(8)}{ext}"


def resolve_avatar_file(photo_path: str | None) -> Path | None:
    """Return the on-disk file if it lives under the avatar dir. No path traversal."""
    raw = (photo_path or "").strip()
    if not raw:
        return None
    name = Path(raw).name
    if name != raw or name in (".", "..") or "/" in raw or "\\" in raw:
        return None
    if Path(name).suffix.lower() not in ALLOWED_EXTS:
        return None
    if ".." in name:
        return None
    folder = avatar_dir().resolve()
    candidate = (folder / name).resolve()
    try:
        candidate.relative_to(folder)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def media_type_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    return "application/octet-stream"


def delete_avatar_file(photo_path: str | None) -> None:
    path = resolve_avatar_file(photo_path)
    if path:
        try:
            path.unlink()
        except OSError:
            pass


def store_avatar_bytes(user_id: int, data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise PhotoError("That photo is too large. Please use a JPEG, PNG, or WebP under 3 MB.")
    ext = sniff_image(data)
    if not ext:
        raise PhotoError("That file doesn’t look like a JPEG, PNG, or WebP picture.")
    name = safe_filename(user_id, ext)
    dest = avatar_dir() / name
    dest.write_bytes(data)
    return name


def validate_upload_file(filename: str | None, content_type: str | None, data: bytes) -> None:
    if not data:
        raise PhotoError("Please choose a photo to upload.")
    if len(data) > MAX_BYTES:
        raise PhotoError("That photo is too large. Please use a JPEG, PNG, or WebP under 3 MB.")
    ext = sniff_image(data)
    if not ext:
        raise PhotoError("Please upload a JPEG, PNG, or WebP picture.")
    hinted = (Path(filename or "").suffix or "").lower()
    if hinted and hinted not in ALLOWED_EXTS:
        raise PhotoError("Please upload a JPEG, PNG, or WebP picture.")
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype and ctype not in CONTENT_EXT and ctype != "application/octet-stream":
        raise PhotoError("Please upload a JPEG, PNG, or WebP picture.")


def save_user_photo(conn, user_id: int, data: bytes, filename: str | None = None, content_type: str | None = None) -> str:
    validate_upload_file(filename, content_type, data)
    old = conn.execute("SELECT photo_path FROM users WHERE id=?", (user_id,)).fetchone()
    name = store_avatar_bytes(user_id, data)
    conn.execute("UPDATE users SET photo_path=? WHERE id=?", (name, user_id))
    if old:
        prior = uget(old, "photo_path", "") or ""
        if prior and prior != name:
            delete_avatar_file(prior)
    return name


def clear_user_photo(conn, user_id: int) -> None:
    row = conn.execute("SELECT photo_path FROM users WHERE id=?", (user_id,)).fetchone()
    conn.execute("UPDATE users SET photo_path='' WHERE id=?", (user_id,))
    if row:
        delete_avatar_file(uget(row, "photo_path", "") or "")


def slug_ok(slug: str) -> bool:
    return bool(SAFE_SLUG_RE.match((slug or "").strip().lower()))


def _host_ok(host: str) -> bool:
    host = (host or "").strip().lower().rstrip(".")
    if not host or host in BLOCKED_HOSTS:
        return False
    if host.endswith(".localhost") or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        return bool(ip.is_global)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except (ValueError, TypeError, IndexError):
            continue
        if not ip.is_global:
            return False
    return True


def normalize_http_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        raise PhotoError("Please paste a Psychology Today or personal website link first.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise PhotoError("That link doesn’t look like a web page. Use an address that starts with https://")
    if not _host_ok(parsed.hostname or ""):
        raise PhotoError("We can only open a public web page. Try a Psychology Today or personal site link.")
    return url


def http_get(url: str, *, timeout: float = FETCH_TIMEOUT, max_bytes: int = MAX_BYTES) -> tuple[bytes, str, str]:
    """Single HTTP seam so tests can mock fetches. Returns (body, content_type, final_url)."""
    safe = normalize_http_url(url)
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        headers=FETCH_HEADERS,
    ) as client:
        with client.stream("GET", safe) as resp:
            if resp.status_code >= 400:
                raise PhotoError("We could not open that page. Check the address and try again.")
            final = str(resp.url)
            try:
                normalize_http_url(final)
            except PhotoError:
                raise PhotoError("We could not open that page. Check the address and try again.")
            ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise PhotoError("That photo is too large. Please use a JPEG, PNG, or WebP under 3 MB.")
                chunks.append(chunk)
            return b"".join(chunks), ctype, final


class _HeadshotParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.og: list[str] = []
        self.pt: list[str] = []
        self.imgs: list[tuple[int, str]] = []
        self._open_priority = 0

    def handle_starttag(self, tag, attrs):
        ad = {k.lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        if tag == "meta":
            key = (ad.get("property") or ad.get("name") or "").lower()
            content = (ad.get("content") or "").strip()
            if content and key in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
                self.og.append(content)
            return
        if tag != "img":
            return
        src = (ad.get("src") or ad.get("data-src") or ad.get("data-lazy-src") or "").strip()
        if not src or src.startswith("data:"):
            return
        if SKIP_SRC_RE.search(src) or SKIP_SRC_RE.search(ad.get("class", "") + " " + ad.get("alt", "") + " " + ad.get("id", "")):
            return
        classes = ad.get("class", "")
        ident = ad.get("id", "")
        alt = ad.get("alt", "")
        ptish = bool(
            HINT_RE.search(src)
            or HINT_RE.search(classes)
            or HINT_RE.search(ident)
            or HINT_RE.search(alt)
            or "psychologytoday" in src.lower()
        )
        w = _int_attr(ad.get("width"))
        h = _int_attr(ad.get("height"))
        if w and w < 64:
            return
        if h and h < 64:
            return
        area = (w or 240) * (h or 240)
        if ptish:
            self.pt.append(src)
            area += 80_000
        self.imgs.append((area, src))


def _int_attr(raw: str | None) -> int:
    if not raw:
        return 0
    digits = re.sub(r"[^\d]", "", raw)
    try:
        return int(digits) if digits else 0
    except ValueError:
        return 0


def extract_image_candidates(html: str, base_url: str) -> list[str]:
    parser = _HeadshotParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    ordered: list[str] = []
    for src in parser.og + parser.pt:
        abs_url = urljoin(base_url, src)
        if abs_url not in ordered:
            ordered.append(abs_url)
    for _area, src in sorted(parser.imgs, key=lambda item: item[0], reverse=True):
        abs_url = urljoin(base_url, src)
        if abs_url not in ordered:
            ordered.append(abs_url)
    return ordered[:8]


def import_photo_from_url(page_url: str) -> bytes:
    """Fetch only the URL the therapist pasted. Extract a likely headshot."""
    url = normalize_http_url(page_url)
    try:
        body, ctype, final = http_get(url, max_bytes=max(MAX_BYTES, HTML_MAX_BYTES))
    except PhotoError:
        raise
    except Exception:
        raise PhotoError("We could not open that page. Check the address and try again.")

    if sniff_image(body) or ctype in CONTENT_EXT:
        if not sniff_image(body):
            raise PhotoError("We could not find a photo on that page. Try uploading a picture instead.")
        if len(body) > MAX_BYTES:
            raise PhotoError("That photo is too large. Please use a JPEG, PNG, or WebP under 3 MB.")
        return body

    if "html" not in (ctype or "") and not body.lstrip()[:20].lower().startswith((b"<!doctype", b"<html", b"<head")):
        raise PhotoError("We could not find a photo on that page. Try uploading a picture instead.")

    html = body[:HTML_MAX_BYTES].decode("utf-8", errors="ignore")
    candidates = extract_image_candidates(html, final or url)
    last_err = "We could not find a photo on that page. Try uploading a picture instead."
    for candidate in candidates:
        try:
            img, img_type, _final = http_get(candidate, max_bytes=MAX_BYTES)
        except PhotoError as exc:
            last_err = exc.message
            continue
        except Exception:
            continue
        if sniff_image(img) or img_type in CONTENT_EXT:
            if sniff_image(img):
                return img
    raise PhotoError(last_err)
