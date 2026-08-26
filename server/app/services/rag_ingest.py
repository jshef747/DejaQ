"""Turn an admin's raw input (text, file, URL, image, repo) into RAG-ready text.

This is the messy extraction layer for the five ingestion sources. It has no
auth, DB, or vector concerns — it only answers "what is the readable text of this
thing, and what should we call it?". `rag_admin_service` orchestrates; this module
extracts.

Extraction reuses what already exists rather than adding heavy dependencies:
- PDF/DOCX/text/code → `file_text.extract` (pypdf / python-docx / UTF-8 sniff),
  the exact same path the file gate uses.
- Image → `image_text.ocr_plaintext` (tesseract), the existing OCR binary.
- Scanned PDF (no text layer) → its embedded page images are pulled out with
  pypdf (already a dependency, MIT) and OCR'd. This avoids AGPL `pymupdf`, which
  the file gate deliberately declined (see pyproject.toml).
- URL → httpx fetch + BeautifulSoup text extraction.
- GitHub repository → the API source tarball, read in memory with `tarfile`. The
  odd one out: it returns ONE IngestResult PER FILE (see `from_repo`), not one
  for the whole input.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import MAX_ATTACHMENT_BYTES
from app.services import file_text, image_text

logger = logging.getLogger("dejaq.rag")

_WHITESPACE_RE = re.compile(r"\s+")
_IMAGE_MIME_PREFIX = "image/"
# A URL fetch that returns more than this is almost certainly not an article.
_URL_MAX_BYTES = MAX_ATTACHMENT_BYTES
# Redirects are followed by hand so every hop can be re-checked against the
# private-address rules; this bounds the chain.
_URL_MAX_REDIRECTS = 5
# Scanned-PDF OCR runs one tesseract pass per embedded image on a FastAPI
# threadpool worker, so a many-page scan needs a hard ceiling: whichever of
# these budgets is hit first stops the loop and keeps the text read so far.
# The time budget is re-checked per IMAGE, not only per page: a single page can
# embed hundreds of rasters, and a per-page check lets one page run unbounded.
_SCANNED_PDF_MAX_PAGES = 50
_SCANNED_PDF_MAX_IMAGES = 100
_SCANNED_PDF_MAX_SECONDS = 120.0


@dataclass(frozen=True)
class IngestResult:
    """The extracted, normalised form of one ingestion input.

    `ok=False` carries a human `reason` for the API error; `ok=True` guarantees a
    non-empty `text` and a `sha` identity.
    """

    ok: bool
    title: str = ""
    kind: str = ""          # text | pdf | docx | markdown | url | image | code
    source: str = ""        # paste | upload | url | ocr | repo
    source_ref: str | None = None
    text: str = ""
    sha: str = ""
    char_count: int = 0
    # Size in bytes of the raw input as given to us (pasted text's UTF-8
    # encoding, the uploaded file's bytes, or the fetched page's bytes) - what
    # the dashboard shows as "file size". Distinct from char_count, which is
    # extracted-text length and can differ a lot for PDF/DOCX.
    byte_size: int = 0
    reason: str = ""


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _finalize(
    *, title: str, kind: str, source: str, source_ref: str | None, text: str, byte_size: int
) -> IngestResult:
    normalized = _normalize(text)
    if not normalized:
        return IngestResult(ok=False, kind=kind, source=source, reason="no readable text found")
    return IngestResult(
        ok=True,
        title=title.strip() or (source_ref or kind),
        kind=kind,
        source=source,
        source_ref=source_ref,
        text=text,
        sha=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        char_count=len(normalized),
        byte_size=byte_size,
    )


def from_text(title: str, content: str) -> IngestResult:
    return _finalize(
        title=title, kind="text", source="paste", source_ref=None, text=content,
        byte_size=len(content.encode("utf-8")),
    )


def from_upload(
    filename: str | None, data: bytes, mime: str | None, title: str | None = None
) -> IngestResult:
    """Extract text from an uploaded file, OCR'ing images and scanned PDFs.

    `filename` is the real name of the uploaded file — it feeds extension-based
    kind detection and is stored as source_ref. `title` is only a display-name
    override and never influences extraction.
    """
    if len(data) > MAX_ATTACHMENT_BYTES:
        return IngestResult(ok=False, reason=f"file exceeds {MAX_ATTACHMENT_BYTES} bytes")

    display = (title or "").strip() or (filename or "").strip() or "upload"
    ft = file_text.extract(data, mime, filename)

    # 1. A file with a real text layer (PDF/DOCX/Markdown/code) — the common case.
    if ft.ok and ft.text.strip():
        return _finalize(
            title=display, kind=ft.kind, source="upload", source_ref=filename, text=ft.text,
            byte_size=len(data),
        )

    # 2. An image upload — OCR it. file_text.kind_for returns "" for images.
    if (mime or "").split(";", 1)[0].strip().lower().startswith(_IMAGE_MIME_PREFIX):
        text = image_text.ocr_plaintext(data)
        if not text.strip():
            return IngestResult(ok=False, kind="image", source="ocr",
                                reason="OCR found no readable text in the image")
        return _finalize(title=display, kind="image", source="ocr", source_ref=filename, text=text,
                          byte_size=len(data))

    # 3. A PDF with no text layer (a scan) — OCR its embedded page images.
    if ft.kind == "pdf":
        text = _ocr_scanned_pdf(data)
        if text.strip():
            return _finalize(title=display, kind="pdf", source="ocr", source_ref=filename, text=text,
                              byte_size=len(data))
        return IngestResult(ok=False, kind="pdf", source="ocr",
                            reason="scanned PDF: no text layer and OCR found nothing")

    # 4. Anything else file_text refused (unsupported/corrupt).
    return IngestResult(ok=False, kind=ft.kind or "", reason=ft.reason or "unsupported file")


def _ocr_scanned_pdf(data: bytes) -> str:
    """OCR every embedded image of a scanned PDF, page by page.

    A scanned PDF is typically one full-page raster per page. pypdf exposes those
    via `page.images`; we OCR each and concatenate. Best-effort — any failure just
    yields less text, never an exception.
    """
    try:
        import io
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return ""
        parts: list[str] = []
        deadline = time.monotonic() + _SCANNED_PDF_MAX_SECONDS
        total_pages = len(reader.pages)
        images_done = 0
        exhausted = False
        for page_index, page in enumerate(reader.pages):
            if page_index >= _SCANNED_PDF_MAX_PAGES or time.monotonic() > deadline:
                exhausted = True
            if exhausted:
                logger.info(
                    "Scanned-PDF OCR stopped at page %d/%d (page/image/time budget reached)",
                    page_index, total_pages,
                )
                break
            try:
                for img in page.images:
                    if images_done >= _SCANNED_PDF_MAX_IMAGES or time.monotonic() > deadline:
                        exhausted = True
                        break
                    images_done += 1
                    page_text = image_text.ocr_plaintext(img.data)
                    if page_text.strip():
                        parts.append(page_text)
            except Exception:
                logger.debug("Could not OCR a scanned PDF page", exc_info=True)
        return "\n".join(parts)
    except ModuleNotFoundError:
        return ""
    except Exception:
        logger.info("Scanned-PDF OCR failed", exc_info=True)
        return ""


def _resolve_ips(host: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Every address `host` resolves to, with IPv4-mapped IPv6 unwrapped."""
    out = []
    for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP):
        ip = ipaddress.ip_address(info[4][0])
        out.append(getattr(ip, "ipv4_mapped", None) or ip)
    return out


def _url_block_reason(url: str) -> str | None:
    """Why this URL must not be fetched server-side, or None when it is allowed.

    The server sits on the operator's network, so an ingestion URL pointing at
    loopback, a private range, or the cloud metadata endpoint would turn the
    admin API into a read primitive for internal services. Only globally
    routable addresses are fetched; a hostname is refused if ANY address it
    resolves to is non-global. Every redirect hop is re-checked, since a public
    URL can 302 into an internal one.

    A DNS entry that changes between this check and the connect (rebinding) is
    not covered — closing that needs a pinned-IP transport, not a stricter rule.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return "URL must start with http:// or https://"
    try:
        host = parsed.hostname
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError:
        return "URL has an invalid host or port"
    if not host:
        return "URL has no host"
    try:
        ips = _resolve_ips(host, port)
    except (OSError, ValueError):
        return f"could not resolve host '{host}'"
    for ip in ips:
        if not ip.is_global:
            return (
                f"refusing to fetch '{host}': {ip} is a loopback, private, "
                "link-local, or otherwise non-public address"
            )
    return None


def from_url(url: str, title: str | None = None) -> IngestResult:
    """Fetch a URL and extract its readable text via BeautifulSoup."""
    url = (url or "").strip()
    try:
        import httpx

        raw = b""
        with httpx.Client(follow_redirects=False, timeout=20.0) as client:
            current = url
            for _ in range(_URL_MAX_REDIRECTS + 1):
                blocked = _url_block_reason(current)
                if blocked is not None:
                    return IngestResult(ok=False, kind="url", source="url", reason=blocked)
                with client.stream(
                    "GET", current, headers={"User-Agent": "DejaQ-RAG/1.0"}
                ) as resp:
                    location = (
                        resp.headers.get("location")
                        if 300 <= resp.status_code < 400
                        else None
                    )
                    if location:
                        current = str(httpx.URL(current).join(location))
                        continue
                    resp.raise_for_status()
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) >= _URL_MAX_BYTES:
                            break
                    raw = bytes(buf[:_URL_MAX_BYTES])
                    break
            else:
                return IngestResult(ok=False, kind="url", source="url",
                                    reason=f"too many redirects (>{_URL_MAX_REDIRECTS})")
    except Exception as exc:
        return IngestResult(ok=False, kind="url", source="url",
                            reason=f"could not fetch URL ({type(exc).__name__})")

    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError:
        return IngestResult(ok=False, kind="url", source="url",
                            reason="beautifulsoup4 is not installed — run `uv sync`")

    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    page_title = title or (soup.title.string.strip() if soup.title and soup.title.string else url)
    text = soup.get_text(separator="\n")
    return _finalize(title=page_title, kind="url", source="url", source_ref=url, text=text,
                      byte_size=len(raw))


# --- GitHub repository import -------------------------------------------------
#
# A fourth entry point beside from_text/from_upload/from_url, with one
# difference: it produces MANY IngestResults, one per file in the repository,
# so the catalog keeps per-file provenance ("which file grounded this answer?")
# and the existing (workspace_id, sha) identity does per-file replace for free.
#
# Fetching is the GitHub API source tarball - one request, no `git` binary, no
# working copy - read through `tarfile` in memory. Nothing is ever extracted to
# disk, so tar path traversal is not reachable here; only regular files are read.
#
# Every "which files are worth indexing" rule lives in the block of constants
# below and in `_repo_skip_reason`. Do not scatter new rules into the read loop.

# Compressed source tarball ceiling. GitHub source tarballs for the kind of
# repository a knowledge base is built from are single-digit MB; 50 MB is far
# above that and still bounded enough that one bad URL cannot fill the disk.
# It is a backstop, not the real limit - _REPO_MAX_FILES and
# _REPO_MAX_FILE_BYTES are what actually bound how much text gets indexed.
_REPO_TARBALL_MAX_BYTES = 50 * 1024 * 1024
# Per-file ceiling. Above this a file is a generated blob, a data dump, or a
# vendored bundle - never something a person wrote for a reader.
_REPO_MAX_FILE_BYTES = 256 * 1024
# Below this many normalised characters a file is a stub (a one-line __init__,
# a two-word .gitignore) and its chunk is pure retrieval noise.
_REPO_MIN_FILE_CHARS = 50
# Hard cap on catalog rows one import may create. Embedding is the slow phase
# and each file becomes its own background job, so an unbounded repo would
# queue thousands of them.
_REPO_MAX_FILES = 400
_REPO_FETCH_TIMEOUT = 60.0

# Directory names that are never source: dependency trees, build output, IDE
# and VCS metadata. Matched against every path component, at any depth.
_REPO_SKIP_DIRS = frozenset({
    ".git", ".github", ".hg", ".svn", ".idea", ".vscode",
    "node_modules", "bower_components", "vendor", "third_party", "site-packages",
    "dist", "build", "out", "target", ".next", ".nuxt", ".output",
    "__pycache__", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
    "coverage", "htmlcov", ".cache",
})
# Lockfiles: enormous, machine-written, and answer no question anyone asks.
_REPO_SKIP_NAMES = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json",
    "poetry.lock", "uv.lock", "pipfile.lock", "cargo.lock", "gemfile.lock",
    "composer.lock", "go.sum", "flake.lock", "podfile.lock", "mix.lock",
})
# Binaries, media, archives, fonts, model weights, compiled output. Anything
# here would fail the UTF-8 sniff anyway - listing it just avoids reading it.
_REPO_SKIP_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp", ".tiff",
    ".pdf", ".zip", ".gz", ".tgz", ".tar", ".bz2", ".xz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".a", ".o", ".obj", ".class", ".jar",
    ".wasm", ".bin", ".pyc", ".pyd", ".pyo", ".woff", ".woff2", ".ttf", ".eot",
    ".otf", ".mp3", ".mp4", ".mov", ".avi", ".webm", ".wav", ".ogg", ".flac",
    ".db", ".sqlite", ".sqlite3", ".parquet", ".npy", ".npz", ".pt", ".pth",
    ".onnx", ".safetensors", ".pkl", ".doc", ".docx", ".xls", ".xlsx", ".ppt",
    ".pptx",
    # A notebook is JSON carrying base64 cell OUTPUT; its prose is buried in
    # escaped strings, so indexing it poisons retrieval with encoded images.
    ".ipynb",
    # Source maps are minified-bundle metadata, nothing else.
    ".map",
})
_REPO_MARKDOWN_EXTS = frozenset({".md", ".markdown", ".mdx"})
_REPO_TEXT_EXTS = frozenset({".txt", ".rst", ".adoc", ".text"})
# A minified bundle is one enormous line - technically valid UTF-8, useless to
# a reader, and it would eat the whole per-file budget.
_REPO_MINIFIED_MARKERS = (".min.js", ".min.css", "-min.js", ".bundle.js")

# Owner deliberately excludes "." - a GitHub account name is alphanumerics and
# hyphens only. Allowing dots made "https://example.com/some-path" parse as
# owner="example.com", which then reached the GitHub API and came back as a
# baffling "no public repository 'example.com/some-path'". Repo names DO allow
# dots (".github", "foo.js"), so only the owner half is tightened.
_REPO_PATH_RE = re.compile(
    r"^(?P<owner>[A-Za-z0-9][A-Za-z0-9-]*)/(?P<repo>[A-Za-z0-9._-]+?)(?:\.git)?"
    r"(?:/(?:tree|blob)/(?P<ref>[^\s?#]+?))?/?$"
)
_GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})


@dataclass(frozen=True)
class RepoRef:
    owner: str
    repo: str
    ref: str | None = None      # branch/tag/sha, None = the default branch

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class RepoIngest:
    """Everything one repository import produced.

    `ok=False` carries a human `reason`, exactly like IngestResult. On success
    `files` holds one IngestResult per indexable file and `skipped` counts what
    the filter dropped, so the operator can be told "112 files, 340 skipped"
    rather than being left to wonder.
    """

    ok: bool
    ref: RepoRef | None = None
    resolved_ref: str = ""      # the sha/branch the tarball's root dir names
    group_key: str = ""         # "github:owner/repo" - the catalog grouping value
    files: list[IngestResult] = None  # type: ignore[assignment]
    skipped: int = 0
    reason: str = ""


def parse_repo_url(value: str) -> RepoRef | None:
    """Accept the forms a person actually pastes.

    "owner/repo", "github.com/owner/repo", the full https URL with or without
    ".git", and a /tree/<branch> deep link (whose branch becomes the ref).
    Anything else returns None.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    if "://" in raw:
        parsed = urlparse(raw)
        if (parsed.hostname or "").lower() not in _GITHUB_HOSTS:
            return None
        path = parsed.path
    else:
        # A host-qualified form with no scheme, or a bare "owner/repo".
        lowered = raw.lower()
        for host in ("www.github.com/", "github.com/"):
            if lowered.startswith(host):
                raw = raw[len(host):]
                break
        path = raw
    match = _REPO_PATH_RE.match(path.strip("/"))
    if match is None:
        return None
    repo = match.group("repo")
    if repo in (".", ".."):
        return None
    return RepoRef(owner=match.group("owner"), repo=repo, ref=match.group("ref") or None)


def _repo_skip_reason(path: str, size: int) -> str | None:
    """Why this repository file must not be indexed, or None to index it.

    Path-and-size rules only - the UTF-8 check happens after the bytes are
    read, in `_repo_files_from_tar`. Every filter rule lives here.
    """
    parts = path.split("/")
    name = parts[-1].lower()
    for part in parts[:-1]:
        if part.lower() in _REPO_SKIP_DIRS:
            return "excluded directory"
    if name in _REPO_SKIP_NAMES:
        return "lockfile"
    dot = name.rfind(".")
    ext = name[dot:] if dot > 0 else ""
    if ext in _REPO_SKIP_EXTS:
        return "binary or media file"
    if any(marker in name for marker in _REPO_MINIFIED_MARKERS):
        return "minified bundle"
    if size > _REPO_MAX_FILE_BYTES:
        return f"larger than {_REPO_MAX_FILE_BYTES} bytes"
    return None


def _repo_kind(path: str) -> str:
    name = path.lower()
    dot = name.rfind("/")
    base = name[dot + 1:]
    ext_at = base.rfind(".")
    ext = base[ext_at:] if ext_at > 0 else ""
    if ext in _REPO_MARKDOWN_EXTS:
        return "markdown"
    if ext in _REPO_TEXT_EXTS or not ext:
        return "text"
    return "code"


def _fetch_repo_tarball(ref: RepoRef) -> tuple[bytes, str]:
    """GET the GitHub source tarball. Returns (bytes, error-reason).

    Redirects are followed by hand for the same reason `from_url` does it:
    the API host 302s to codeload.github.com and every hop is re-checked
    against the private-address rules before it is opened.
    """
    import httpx

    url = f"https://api.github.com/repos/{ref.owner}/{ref.repo}/tarball"
    if ref.ref:
        url = f"{url}/{ref.ref}"
    headers = {
        "User-Agent": "DejaQ-RAG/1.0",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        with httpx.Client(follow_redirects=False, timeout=_REPO_FETCH_TIMEOUT) as client:
            current = url
            for _ in range(_URL_MAX_REDIRECTS + 1):
                blocked = _url_block_reason(current)
                if blocked is not None:
                    return b"", blocked
                with client.stream("GET", current, headers=headers) as resp:
                    if 300 <= resp.status_code < 400 and resp.headers.get("location"):
                        current = str(httpx.URL(current).join(resp.headers["location"]))
                        continue
                    if resp.status_code == 404:
                        # GitHub returns 404, never 403, for a private repo seen
                        # by an unauthenticated client - it will not confirm the
                        # repo exists. So this one status covers both cases and
                        # the message has to name both.
                        return b"", (
                            f"GitHub has no public repository '{ref.slug}'"
                            + (f"' at ref '{ref.ref}'" if ref.ref else "")
                            + ". Either it does not exist, the ref is wrong, or it is "
                            "private - private repositories are not supported (they need "
                            "a stored access token, which DejaQ does not have yet)."
                        )
                    if resp.status_code in (403, 429):
                        return b"", (
                            "GitHub refused the download (rate limit for unauthenticated "
                            "requests). Try again later."
                        )
                    if resp.status_code >= 400:
                        return b"", f"GitHub returned HTTP {resp.status_code} for {ref.slug}"
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) > _REPO_TARBALL_MAX_BYTES:
                            return b"", (
                                f"repository tarball exceeds the "
                                f"{_REPO_TARBALL_MAX_BYTES // (1024 * 1024)} MB limit"
                            )
                    return bytes(buf), ""
            return b"", f"too many redirects (>{_URL_MAX_REDIRECTS})"
    except Exception as exc:
        return b"", f"could not download {ref.slug} ({type(exc).__name__})"


def _repo_files_from_tar(raw: bytes) -> tuple[str, list[tuple[str, bytes]], int]:
    """Read the tarball into (resolved_ref, [(repo-relative path, bytes)], skipped).

    GitHub wraps everything in a single "{owner}-{repo}-{sha}/" directory; that
    prefix is stripped and its trailing sha is the resolved ref. Members are
    only ever read through `extractfile` - never written out - and anything
    that is not a regular file (directory, symlink, device) is ignored.
    """
    import io
    import tarfile

    kept: list[tuple[str, bytes]] = []
    skipped = 0
    resolved_ref = ""
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            parts = member.name.split("/", 1)
            if not resolved_ref and parts[0]:
                root = parts[0]
                resolved_ref = root.rsplit("-", 1)[-1] if "-" in root else root
            if len(parts) < 2 or not parts[1]:
                continue
            path = parts[1]
            reason = _repo_skip_reason(path, member.size)
            if reason is not None:
                skipped += 1
                continue
            if len(kept) >= _REPO_MAX_FILES:
                skipped += 1
                continue
            handle = tar.extractfile(member)
            if handle is None:
                skipped += 1
                continue
            data = handle.read(_REPO_MAX_FILE_BYTES + 1)
            if len(data) > _REPO_MAX_FILE_BYTES:
                skipped += 1
                continue
            kept.append((path, data))
    return resolved_ref, kept, skipped


def from_repo(url: str, ref: str | None = None) -> RepoIngest:
    """Import one public GitHub repository as one IngestResult PER FILE.

    `ref` (a branch, tag, or sha) overrides any ref parsed out of `url`; both
    absent means the repository's default branch.
    """
    parsed = parse_repo_url(url)
    if parsed is None:
        return RepoIngest(ok=False, files=[], reason=(
            "not a GitHub repository URL - expected something like "
            "https://github.com/owner/repo"
        ))
    if ref and ref.strip():
        parsed = RepoRef(owner=parsed.owner, repo=parsed.repo, ref=ref.strip())
    group_key = f"github:{parsed.slug}"

    raw, error = _fetch_repo_tarball(parsed)
    if error:
        return RepoIngest(ok=False, ref=parsed, group_key=group_key, files=[], reason=error)

    try:
        resolved_ref, raw_files, skipped = _repo_files_from_tar(raw)
    except Exception as exc:
        return RepoIngest(ok=False, ref=parsed, group_key=group_key, files=[],
                          reason=f"could not read the repository tarball ({type(exc).__name__})")

    display_ref = parsed.ref or resolved_ref or "HEAD"
    results: list[IngestResult] = []
    # Two files with byte-identical content share one sha, and sha is the
    # catalog's identity - so the second would silently REPLACE the first's
    # row (a repo with two copies of the same LICENSE, or two empty-ish
    # config files). First path wins; the duplicate is counted as skipped.
    seen_shas: set[str] = set()
    for path, data in raw_files:
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            skipped += 1
            continue
        item = _finalize(
            title=path,
            kind=_repo_kind(path),
            source="repo",
            source_ref=f"https://github.com/{parsed.slug}/blob/{display_ref}/{path}",
            text=text,
            byte_size=len(data),
        )
        if not item.ok or item.char_count < _REPO_MIN_FILE_CHARS or item.sha in seen_shas:
            skipped += 1
            continue
        seen_shas.add(item.sha)
        results.append(item)

    if not results:
        return RepoIngest(ok=False, ref=parsed, group_key=group_key, files=[], skipped=skipped,
                          reason=f"no indexable text files found in {parsed.slug}")
    logger.info(
        "rag_repo_fetch repo=%s ref=%s indexed=%d skipped=%d",
        parsed.slug, display_ref, len(results), skipped,
    )
    return RepoIngest(
        ok=True, ref=parsed, resolved_ref=display_ref, group_key=group_key,
        files=results, skipped=skipped,
    )
