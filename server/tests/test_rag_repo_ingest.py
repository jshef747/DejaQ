"""GitHub repository import: URL parsing, the file filter, and tarball reading.

The network is never touched — `_fetch_repo_tarball` is monkeypatched with a
tarball built in memory, which is exactly what the real one returns. What is
asserted is this module's own logic: which files are indexed, which are
dropped and why, per-file kind/title/provenance, and the failure messages.
"""
import io
import tarfile

import pytest

from app.services import rag_ingest

pytestmark = pytest.mark.no_model

ROOT = "owner-repo-abc1234"
# _finalize drops anything below _REPO_MIN_FILE_CHARS, so test files need real body text.
BODY = "This sentence exists only so the file clears the minimum-characters floor. "


def _tarball(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, data in files.items():
            info = tarfile.TarInfo(f"{ROOT}/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def fake_github(monkeypatch):
    """Serve a tarball built from a dict of {path: bytes}."""
    def _install(files: dict[str, bytes], error: str = ""):
        raw = b"" if error else _tarball(files)
        monkeypatch.setattr(rag_ingest, "_fetch_repo_tarball", lambda ref: (raw, error))
    return _install


# --- URL parsing --------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("https://github.com/owner/repo", ("owner", "repo", None)),
    ("https://github.com/owner/repo.git", ("owner", "repo", None)),
    ("http://www.github.com/owner/repo/", ("owner", "repo", None)),
    ("github.com/owner/repo", ("owner", "repo", None)),
    ("owner/repo", ("owner", "repo", None)),
    ("https://github.com/owner/repo/tree/v1.2.0", ("owner", "repo", "v1.2.0")),
    ("https://github.com/owner/repo/tree/feature/x", ("owner", "repo", "feature/x")),
])
def test_parse_repo_url_accepts_the_forms_people_paste(value, expected):
    ref = rag_ingest.parse_repo_url(value)
    assert (ref.owner, ref.repo, ref.ref) == expected


@pytest.mark.parametrize("value", ["", "   ", "not a url", "https://example.com", "owner"])
def test_parse_repo_url_rejects_non_repositories(value):
    assert rag_ingest.parse_repo_url(value) is None


# --- The file filter ----------------------------------------------------------

@pytest.mark.parametrize("path,reason_fragment", [
    ("node_modules/left-pad/index.js", "excluded directory"),
    ("web/dist/app.js", "excluded directory"),
    ("app/__pycache__/x.cpython-313.pyc", "excluded directory"),
    (".git/config", "excluded directory"),
    ("package-lock.json", "lockfile"),
    ("uv.lock", "lockfile"),
    ("docs/diagram.png", "binary or media"),
    ("weights/model.safetensors", "binary or media"),
    ("notebooks/demo.ipynb", "binary or media"),
    ("static/jquery.min.js", "minified bundle"),
    ("static/app.js.map", "binary or media"),
])
def test_filter_drops_what_would_pollute_retrieval(path, reason_fragment):
    assert reason_fragment in (rag_ingest._repo_skip_reason(path, 100) or "")


@pytest.mark.parametrize("path", ["README.md", "src/main.py", "docs/guide.rst", "LICENSE", "Makefile"])
def test_filter_keeps_source_markdown_and_text(path):
    assert rag_ingest._repo_skip_reason(path, 100) is None


def test_filter_drops_an_oversized_file():
    assert "larger than" in rag_ingest._repo_skip_reason("src/generated.py", 10 * 1024 * 1024)


@pytest.mark.parametrize("path,kind", [
    ("README.md", "markdown"), ("docs/a.mdx", "markdown"),
    ("notes.txt", "text"), ("LICENSE", "text"), ("docs/x.rst", "text"),
    ("src/main.py", "code"), ("web/app.tsx", "code"),
])
def test_kind_labels_markdown_text_and_code(path, kind):
    assert rag_ingest._repo_kind(path) == kind


# --- End to end over a fake tarball -------------------------------------------

def test_from_repo_produces_one_result_per_indexable_file(fake_github):
    fake_github({
        "README.md": (BODY + "The install command is `pip install thing`. ").encode(),
        "src/main.py": (BODY + "def main(): return 1\n").encode(),
        "node_modules/dep/index.js": (BODY + "module.exports = 1").encode(),
        "logo.png": b"\x89PNG" + b"\x00" * 400,
        "uv.lock": (BODY + "lock").encode(),
    })
    got = rag_ingest.from_repo("https://github.com/owner/repo")
    assert got.ok
    assert sorted(f.title for f in got.files) == ["README.md", "src/main.py"]
    assert got.skipped == 3
    assert got.group_key == "github:owner/repo"
    assert got.resolved_ref == "abc1234"


def test_from_repo_records_per_file_provenance(fake_github):
    fake_github({"docs/guide.md": (BODY + "how to deploy").encode()})
    got = rag_ingest.from_repo("owner/repo")
    doc = got.files[0]
    assert doc.title == "docs/guide.md"
    assert doc.kind == "markdown"
    assert doc.source == "repo"
    assert doc.source_ref == "https://github.com/owner/repo/blob/abc1234/docs/guide.md"


def test_from_repo_uses_an_explicit_ref_in_the_blob_url(fake_github):
    fake_github({"README.md": (BODY + "hello").encode()})
    got = rag_ingest.from_repo("owner/repo", ref="v2")
    assert got.resolved_ref == "v2"
    assert "/blob/v2/README.md" in got.files[0].source_ref


def test_from_repo_drops_binary_content_that_passed_the_extension_filter(fake_github):
    # No skip-listed extension, but the bytes are not UTF-8 — the sniff catches it.
    fake_github({
        "README.md": (BODY + "hello").encode(),
        "data/blob.dat": b"\xff\xfe\x00\x01" * 100,
    })
    got = rag_ingest.from_repo("owner/repo")
    assert [f.title for f in got.files] == ["README.md"]
    assert got.skipped == 1


def test_from_repo_drops_a_stub_file_below_the_character_floor(fake_github):
    fake_github({"README.md": (BODY + "hello").encode(), "src/__init__.py": b"\n"})
    got = rag_ingest.from_repo("owner/repo")
    assert [f.title for f in got.files] == ["README.md"]


def test_from_repo_keeps_only_the_first_of_two_identical_files(fake_github):
    """Two byte-identical files share one sha, and sha is the catalog identity —
    indexing both would make the second silently replace the first's row."""
    same = (BODY + "MIT License, permission is hereby granted.").encode()
    fake_github({"LICENSE": same, "packages/sub/LICENSE": same})
    got = rag_ingest.from_repo("owner/repo")
    assert [f.title for f in got.files] == ["LICENSE"]
    assert got.skipped == 1


def test_from_repo_ignores_directory_and_symlink_members(monkeypatch):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        d = tarfile.TarInfo(f"{ROOT}/docs")
        d.type = tarfile.DIRTYPE
        tar.addfile(d)
        link = tarfile.TarInfo(f"{ROOT}/docs/link.md")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../../etc/passwd"
        tar.addfile(link)
        body = (BODY + "real content").encode()
        f = tarfile.TarInfo(f"{ROOT}/README.md")
        f.size = len(body)
        tar.addfile(f, io.BytesIO(body))
    monkeypatch.setattr(rag_ingest, "_fetch_repo_tarball", lambda ref: (buf.getvalue(), ""))
    got = rag_ingest.from_repo("owner/repo")
    assert [f.title for f in got.files] == ["README.md"]


def test_from_repo_reports_a_private_or_missing_repository_clearly(fake_github):
    fake_github({}, error=(
        "GitHub has no public repository 'owner/repo'. Either it does not exist, "
        "the ref is wrong, or it is private - private repositories are not supported"
    ))
    got = rag_ingest.from_repo("owner/repo")
    assert not got.ok
    assert "private repositories are not supported" in got.reason


def test_from_repo_rejects_a_url_that_is_not_a_repository():
    got = rag_ingest.from_repo("https://example.com/not-a-repo-at-all")
    assert not got.ok and "GitHub repository URL" in got.reason


def test_from_repo_reports_a_repository_with_nothing_indexable(fake_github):
    fake_github({"logo.png": b"\x89PNG" + b"\x00" * 400})
    got = rag_ingest.from_repo("owner/repo")
    assert not got.ok and "no indexable text files" in got.reason


def test_from_repo_caps_the_number_of_files(fake_github, monkeypatch):
    monkeypatch.setattr(rag_ingest, "_REPO_MAX_FILES", 3)
    fake_github({f"doc{i}.md": (BODY + f"unique body number {i}").encode() for i in range(10)})
    got = rag_ingest.from_repo("owner/repo")
    assert len(got.files) == 3 and got.skipped == 7


@pytest.mark.parametrize("value", [
    # Regression: the first parser made the "github.com/" prefix optional AND
    # allowed dots in the owner, so any two-segment URL on any host parsed as a
    # repo and the failure surfaced as "no public repository 'example.com/x'".
    "https://example.com/not-a-repo-at-all",
    "https://gitlab.com/owner/repo",
    "example.com/some/path",
])
def test_parse_repo_url_rejects_non_github_hosts(value):
    assert rag_ingest.parse_repo_url(value) is None
