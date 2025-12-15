#!/usr/bin/env python3
"""
Zotero MCP Server - Model Context Protocol server for Zotero integration.

This server provides tools and resources for interacting with Zotero libraries,
using the latest MCP paradigms and the official Python SDK.
"""

import os
import sys
import json
import logging
from typing import Any, Optional
import time
import requests
import datetime
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
        # Fix: handle explicit list or dict key depending on Pyzotero version
        try:
            item_data = response["successful"][0]
        except (KeyError, TypeError, IndexError):
             # Fallback if it is a dict with string key "0"
            item_data = response["successful"]["0"]
            
        zot.addto_collection(collection_key, item_data)

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
    Upload a file attachment to a Zotero item.

    Args:
        item_key: The parent Zotero item key
        file_path: Absolute path to the file to upload

    Returns:
        JSON string with upload result
    """
    ensure_client()

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    # simple attachment upload
    # returns checking result or identification of successful upload
    try:
        result = zot.attachment_simple([file_path], item_key)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error uploading attachment: {str(e)}")
        raise RuntimeError(f"Upload failed: {str(e)}")


@mcp.tool()
def ingest_arxiv_paper(arxiv_id: str, collection_key: Optional[str] = None) -> str:
    """
    Robustly ingest an ArXiv paper into Zotero with full metadata and PDF.

    Args:
        arxiv_id: The ArXiv ID (e.g., '2101.12345')
        collection_key: Optional Zotero collection to add to

    Returns:
        JSON string with result details
    """
    ensure_client()
    
    # 1. Fetch from ArXiv
    logger.info(f"Fetching metadata for ArXiv ID: {arxiv_id}")
    try:
        search = arxiv.Search(id_list=[arxiv_id])
        paper = next(search.results())
    except Exception as e:
        return json.dumps({"error": f"ArXiv fetch failed: {str(e)}"}, indent=2)

    # 2. Map Metadata
    creators = [{"creatorType": "author", "firstName": a.name.split(" ")[0], "lastName": " ".join(a.name.split(" ")[1:])} for a in paper.authors]
    
    # Format "Extra" field for AI agents
    ingest_time = datetime.datetime.now().isoformat()
    extra_metadata = (
        f"ArXiv_ID: {arxiv_id}\n"
        f"AI_Ready: true\n"
        f"Ingested_Date: {ingest_time}\n"
        f"Categories: {', '.join(paper.categories)}\n"
        f"ArXiv_URL: {paper.entry_id}\n"
        f"PDF_URL: {paper.pdf_url}"
    )

    item_template = zot.item_template('journalArticle')
    item_template['title'] = paper.title
    item_template['creators'] = creators
    item_template['abstractNote'] = paper.summary
    item_template['date'] = paper.published.strftime("%Y-%m-%d")
    item_template['url'] = paper.entry_id
    item_template['DOI'] = paper.doi if paper.doi else ""
    item_template['extra'] = extra_metadata

    # 3. Create Item
    logger.info("Creating Zotero item...")
    try:
        response = zot.create_items([item_template])
        if response.get('successful'):
            # Handle list vs dict response quirk
            try:
                item_data = response['successful'][0]
            except (KeyError, TypeError, IndexError):
                item_data = response['successful']['0']
            
            item_key = item_data['key']
            
            if collection_key:
                zot.addto_collection(collection_key, item_data)
        else:
            return json.dumps({"error": "Failed to create Zotero item", "details": response}, indent=2)
    except Exception as e:
         return json.dumps({"error": f"Zotero creation failed: {str(e)}"}, indent=2)

    # 4. Download and Attach PDF
    logger.info("Downloading PDF...")
    pdf_path = f"/tmp/{arxiv_id}.pdf"
    try:
        # Use a custom user agent to avoid bot blocking
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'}
        response = requests.get(paper.pdf_url, headers=headers)
        response.raise_for_status()
        
        with open(pdf_path, 'wb') as f:
            f.write(response.content)
            
        logger.info(f"Attaching PDF to item {item_key}...")
        zot.attachment_simple([pdf_path], item_key)
        
    except Exception as e:
        logger.error(f"PDF download/upload failed: {str(e)}")
        # We don't fail the whole tool if just PDF fails, but we note it
        return json.dumps({
            "success": True, 
            "item_key": item_key, 
            "message": "Item created but PDF upload failed",
            "error_details": str(e)
        }, indent=2)
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

    return json.dumps({
        "success": True,
        "item_key": item_key,
        "title": paper.title,
        "arxiv_id": arxiv_id,
        "message": "Paper ingested and PDF attached successfully"
    }, indent=2)


def main():
    """Main entry point for the server."""
    logger.info("Starting Zotero MCP Server")

    # Initialize Zotero client
    init_zotero_client()

    # Run the MCP server (stdio transport by default)
    mcp.run()


if __name__ == "__main__":
    main()
