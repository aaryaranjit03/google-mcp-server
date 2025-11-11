"""
Google Suite MCP Test Client
Tests the Google Suite MCP server with various operations
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from typing import Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class GoogleMCPClient:
    """Test client for Google Suite MCP Server"""
    
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.available_tools = []
        self.available_resources = []
        self.available_prompts = []
    
    async def connect(self, server_script_path: str):
        """Connect to the MCP server"""
        print("🔌 Connecting to Google Suite MCP Server...")
        
        # Configure server parameters
        server_params = StdioServerParameters(
            command="python",
            args=[server_script_path],
            env=None
        )
        
        # Create stdio client connection using context manager
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                self.session = session
                
                # Initialize connection
                await session.initialize()
                
                # List available capabilities
                await self.discover_capabilities()
                
                print("✓ Connected successfully!\n")
                
                # Run test suite
                await self.run_tests()
    
    async def discover_capabilities(self):
        """Discover available tools, resources, and prompts"""
        print("📋 Discovering server capabilities...")
        
        # List tools
        tools_result = await self.session.list_tools()
        self.available_tools = tools_result.tools
        print(f"  • Found {len(self.available_tools)} tools")
        
        # List resources
        resources_result = await self.session.list_resources()
        self.available_resources = resources_result.resources
        print(f"  • Found {len(self.available_resources)} resources")
        
        # List prompts
        prompts_result = await self.session.list_prompts()
        self.available_prompts = prompts_result.prompts
        print(f"  • Found {len(self.available_prompts)} prompts\n")
    
    def print_section(self, title: str):
        """Print a formatted section header"""
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}\n")
    
    async def test_list_tools(self):
        """Test: List all available tools"""
        self.print_section("TEST 1: List Available Tools")
        
        for i, tool in enumerate(self.available_tools, 1):
            print(f"{i}. {tool.name}")
            print(f"   Description: {tool.description}")
            if hasattr(tool, 'inputSchema'):
                print(f"   Input Schema: {json.dumps(tool.inputSchema, indent=2)}")
            print()
    
    async def test_calendar_operations(self):
        """Test: Calendar operations"""
        self.print_section("TEST 2: Calendar Operations")
        
        # Test 1: List calendar events
        print("📅 Listing upcoming calendar events...")
        try:
            result = await self.session.call_tool(
                "list_calendar_events",
                arguments={"max_results": 5, "days_ahead": 7}
            )
            
            for content in result.content:
                if hasattr(content, 'text'):
                    print(f"\n{content.text}")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        # Test 2: Create a calendar event
        print("\n📝 Creating a test calendar event...")
        try:
            # Calculate time for tomorrow at 2pm
            tomorrow = datetime.now() + timedelta(days=1)
            start_time = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(hours=1)
            
            # Format as ISO 8601 with timezone
            start_iso = start_time.strftime("%Y-%m-%dT%H:%M:%S-08:00")
            end_iso = end_time.strftime("%Y-%m-%dT%H:%M:%S-08:00")
            
            result = await self.session.call_tool(
                "create_calendar_event",
                arguments={
                    "summary": "MCP Test Meeting",
                    "start_time": start_iso,
                    "end_time": end_iso,
                    "description": "This is a test event created by MCP client",
                    "location": "Virtual"
                }
            )
            
            for content in result.content:
                if hasattr(content, 'text'):
                    response = json.loads(content.text)
                    if response.get("success"):
                        print(f"✓ Event created successfully!")
                        print(f"  Event ID: {response.get('event_id')}")
                        print(f"  Link: {response.get('html_link')}")
                        
                        # Store event ID for cleanup
                        self.test_event_id = response.get('event_id')
                    else:
                        print(f"❌ Failed to create event: {response.get('error')}")
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
        
        # Test 3: Update the event
        if hasattr(self, 'test_event_id'):
            print("\n✏️  Updating the test event...")
            try:
                result = await self.session.call_tool(
                    "update_calendar_event",
                    arguments={
                        "event_id": self.test_event_id,
                        "summary": "MCP Test Meeting (Updated)",
                        "description": "Updated description"
                    }
                )
                
                for content in result.content:
                    if hasattr(content, 'text'):
                        response = json.loads(content.text)
                        if response.get("success"):
                            print(f"✓ Event updated successfully!")
                        else:
                            print(f"❌ Failed to update event: {response.get('error')}")
            except Exception as e:
                print(f"❌ Error: {e}")
    
    async def test_gmail_operations(self):
        """Test: Gmail operations"""
        self.print_section("TEST 3: Gmail Operations")
        
        # Test 1: List emails
        print("📧 Listing inbox emails...")
        try:
            result = await self.session.call_tool(
                "list_emails",
                arguments={"max_results": 5, "query": "in:inbox"}
            )
            
            for content in result.content:
                if hasattr(content, 'text'):
                    emails_data = json.loads(content.text)
                    if "emails" in emails_data:
                        print(f"\nFound {emails_data['count']} emails:")
                        for email in emails_data['emails']:
                            print(f"\n  • Subject: {email.get('subject', 'No subject')}")
                            print(f"    From: {email.get('from', 'Unknown')}")
                            print(f"    Date: {email.get('date', 'Unknown')}")
                            snippet = email.get('snippet', '')
                            print(f"    Snippet: {snippet[:100]}...")
                        
                        # Store first email ID for further testing
                        if emails_data['emails']:
                            self.test_email_id = emails_data['emails'][0]['id']
                    else:
                        print(emails_data.get('message', 'No emails found'))
        except Exception as e:
            print(f"❌ Error: {e}")
        
        # Test 2: Get email content
        if hasattr(self, 'test_email_id'):
            print(f"\n📖 Reading email content...")
            try:
                result = await self.session.call_tool(
                    "get_email_content",
                    arguments={"message_id": self.test_email_id}
                )
                
                for content in result.content:
                    if hasattr(content, 'text'):
                        email_data = json.loads(content.text)
                        print(f"\n  Subject: {email_data.get('subject', 'No subject')}")
                        print(f"  From: {email_data.get('from', 'Unknown')}")
                        print(f"  To: {email_data.get('to', 'Unknown')}")
                        body = email_data.get('body', '')
                        print(f"  Body preview: {body[:200]}...")
            except Exception as e:
                print(f"❌ Error: {e}")
        
        # Test 3: Search emails
        print("\n🔍 Searching for unread emails...")
        try:
            result = await self.session.call_tool(
                "search_emails",
                arguments={"query": "is:unread", "max_results": 3}
            )
            
            for content in result.content:
                if hasattr(content, 'text'):
                    search_data = json.loads(content.text)
                    if "emails" in search_data:
                        print(f"Found {search_data['count']} unread emails")
                    else:
                        print(search_data.get('message', 'No results'))
        except Exception as e:
            print(f"❌ Error: {e}")
    
    async def test_resources(self):
        """Test: Access resources"""
        self.print_section("TEST 4: Resources")
        
        # Test calendar settings resource
        print("⚙️  Accessing calendar settings...")
        try:
            result = await self.session.read_resource(
                uri="google://calendar/settings"
            )
            
            for content in result.contents:
                if hasattr(content, 'text'):
                    settings = json.loads(content.text)
                    print(f"\n  Calendar ID: {settings.get('id')}")
                    print(f"  Summary: {settings.get('summary')}")
                    print(f"  Time Zone: {settings.get('timeZone')}")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        # Test Gmail profile resource
        print("\n👤 Accessing Gmail profile...")
        try:
            result = await self.session.read_resource(
                uri="google://gmail/profile"
            )
            
            for content in result.contents:
                if hasattr(content, 'text'):
                    profile = json.loads(content.text)
                    print(f"\n  Email: {profile.get('email')}")
                    print(f"  Total Messages: {profile.get('messages_total')}")
                    print(f"  Total Threads: {profile.get('threads_total')}")
        except Exception as e:
            print(f"❌ Error: {e}")
    
    async def test_prompts(self):
        """Test: Get prompts"""
        self.print_section("TEST 5: Prompts")
        
        print("📝 Available prompts:")
        for i, prompt in enumerate(self.available_prompts, 1):
            print(f"\n{i}. {prompt.name}")
            print(f"   Description: {prompt.description}")
            
            # Get the prompt content
            try:
                if prompt.name == "schedule_meeting_prompt":
                    result = await self.session.get_prompt(
                        prompt.name,
                        arguments={
                            "attendees": "test@example.com",
                            "duration_minutes": "30"  # Changed to string
                        }
                    )
                elif prompt.name == "email_summary_prompt":
                    result = await self.session.get_prompt(
                        prompt.name,
                        arguments={"max_emails": "5"}  # Changed to string
                    )
                elif prompt.name == "calendar_report_prompt":
                    result = await self.session.get_prompt(
                        prompt.name,
                        arguments={"days": "7"}  # Changed to string
                    )
                else:
                    result = await self.session.get_prompt(prompt.name)
                
                if result.messages:
                    print(f"\n   Prompt content preview:")
                    for message in result.messages:
                        if hasattr(message.content, 'text'):
                            preview = message.content.text[:200]
                            print(f"   {preview}...")
            except Exception as e:
                print(f"   ❌ Error getting prompt: {e}")
    
    async def cleanup(self):
        """Clean up test data"""
        self.print_section("CLEANUP")
        
        # Delete test calendar event
        if hasattr(self, 'test_event_id'):
            print("🗑️  Deleting test calendar event...")
            try:
                result = await self.session.call_tool(
                    "delete_calendar_event",
                    arguments={"event_id": self.test_event_id}
                )
                
                for content in result.content:
                    if hasattr(content, 'text'):
                        response = json.loads(content.text)
                        if response.get("success"):
                            print("✓ Test event deleted successfully")
                        else:
                            print(f"❌ Failed to delete event: {response.get('error')}")
            except Exception as e:
                print(f"❌ Error: {e}")
    
    async def run_tests(self):
        """Run all tests"""
        print("\n" + "="*60)
        print("  Starting Test Suite")
        print("="*60 + "\n")
        
        try:
            # Run all tests
            await self.test_list_tools()
            await self.test_calendar_operations()
            await self.test_gmail_operations()
            await self.test_resources()
            await self.test_prompts()
            
            # Cleanup
            await self.cleanup()
            
            # Summary
            self.print_section("TEST SUITE COMPLETE")
            print("✓ All tests completed!")
            print("\nNote: Some tests may fail if you haven't set up")
            print("Google API credentials properly.")
            
        except Exception as e:
            print(f"\n❌ Test suite error: {e}")
            import traceback
            traceback.print_exc()


async def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python test_client.py <path_to_server.py>")
        print("Example: python test_client.py google_suite_server.py")
        sys.exit(1)
    
    server_path = sys.argv[1]
    
    print("="*60)
    print("  Google Suite MCP Test Client")
    print("="*60 + "\n")
    
    client = GoogleMCPClient()
    
    try:
        await client.connect(server_path)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
