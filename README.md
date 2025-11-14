# Google Suite MCP Server

A Model Context Protocol (MCP) server for integrating Google Calendar and Gmail with AI applications like Claude.

## 🎯 Overview

This project implements a test MCP server that enables AI assistants to:
- Manage Google Calendar events (create, read, update, delete)
- Access and search Gmail messages
- Compose and send emails
- Retrieve calendar and email metadata

Built using:
- **MCP Protocol** - Anthropic's Model Context Protocol
- **Google APIs** - Calendar API & Gmail API
- **Python** - FastMCP framework

## 📋 Features

### Calendar Tools
- `list_calendar_events` - List upcoming calendar events
- `create_calendar_event` - Create new events with attendees
- `update_calendar_event` - Modify existing events
- `delete_calendar_event` - Remove events

### Gmail Tools
- `list_emails` - List inbox messages with filters
- `get_email_content` - Read full email content
- `send_email` - Compose and send emails
- `search_emails` - Advanced Gmail search
- `mark_email_read` - Mark messages as read

### Resources
- Calendar settings and timezone info
- Gmail profile and quota information

### Prompts
- Meeting scheduling templates
- Email summary templates
- Calendar report templates

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Google Cloud account
- Google Workspace account (Gmail + Calendar)

### Installation

1. **Clone the repository**
```bash
   git clone <your-repo-url>
   cd google-mcp-server
```

2. **Install dependencies**
```bash
   pip install -r requirements.txt
```

3. **Set up Google Cloud credentials**
   - See [SETUP.md](SETUP.md) for detailed instructions
   - Create OAuth 2.0 credentials
   - Download as `credentials.json` (not included in repo)

4. **Run the server**
```bash
   python google_suite_server.py
```

5. **Test with the client**
```bash
   python test_client.py google_suite_server.py
```

## 🧪 Testing

The project includes a comprehensive test suite:
```bash
python test_client.py google_suite_server.py
```

Tests cover:
- ✅ Tool discovery and execution
- ✅ Calendar operations (CRUD)
- ✅ Gmail operations (read, search, send)
- ✅ Resource access
- ✅ Prompt templates

## 💡 Usage Examples

### Using the MCP Server with Postman

This project exposes an MCP-compatible HTTP endpoint at:
 ```
http://127.0.0.1:8000/mcp
```

1. Open **Postman** → click **New** → **MCP** (or use the MCP sidebar).

2. Enter the server endpoint:
```
http://127.0.0.1:8000/mcp
```

3. Click **Connect**. Postman will automatically:

   - Negotiate an MCP session

   - Open the streaming SSE connection

   - Load all available tools

4. Select any tool from the Tools tab and fill in the input fields.

5. Press **Run** to execute the tool. Results will appear in the right panel, and streaming or multi-part outputs will show in real time.

This provides a simple UI for invoking the server’s Google Calendar, Gmail, and other MCP tools without needing a custom client.

### Programmatic Usage
```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server_params = StdioServerParameters(
    command="python",
    args=["google_suite_server.py"]
)

async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        
        # List calendar events
        result = await session.call_tool(
            "list_calendar_events",
            arguments={"max_results": 5}
        )
```

## 📊 Test Results

All tests passing ✅
- 9 tools discovered and tested
- 2 resources accessed
- 3 prompts validated
- Calendar CRUD operations verified
- Gmail operations verified

