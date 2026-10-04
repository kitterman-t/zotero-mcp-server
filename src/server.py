#!/usr/bin/env python3
"""
Zotero MCP Server - Model Context Protocol server for Zotero integration.

This server provides tools and resources for interacting with Zotero libraries,
using the latest MCP paradigms and the official Python SDK.
"""

import os
import re
import sys
import json
import logging
import tempfile
from typing import Any, Optional
import requests
import arxiv
from dotenv import load_dotenv
from pyzotero import zotero
from mcp.server.fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger('zotero-mcp-server')

# Load environment variables
load_dotenv()

# Initialize FastMCP server
mcp = FastMCP("Zotero MCP Server")

# Global Zotero client instance
zot: Optional[zotero.Zotero] = None


def init_zotero_client():
    """Initialize the Zotero client with credentials from environment."""
    global zot

    api_key = os.getenv('ZOTERO_API_KEY')
    user_id = os.getenv('ZOTERO_USER_ID')
    group_id = os.getenv('ZOTERO_GROUP_ID')

    if not api_key:
        logger.error("ZOTERO_API_KEY environment variable not set")
        return

    try:
        # Prioritize user library over group library
        if user_id:
            zot = zotero.Zotero(user_id, 'user', api_key)
            logger.info(f"Initialized Zotero client for user {user_id}")
        elif group_id:
            zot = zotero.Zotero(group_id, 'group', api_key)
            logger.info(f"Initialized Zotero client for group {group_id}")
        else:
            logger.error("Either ZOTERO_USER_ID or ZOTERO_GROUP_ID must be set")
    except Exception as e:
        logger.error(f"Error initializing Zotero client: {str(e)}")


def ensure_client():
    """Ensure Zotero client is initialized."""
    if zot is None:
        raise RuntimeError("Zotero client not initialized. Check API credentials.")


# ============================================================================
# SECURITY - Path Validation & Sandboxing
# ============================================================================

DEFAULT_UPLOAD_DIRS = ("~/Downloads", "/tmp")


def get_allowed_upload_dirs() -> list[str]:
    """Directories upload_attachment may read from, with symlinks resolved."""
    allowed = [os.path.expanduser(p) for p in DEFAULT_UPLOAD_DIRS]

    custom_dir = os.getenv('ZOTERO_ALLOWED_UPLOAD_DIR')
    if custom_dir:
        allowed.append(os.path.expanduser(custom_dir))

    # realpath, not abspath: on macOS /tmp is itself a link to /private/tmp,
    # and both sides of the comparison must be resolved the same way.
    return [os.path.realpath(p) for p in allowed]


def validate_path(file_path: str) -> str:
    """
    Return the resolved path of file_path if it lies inside an allowed directory.

    Symlinks are resolved before the check, so a link placed inside ~/Downloads
    that points at ~/.ssh is judged by where it points, not where it sits.
    Raises PermissionError otherwise.
    """
    real_path = os.path.realpath(os.path.expanduser(file_path))

    for safe_dir in get_allowed_upload_dirs():
        try:
            if os.path.commonpath([safe_dir, real_path]) == safe_dir:
                return real_path
        except ValueError:
            # Different drives on Windows have no common path.
            continue

    raise PermissionError(
        f"Access denied to {file_path}: it is not inside an allowed upload "
        "directory (~/Downloads, /tmp, or ZOTERO_ALLOWED_UPLOAD_DIR)."
    )


def first_created_item(response: dict[str, Any]) -> dict[str, Any]:
    """Return the first item from a create_items response.

    The Zotero API keys "successful" by the item's position as a string
    ("0"), but some pyzotero versions have returned a list, so accept both.
    """
    successful = response.get("successful") or {}
    if isinstance(successful, dict):
        item = successful.get("0")
    else:
        item = successful[0] if successful else None
    if not item:
        raise RuntimeError(f"Zotero did not create the item: {json.dumps(response)}")
    return item


# ============================================================================
# RESOURCES - Read-only data access
# ============================================================================

@mcp.resource("zotero://collections")
def get_collections() -> str:
    """List of collections in the Zotero library."""
    ensure_client()
    collections = zot.collections()
    return json.dumps(collections, indent=2)


@mcp.resource("zotero://items/top")
def get_top_items() -> str:
    """Top-level items in the Zotero library."""
    ensure_client()
    items = zot.top(limit=50)
    return json.dumps(items, indent=2)


@mcp.resource("zotero://items/recent")
def get_recent_items() -> str:
    """Recently added or modified items in the Zotero library."""
    ensure_client()
    items = zot.items(limit=20, sort="dateModified", direction="desc")
    return json.dumps(items, indent=2)


@mcp.resource("zotero://collections/{collection_key}/items")
def get_collection_items(collection_key: str) -> str:
    """Items in a specific Zotero collection."""
    ensure_client()
    items = zot.collection_items(collection_key)
    return json.dumps(items, indent=2)


@mcp.resource("zotero://items/{item_key}")
def get_item(item_key: str) -> str:
    """Details of a specific Zotero item."""
    ensure_client()
    item = zot.item(item_key)
    return json.dumps(item, indent=2)


@mcp.resource("zotero://items/{item_key}/citation/{style}")
def get_item_citation(item_key: str, style: str) -> str:
    """Citation for a specific Zotero item in a specific style."""
    ensure_client()
    citation = zot.item(item_key, format="citation", style=style)
    return citation


# ============================================================================
# TOOLS - Actions and operations
# ============================================================================

@mcp.tool()
def search_items(
    query: str,
    collection_key: Optional[str] = None,
    limit: int = 20
) -> str:
    """
    Search for items in the Zotero library.

    Args:
        query: Search query string
        collection_key: Optional collection key to search within
        limit: Maximum number of results to return (default: 20)

    Returns:
        JSON string containing search results
    """
    ensure_client()

    search_params = {"q": query, "limit": limit}

    if collection_key:
        items = zot.collection_items_top(collection_key, **search_params)
    else:
        items = zot.items(**search_params)

    result = {
        "query": query,
        "count": len(items),
        "results": items
    }

    return json.dumps(result, indent=2)


@mcp.tool()
def get_citation(item_key: str, style: str = "apa") -> str:
    """
    Get citation for a specific item.

    Args:
        item_key: The Zotero item key
        style: Citation style (e.g., apa, mla, chicago). Default: apa

    Returns:
        Formatted citation string
    """
    ensure_client()
    citation = zot.item(item_key, format="citation", style=style)
    return citation


@mcp.tool()
def add_item(
    item_type: str,
    title: str,
    creators: Optional[list[dict[str, str]]] = None,
    collection_key: Optional[str] = None,
    additional_fields: Optional[dict[str, Any]] = None
) -> str:
    """
    Add a new item to the Zotero library.

    Args:
        item_type: Item type (e.g., journalArticle, book, webpage)
        title: Item title
        creators: List of creators with format [{"creatorType": "author", "firstName": "...", "lastName": "..."}]
        collection_key: Optional collection key to add the item to
        additional_fields: Additional fields (e.g., date, url, publisher)

    Returns:
        JSON string with creation response
    """
    ensure_client()

    # Create item template
    template = zot.item_template(item_type)

    # Set title
    template["title"] = title

    # Set creators
    if creators:
        template["creators"] = creators

    # Set additional fields
    if additional_fields:
        for key, value in additional_fields.items():
            template[key] = value

    # Create item
    response = zot.create_items([template])

    # Add to collection if specified
    if collection_key and response.get("success"):
        # addto_collection needs the created item dict (key, version and data),
        # not a list of keys.
        zot.addto_collection(collection_key, first_created_item(response))

    return json.dumps(response, indent=2)


@mcp.tool()
def get_bibliography(item_keys: list[str], style: str = "apa") -> str:
    """
    Get bibliography for multiple items.

    Args:
        item_keys: List of Zotero item keys
        style: Citation style (e.g., apa, mla, chicago). Default: apa

    Returns:
        Formatted bibliography string
    """
    ensure_client()
    bibliography = zot.bibliography(item_keys, style=style)
    return bibliography


@mcp.tool()
def create_collection(name: str, parent_key: Optional[str] = None) -> str:
    """
    Create a new collection in the Zotero library.

    Args:
        name: Name of the new collection
        parent_key: Optional parent collection key for nested collections

    Returns:
        JSON string with creation response
    """
    ensure_client()

    collection_data = {"name": name}
    if parent_key:
        collection_data["parentCollection"] = parent_key

    response = zot.create_collections([collection_data])
    return json.dumps(response, indent=2)


@mcp.tool()
def update_item(
    item_key: str,
    updates: dict[str, Any]
) -> str:
    """
    Update an existing item in the Zotero library.

    Args:
        item_key: The Zotero item key to update
        updates: Dictionary of fields to update

    Returns:
        JSON string with update response
    """
    ensure_client()

    # Get the existing item
    item = zot.item(item_key)

    # Update fields
    for key, value in updates.items():
        item[key] = value

    # Update the item
    response = zot.update_item(item)
    return json.dumps(response, indent=2)


@mcp.tool()
def delete_item(item_key: str) -> str:
    """
    Delete an item from the Zotero library.

    Args:
        item_key: The Zotero item key to delete

    Returns:
        Success message
    """
    ensure_client()

    # Get item version for deletion
    item = zot.item(item_key)
    version = item.get('version')

    # Delete the item
    zot.delete_item(item, version=version)

    return json.dumps({"success": True, "message": f"Item {item_key} deleted"})


@mcp.tool()
def get_item_types() -> str:
    """
    Get list of all available Zotero item types.

    Returns:
        JSON string containing all item types
    """
    ensure_client()
    item_types = zot.item_types()
    return json.dumps(item_types, indent=2)


@mcp.tool()
def get_item_fields(item_type: str) -> str:
    """
    Get available fields for a specific item type.

    Args:
        item_type: The item type to get fields for (e.g., journalArticle, book)

    Returns:
        JSON string containing available fields
    """
    ensure_client()
    fields = zot.item_type_fields(item_type)
    return json.dumps(fields, indent=2)


@mcp.tool()
def upload_attachment(item_key: str, file_path: str) -> str:
    """
    Upload a file as an attachment to an existing Zotero item.

    Only files inside ~/Downloads, /tmp, or the directory named by
    ZOTERO_ALLOWED_UPLOAD_DIR can be uploaded, so a model cannot be talked
    into sending arbitrary local files to the Zotero cloud.

    Args:
        item_key: The parent Zotero item key
        file_path: Path to the file to upload

    Returns:
        JSON string with the upload result
    """
    ensure_client()

    try:
        safe_path = validate_path(file_path)
    except PermissionError:
        logger.warning(f"Blocked upload from outside the allowed directories: {file_path}")
        raise

    if not os.path.isfile(safe_path):
        raise FileNotFoundError(f"Not a file: {file_path}")

    result = zot.attachment_simple([safe_path], item_key)
    return json.dumps(result, indent=2)


# New-style IDs (2101.12345, optional version) and old-style IDs, which carry
# an archive name and a slash (hep-th/9901001).
ARXIV_ID_RE = re.compile(
    r"^(?:\d{4}\.\d{4,5}|[a-z][a-z\-]*(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?$"
)

# arXiv asks automated clients to identify themselves rather than pose as a
# browser.
USER_AGENT = "zotero-mcp-server (+https://github.com/kitterman-t/zotero-mcp-server)"

# A cap on the PDF download, enforced while streaming, so a bad response
# cannot fill the disk before the size is known.
MAX_PDF_BYTES = 100 * 1024 * 1024


def normalize_arxiv_id(raw: str) -> str:
    """Accept an arXiv ID, an "arXiv:" prefixed ID, or an abs/pdf URL."""
    value = raw.strip()
    value = re.sub(r"^arxiv:", "", value, flags=re.IGNORECASE)
    match = re.match(r"^https?://(?:www\.|export\.)?arxiv\.org/(?:abs|pdf)/(.+?)(?:\.pdf)?/?$", value)
    if match:
        value = match.group(1)
    if not ARXIV_ID_RE.match(value):
        raise ValueError(f"Not an arXiv ID: {raw!r}")
    return value


def arxiv_creators(authors: list[Any]) -> list[dict[str, str]]:
    """Map arXiv author names to Zotero creators.

    arXiv gives one display name per author. The last word becomes the last
    name, so "John A. Smith" is Smith, John A.; a one-word name uses Zotero's
    single-field form instead of leaving the last name empty.
    """
    creators = []
    for author in authors:
        first, _, last = author.name.strip().rpartition(" ")
        if first:
            creators.append({"creatorType": "author", "firstName": first, "lastName": last})
        else:
            creators.append({"creatorType": "author", "name": last})
    return creators


def find_existing_arxiv_item(arxiv_id: str) -> Optional[dict[str, Any]]:
    """Return a library item that already holds this paper, in any version."""
    base_id = re.sub(r"v\d+$", "", arxiv_id)
    for item in zot.items(q=base_id, qmode="everything", limit=25):
        data = item.get("data", {})
        archive_id = re.sub(r"v\d+$", "", data.get("archiveID", ""))
        url = data.get("url", "")
        if archive_id == f"arXiv:{base_id}" or re.search(
            rf"arxiv\.org/(?:abs|pdf)/{re.escape(base_id)}(?:v\d+)?(?:\.pdf)?$", url
        ):
            return item
    return None


def download_pdf(url: str, dest: str) -> None:
    """Stream a PDF to dest, refusing anything over MAX_PDF_BYTES or not a PDF."""
    with requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=(10, 60), stream=True) as response:
        response.raise_for_status()
        received = 0
        with open(dest, "wb") as handle:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                received += len(chunk)
                if received > MAX_PDF_BYTES:
                    raise ValueError(f"PDF is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB")
                handle.write(chunk)
    with open(dest, "rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise ValueError("Download is not a PDF")


@mcp.tool()
def ingest_arxiv_paper(
    arxiv_id: str,
    collection_key: Optional[str] = None,
    allow_duplicate: bool = False,
) -> str:
    """
    Add an arXiv paper to Zotero as a preprint, with its metadata and PDF.

    If the library already holds the paper (any version), nothing is created
    and the existing item key is returned, unless allow_duplicate is true.

    Args:
        arxiv_id: An arXiv ID (2101.12345, 2101.12345v2, hep-th/9901001),
            optionally prefixed with "arXiv:", or an arxiv.org abs/pdf URL
        collection_key: Optional Zotero collection to add the item to
        allow_duplicate: Create a new item even if the paper is already there

    Returns:
        JSON string with the item key and whether the PDF was attached
    """
    ensure_client()

    arxiv_id = normalize_arxiv_id(arxiv_id)

    if not allow_duplicate:
        existing = find_existing_arxiv_item(arxiv_id)
        if existing:
            return json.dumps({
                "item_key": existing["key"],
                "created": False,
                "message": "This paper is already in the library",
            }, indent=2)

    logger.info(f"Fetching arXiv metadata for {arxiv_id}")
    client = arxiv.Client()
    paper = next(client.results(arxiv.Search(id_list=[arxiv_id])), None)
    if paper is None:
        raise ValueError(f"arXiv has no paper with ID {arxiv_id}")

    short_id = paper.get_short_id()
    base_id = re.sub(r"v\d+$", "", short_id)

    template = zot.item_template("preprint")
    template["title"] = paper.title
    template["creators"] = arxiv_creators(paper.authors)
    template["abstractNote"] = paper.summary
    template["date"] = paper.published.strftime("%Y-%m-%d")
    template["url"] = paper.entry_id
    template["repository"] = "arXiv"
    template["archiveID"] = f"arXiv:{base_id}"
    # arXiv registers a DataCite DOI for every paper; a journal DOI, when the
    # paper was later published, belongs to that other version.
    template["DOI"] = f"10.48550/arXiv.{base_id}"
    extra = [f"arXiv categories: {', '.join(paper.categories)}"]
    if paper.doi:
        extra.append(f"Published version DOI: {paper.doi}")
    if paper.journal_ref:
        extra.append(f"Journal reference: {paper.journal_ref}")
    template["extra"] = "\n".join(extra)

    response = zot.create_items([template])
    item = first_created_item(response)
    item_key = item["key"]

    if collection_key:
        zot.addto_collection(collection_key, item)

    result: dict[str, Any] = {
        "item_key": item_key,
        "created": True,
        "title": paper.title,
        "arxiv_id": short_id,
        "pdf_attached": False,
    }

    # The item exists at this point, so a failed PDF is reported in the
    # result instead of raised, and the caller can retry the attachment.
    if not paper.pdf_url:
        result["pdf_error"] = "arXiv lists no PDF for this paper"
        return json.dumps(result, indent=2)

    try:
        with tempfile.TemporaryDirectory(prefix="zotero-arxiv-") as tmp_dir:
            pdf_path = os.path.join(tmp_dir, f"{base_id.replace('/', '_')}.pdf")
            download_pdf(paper.pdf_url, pdf_path)
            zot.attachment_simple([pdf_path], item_key)
        result["pdf_attached"] = True
    except Exception as e:
        logger.error(f"PDF download or upload failed for {short_id}: {e}")
        result["pdf_error"] = str(e)

    return json.dumps(result, indent=2)


def main():
    """Main entry point for the server."""
    logger.info("Starting Zotero MCP Server")

    # Initialize Zotero client
    init_zotero_client()

    # Run the MCP server (stdio transport by default)
    mcp.run()


if __name__ == "__main__":
    main()
