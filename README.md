# Zotero MCP Server

A Model Context Protocol (MCP) server that integrates with Zotero, allowing AI applications to access and manipulate Zotero libraries.

Built with the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) following the latest MCP paradigms and best practices.

## What this fork adds

This is a fork of [cr625/zotero-mcp-server](https://github.com/cr625/zotero-mcp-server). It adds:

- **`ingest_arxiv_paper`**: give it an arXiv ID or link and it saves the paper as a Zotero preprint (arXiv ID, DOI, authors, abstract, categories) with the PDF attached. It skips papers already in the library, accepts old-style IDs such as `hep-th/9901001`, and reports a failed PDF download instead of calling it a success.
- **`upload_attachment`**: attaches a local file to an item, but only from `~/Downloads`, `/tmp` or a folder you name, with symlinks resolved first, so a model cannot be talked into uploading files from elsewhere on your machine.
- **A fix for `add_item`** with a collection, which passed the wrong value to pyzotero.
- **Offline tests and CI**: `pytest` runs with Zotero, arXiv and the network faked, on Linux and macOS for every push.
- **Dependency pins**: `mcp<2`, because the 2.x SDK renamed the server class this code uses and a fresh install would not start.

## Features

- Search for items in Zotero libraries
- Get citations and bibliographies
- Add new items to Zotero libraries
- Access collections and items
- Support for both personal and group libraries

## Installation

Requires Python 3.10 or newer.

1. Clone the repository:
   ```bash
   git clone https://github.com/kitterman-t/zotero-mcp-server.git
   cd zotero-mcp-server
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   ```

3. Activate the virtual environment:
   - On Linux/macOS:
     ```bash
     source venv/bin/activate
     ```
   - On Windows:
     ```bash
     venv\Scripts\activate
     ```

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit the `.env` file with your Zotero API credentials:
   ```
   ZOTERO_API_KEY=your_api_key_here
   ZOTERO_USER_ID=your_numeric_user_id_here
   # ZOTERO_GROUP_ID=your_group_id_here  # Uncomment to use a group library
   ```

   You need to set either `ZOTERO_USER_ID` (for personal libraries) or `ZOTERO_GROUP_ID` (for group libraries).

   To let `upload_attachment` read from one more folder besides `~/Downloads` and `/tmp`, set `ZOTERO_ALLOWED_UPLOAD_DIR`.

3. If you're not sure how to find your Zotero user ID, run:
   ```bash
   ./find_zotero_id.py
   ```

## Usage

### Running the Server

```bash
python src/server.py
```

The server will start and listen for JSON-RPC requests on standard input/output.

### Testing the Server

The offline tests need no Zotero account or network:

```bash
pip install pytest
pytest
```

`./simple_test.py` checks a running server against your real library.

### Integration with AI Applications

The Zotero MCP server can be integrated with AI applications that support the Model Context Protocol. See the `USAGE_GUIDE.md` file for detailed examples.

## Available Resources

- `zotero://collections`: List of collections in the Zotero library
- `zotero://items/top`: Top-level items in the Zotero library
- `zotero://items/recent`: Recently added or modified items in the Zotero library
- `zotero://collections/{collection_key}/items`: Items in a specific Zotero collection
- `zotero://items/{item_key}`: Details of a specific Zotero item
- `zotero://items/{item_key}/citation/{style}`: Citation for a specific Zotero item in a specific style

## Available Tools

- `search_items`: Search for items in the Zotero library
- `get_citation`: Get citation for a specific item
- `add_item`: Add a new item to the Zotero library
- `get_bibliography`: Get bibliography for multiple items
- `create_collection`: Create a new collection in the Zotero library
- `update_item`: Update an existing item in the Zotero library
- `delete_item`: Delete an item from the Zotero library
- `get_item_types`: Get list of all available Zotero item types
- `get_item_fields`: Get available fields for a specific item type
- `upload_attachment`: Attach a local file to an item, from the allowed folders only
- `ingest_arxiv_paper`: Add an arXiv paper as a preprint with its metadata and PDF, skipping papers already in the library

## Documentation

For more detailed information, see:

- `USAGE_GUIDE.md`: Comprehensive usage guide
- `test_client.py`: Interactive test client
- `simple_test.py`: Simple test script
- `find_zotero_id.py`: Helper script to find your Zotero IDs

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
