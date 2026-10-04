"""ingest_arxiv_paper, with arXiv, the PDF download and Zotero all faked."""

import datetime
import json
import os

import arxiv
import pytest

from src import server

PDF_BYTES = b"%PDF-1.4\n%fake test paper\n"


def make_paper(short_id="2101.12345v2", pdf=True, **overrides):
    links = [arxiv.Result.Link(f"https://arxiv.org/abs/{short_id}", rel="alternate")]
    if pdf:
        links.append(arxiv.Result.Link(f"https://arxiv.org/pdf/{short_id}", title="pdf", rel="related"))
    fields = dict(
        entry_id=f"http://arxiv.org/abs/{short_id}",
        published=datetime.datetime(2021, 1, 28, tzinfo=datetime.timezone.utc),
        title="A Test Paper",
        authors=[arxiv.Result.Author("John A. Smith"), arxiv.Result.Author("Plato")],
        summary="An abstract.",
        categories=["cs.CL", "cs.AI"],
        links=links,
    )
    fields.update(overrides)
    return arxiv.Result(**fields)


class FakeClient:
    def __init__(self, papers):
        self.papers = papers
        self.searches = []

    def results(self, search):
        self.searches.append(search.id_list)
        return iter(self.papers)


class FakeZotero:
    def __init__(self, existing=()):
        self.existing = list(existing)
        self.created = []
        self.collections = []
        self.attachments = []
        self.searches = []

    def item_template(self, item_type):
        return {
            "itemType": item_type, "title": "", "creators": [], "abstractNote": "",
            "repository": "", "archiveID": "", "date": "", "DOI": "", "url": "",
            "extra": "", "collections": [],
        }

    def items(self, **params):
        self.searches.append(params)
        return self.existing

    def create_items(self, items):
        self.created.extend(items)
        return {
            "successful": {"0": {"key": "NEWKEY01", "version": 1, "data": {"collections": []}}},
            "success": {"0": "NEWKEY01"},
            "unchanged": {},
            "failed": {},
        }

    def addto_collection(self, collection, payload):
        self.collections.append((collection, payload["key"]))

    def attachment_simple(self, files, parent):
        path = files[0]
        with open(path, "rb") as handle:
            self.attachments.append((os.path.basename(path), parent, handle.read(5)))
        self.last_path = path
        return {"success": [os.path.basename(path)]}


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start:start + chunk_size]


@pytest.fixture
def world(monkeypatch):
    """Fakes for Zotero, arXiv and HTTP; returns them for assertions."""
    zot = FakeZotero()
    client = FakeClient([make_paper()])
    requests_made = []

    def fake_get(url, **kwargs):
        requests_made.append((url, kwargs))
        return FakeResponse(world.body)

    monkeypatch.setattr(server, "zot", zot)
    monkeypatch.setattr(server.arxiv, "Client", lambda: client)
    monkeypatch.setattr(server.requests, "get", fake_get)

    class World:
        pass

    world = World()
    world.zot, world.client, world.requests, world.body = zot, client, requests_made, PDF_BYTES
    return world


@pytest.mark.parametrize("raw, expected", [
    ("2101.12345", "2101.12345"),
    ("2101.12345v2", "2101.12345v2"),
    ("arXiv:2101.12345", "2101.12345"),
    ("  ARXIV:2101.1234 ", "2101.1234"),
    ("https://arxiv.org/abs/2101.12345v2", "2101.12345v2"),
    ("https://arxiv.org/pdf/2101.12345.pdf", "2101.12345"),
    ("hep-th/9901001", "hep-th/9901001"),
    ("math.GT/0309136v1", "math.GT/0309136v1"),
    ("https://arxiv.org/abs/quant-ph/0201082", "quant-ph/0201082"),
])
def test_normalize_accepts_the_forms_people_paste(raw, expected):
    assert server.normalize_arxiv_id(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "2101.123", "../../etc/passwd", "hep-th/9901001/../../x", "10.1000/xyz", "2101.12345 extra",
])
def test_normalize_refuses_anything_else(raw):
    with pytest.raises(ValueError):
        server.normalize_arxiv_id(raw)


def test_authors_keep_middle_initials_in_the_first_name():
    creators = server.arxiv_creators([arxiv.Result.Author(" John A. Smith "), arxiv.Result.Author("Plato")])
    assert creators == [
        {"creatorType": "author", "firstName": "John A.", "lastName": "Smith"},
        {"creatorType": "author", "name": "Plato"},
    ]


def test_ingest_creates_a_preprint_and_attaches_the_pdf(world):
    result = json.loads(server.ingest_arxiv_paper("arXiv:2101.12345v2", collection_key="COLL0001"))

    assert result == {
        "item_key": "NEWKEY01", "created": True, "title": "A Test Paper",
        "arxiv_id": "2101.12345v2", "pdf_attached": True,
    }
    (item,) = world.zot.created
    assert item["itemType"] == "preprint"
    assert item["repository"] == "arXiv"
    assert item["archiveID"] == "arXiv:2101.12345"
    assert item["DOI"] == "10.48550/arXiv.2101.12345"
    assert item["date"] == "2021-01-28"
    assert item["creators"][0] == {"creatorType": "author", "firstName": "John A.", "lastName": "Smith"}
    assert item["extra"] == "arXiv categories: cs.CL, cs.AI"
    assert world.zot.collections == [("COLL0001", "NEWKEY01")]
    assert world.zot.attachments == [("2101.12345.pdf", "NEWKEY01", b"%PDF-")]


def test_the_download_identifies_itself_and_has_a_timeout(world):
    server.ingest_arxiv_paper("2101.12345")
    ((url, kwargs),) = world.requests
    assert url == "https://arxiv.org/pdf/2101.12345v2"
    assert "Mozilla" not in kwargs["headers"]["User-Agent"]
    assert kwargs["timeout"]
    assert kwargs["stream"] is True


def test_the_temporary_pdf_is_removed_afterwards(world):
    server.ingest_arxiv_paper("2101.12345")
    assert not os.path.exists(world.zot.last_path)


def test_an_old_style_id_with_a_slash_gets_a_flat_file_name(world):
    world.client.papers = [make_paper("hep-th/9901001v1")]
    result = json.loads(server.ingest_arxiv_paper("hep-th/9901001"))
    assert result["pdf_attached"] is True
    assert world.zot.attachments[0][0] == "hep-th_9901001.pdf"
    assert world.zot.created[0]["archiveID"] == "arXiv:hep-th/9901001"


def test_a_paper_already_in_the_library_is_not_added_again(world):
    world.zot.existing = [{"key": "OLDKEY01", "data": {"archiveID": "arXiv:2101.12345", "url": ""}}]
    result = json.loads(server.ingest_arxiv_paper("2101.12345v3"))
    assert result == {"item_key": "OLDKEY01", "created": False, "message": "This paper is already in the library"}
    assert world.zot.created == []
    assert world.client.searches == []


def test_an_item_found_by_its_arxiv_url_counts_as_a_duplicate(world):
    world.zot.existing = [{"key": "OLDKEY02", "data": {"url": "https://arxiv.org/abs/2101.12345v1"}}]
    result = json.loads(server.ingest_arxiv_paper("2101.12345"))
    assert result["created"] is False


def test_a_similar_id_is_not_a_duplicate(world):
    world.zot.existing = [{"key": "OTHER001", "data": {"archiveID": "arXiv:2101.123456", "url": ""}}]
    result = json.loads(server.ingest_arxiv_paper("2101.12345"))
    assert result["created"] is True


def test_allow_duplicate_creates_anyway(world):
    world.zot.existing = [{"key": "OLDKEY01", "data": {"archiveID": "arXiv:2101.12345", "url": ""}}]
    result = json.loads(server.ingest_arxiv_paper("2101.12345", allow_duplicate=True))
    assert result["created"] is True


def test_an_unknown_id_raises_and_creates_nothing(world):
    world.client.papers = []
    with pytest.raises(ValueError):
        server.ingest_arxiv_paper("2101.99999")
    assert world.zot.created == []


def test_a_failed_download_is_reported_not_called_success(world, monkeypatch):
    def broken_get(url, **kwargs):
        raise server.requests.ConnectionError("network down")

    monkeypatch.setattr(server.requests, "get", broken_get)
    result = json.loads(server.ingest_arxiv_paper("2101.12345"))
    assert result["item_key"] == "NEWKEY01"
    assert result["pdf_attached"] is False
    assert "network down" in result["pdf_error"]
    assert world.zot.attachments == []


def test_a_response_that_is_not_a_pdf_is_not_attached(world):
    world.body = b"<html>rate limited</html>"
    result = json.loads(server.ingest_arxiv_paper("2101.12345"))
    assert result["pdf_attached"] is False
    assert result["pdf_error"] == "Download is not a PDF"
    assert world.zot.attachments == []


def test_an_oversized_pdf_is_refused_while_streaming(world, monkeypatch):
    monkeypatch.setattr(server, "MAX_PDF_BYTES", 10)
    result = json.loads(server.ingest_arxiv_paper("2101.12345"))
    assert result["pdf_attached"] is False
    assert "larger than" in result["pdf_error"]


def test_a_paper_without_a_pdf_link_says_so(world):
    world.client.papers = [make_paper(pdf=False)]
    result = json.loads(server.ingest_arxiv_paper("2101.12345"))
    assert result["pdf_attached"] is False
    assert result["pdf_error"] == "arXiv lists no PDF for this paper"
    assert world.requests == []


def test_add_item_passes_the_created_item_to_addto_collection(world):
    server.add_item("book", "A Book", collection_key="COLL0002")
    assert world.zot.collections == [("COLL0002", "NEWKEY01")]
