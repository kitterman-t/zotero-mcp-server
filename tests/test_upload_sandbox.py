"""The upload sandbox: which local files upload_attachment will send to Zotero."""

import os

import pytest

from src import server


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """An allowed directory and an outside one, with no default directories."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    monkeypatch.setattr(server, "DEFAULT_UPLOAD_DIRS", ())
    monkeypatch.setenv("ZOTERO_ALLOWED_UPLOAD_DIR", str(allowed))
    return allowed, outside


def test_a_file_inside_the_allowed_directory_is_accepted(sandbox):
    allowed, _ = sandbox
    paper = allowed / "paper.pdf"
    paper.write_bytes(b"%PDF-1.4")
    assert server.validate_path(str(paper)) == os.path.realpath(paper)


def test_a_file_outside_is_refused(sandbox):
    _, outside = sandbox
    secret = outside / "id_rsa"
    secret.write_text("key")
    with pytest.raises(PermissionError):
        server.validate_path(str(secret))


def test_a_symlink_inside_that_points_outside_is_refused(sandbox):
    allowed, outside = sandbox
    secret = outside / "id_rsa"
    secret.write_text("key")
    link = allowed / "innocent.pdf"
    link.symlink_to(secret)
    with pytest.raises(PermissionError):
        server.validate_path(str(link))


def test_dot_dot_cannot_climb_out(sandbox):
    allowed, outside = sandbox
    (outside / "notes.txt").write_text("x")
    with pytest.raises(PermissionError):
        server.validate_path(str(allowed / ".." / "outside" / "notes.txt"))


def test_a_sibling_whose_name_starts_with_the_allowed_name_is_refused(sandbox):
    allowed, _ = sandbox
    sibling = allowed.parent / (allowed.name + "-evil")
    sibling.mkdir()
    (sibling / "x.pdf").write_bytes(b"%PDF-")
    with pytest.raises(PermissionError):
        server.validate_path(str(sibling / "x.pdf"))


class RecordingZotero:
    def __init__(self):
        self.uploads = []

    def attachment_simple(self, files, parent):
        self.uploads.append((files, parent))
        return {"success": [os.path.basename(files[0])]}


def test_upload_attachment_sends_the_resolved_path(sandbox, monkeypatch):
    allowed, _ = sandbox
    paper = allowed / "paper.pdf"
    paper.write_bytes(b"%PDF-1.4")
    zot = RecordingZotero()
    monkeypatch.setattr(server, "zot", zot)

    server.upload_attachment("ITEM1234", str(paper))

    assert zot.uploads == [([os.path.realpath(paper)], "ITEM1234")]


def test_upload_attachment_refuses_a_directory(sandbox, monkeypatch):
    allowed, _ = sandbox
    monkeypatch.setattr(server, "zot", RecordingZotero())
    with pytest.raises(FileNotFoundError):
        server.upload_attachment("ITEM1234", str(allowed))


def test_upload_attachment_refuses_outside_paths_before_touching_zotero(sandbox, monkeypatch):
    _, outside = sandbox
    secret = outside / "id_rsa"
    secret.write_text("key")
    zot = RecordingZotero()
    monkeypatch.setattr(server, "zot", zot)
    with pytest.raises(PermissionError):
        server.upload_attachment("ITEM1234", str(secret))
    assert zot.uploads == []
