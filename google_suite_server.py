"""
Google Suite MCP Server
Provides tools for Google Calendar and Gmail integration
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Optional
import os

from mcp.server.fastmcp import FastMCP
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle

# Google API scopes
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/gmail.modify'
]

# Initialize FastMCP server
mcp = FastMCP("google-suite")

# Global service objects
calendar_service = None
gmail_service = None

def get_credentials():
    """Get or refresh Google OAuth credentials"""
    creds = None
    
    # Token file stores user's access and refresh tokens
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    # If no valid credentials, let user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Redirect OAuth messages to stderr
            import sys
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            # Run on specific port to avoid conflicts
            creds = flow.run_local_server(port=8080)
        
        # Save credentials for next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    
    return creds

def initialize_services():
    """Initialize Google API services"""
    global calendar_service, gmail_service
    
    creds = get_credentials()
    calendar_service = build('calendar', 'v3', credentials=creds)
    gmail_service = build('gmail', 'v1', credentials=creds)

# ====================
# CALENDAR TOOLS
# ====================

@mcp.tool()
def list_calendar_events(
    max_results: int = 10,
    days_ahead: int = 7
) -> str:
    """
    List upcoming calendar events
    
    Args:
        max_results: Maximum number of events to return (default: 10)
        days_ahead: Number of days to look ahead (default: 7)
    
    Returns:
        JSON string with list of events
    """
    try:
        if not calendar_service:
            initialize_services()
        
        # Get current time and future time
        now = datetime.utcnow().isoformat() + 'Z'
        time_max = (datetime.utcnow() + timedelta(days=days_ahead)).isoformat() + 'Z'
        
        # Call the Calendar API
        events_result = calendar_service.events().list(
            calendarId='primary',
            timeMin=now,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        if not events:
            return json.dumps({"message": "No upcoming events found"})
        
        event_list = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            event_list.append({
                'id': event['id'],
                'summary': event.get('summary', 'No title'),
                'start': start,
                'end': event['end'].get('dateTime', event['end'].get('date')),
                'location': event.get('location', ''),
                'description': event.get('description', '')
            })
        
        return json.dumps({"events": event_list, "count": len(event_list)}, indent=2)
    
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def create_calendar_event(
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    location: str = "",
    attendees: str = ""
) -> str:
    """
    Create a new calendar event
    
    Args:
        summary: Event title/summary
        start_time: Start time in ISO format (e.g., "2024-12-25T10:00:00-08:00")
        end_time: End time in ISO format
        description: Event description (optional)
        location: Event location (optional)
        attendees: Comma-separated email addresses (optional)
    
    Returns:
        JSON string with created event details
    """
    try:
        if not calendar_service:
            initialize_services()
        
        event = {
            'summary': summary,
            'location': location,
            'description': description,
            'start': {
                'dateTime': start_time,
                'timeZone': 'America/Los_Angeles',
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'America/Los_Angeles',
            }
        }
        
        # Add attendees if provided
        if attendees:
            attendee_list = [{'email': email.strip()} for email in attendees.split(',')]
            event['attendees'] = attendee_list
        
        created_event = calendar_service.events().insert(
            calendarId='primary',
            body=event
        ).execute()
        
        return json.dumps({
            "success": True,
            "event_id": created_event['id'],
            "html_link": created_event.get('htmlLink', ''),
            "summary": created_event.get('summary', '')
        }, indent=2)
    
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def delete_calendar_event(event_id: str) -> str:
    """
    Delete a calendar event
    
    Args:
        event_id: The ID of the event to delete
    
    Returns:
        JSON string with deletion status
    """
    try:
        if not calendar_service:
            initialize_services()
        
        calendar_service.events().delete(
            calendarId='primary',
            eventId=event_id
        ).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Event {event_id} deleted successfully"
        })
    
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def update_calendar_event(
    event_id: str,
    summary: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None
) -> str:
    """
    Update an existing calendar event
    
    Args:
        event_id: The ID of the event to update
        summary: New event title (optional)
        start_time: New start time in ISO format (optional)
        end_time: New end time in ISO format (optional)
        description: New description (optional)
        location: New location (optional)
    
    Returns:
        JSON string with updated event details
    """
    try:
        if not calendar_service:
            initialize_services()
        
        # Get existing event
        event = calendar_service.events().get(
            calendarId='primary',
            eventId=event_id
        ).execute()
        
        # Update fields if provided
        if summary:
            event['summary'] = summary
        if start_time:
            event['start']['dateTime'] = start_time
        if end_time:
            event['end']['dateTime'] = end_time
        if description is not None:
            event['description'] = description
        if location is not None:
            event['location'] = location
        
        updated_event = calendar_service.events().update(
            calendarId='primary',
            eventId=event_id,
            body=event
        ).execute()
        
        return json.dumps({
            "success": True,
            "event_id": updated_event['id'],
            "summary": updated_event.get('summary', '')
        }, indent=2)
    
    except Exception as e:
        return json.dumps({"error": str(e)})

# ====================
# GMAIL TOOLS
# ====================

@mcp.tool()
def list_emails(
    max_results: int = 10,
    query: str = "in:inbox"
) -> str:
    """
    List emails from Gmail
    
    Args:
        max_results: Maximum number of emails to return (default: 10)
        query: Gmail search query (default: "in:inbox")
               Examples: "is:unread", "from:example@gmail.com", "subject:meeting"
    
    Returns:
        JSON string with list of emails
    """
    try:
        if not gmail_service:
            initialize_services()
        
        # Call Gmail API
        results = gmail_service.users().messages().list(
            userId='me',
            maxResults=max_results,
            q=query
        ).execute()
        
        messages = results.get('messages', [])
        
        if not messages:
            return json.dumps({"message": "No messages found"})
        
        email_list = []
        for message in messages:
            msg = gmail_service.users().messages().get(
                userId='me',
                id=message['id'],
                format='metadata',
                metadataHeaders=['From', 'Subject', 'Date']
            ).execute()
            
            headers = msg['payload']['headers']
            email_data = {
                'id': msg['id'],
                'thread_id': msg['threadId'],
                'snippet': msg['snippet']
            }
            
            for header in headers:
                if header['name'] == 'From':
                    email_data['from'] = header['value']
                elif header['name'] == 'Subject':
                    email_data['subject'] = header['value']
                elif header['name'] == 'Date':
                    email_data['date'] = header['value']
            
            email_list.append(email_data)
        
        return json.dumps({"emails": email_list, "count": len(email_list)}, indent=2)
    
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def get_email_content(message_id: str) -> str:
    """
    Get full content of a specific email
    
    Args:
        message_id: The ID of the email message
    
    Returns:
        JSON string with full email content
    """
    try:
        if not gmail_service:
            initialize_services()
        
        message = gmail_service.users().messages().get(
            userId='me',
            id=message_id,
            format='full'
        ).execute()
        
        headers = message['payload']['headers']
        email_data = {
            'id': message['id'],
            'thread_id': message['threadId'],
            'snippet': message['snippet']
        }
        
        # Extract headers
        for header in headers:
            name = header['name']
            if name in ['From', 'To', 'Subject', 'Date', 'Cc', 'Bcc']:
                email_data[name.lower()] = header['value']
        
        # Extract body
        parts = message['payload'].get('parts', [])
        body = ""
        
        if parts:
            for part in parts:
                if part['mimeType'] == 'text/plain':
                    if 'data' in part['body']:
                        import base64
                        body = base64.urlsafe_b64decode(
                            part['body']['data']
                        ).decode('utf-8')
                        break
        else:
            if 'data' in message['payload']['body']:
                import base64
                body = base64.urlsafe_b64decode(
                    message['payload']['body']['data']
                ).decode('utf-8')
        
        email_data['body'] = body
        
        return json.dumps(email_data, indent=2)
    
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = ""
) -> str:
    """
    Send an email via Gmail
    
    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body text
        cc: CC email addresses, comma-separated (optional)
        bcc: BCC email addresses, comma-separated (optional)
    
    Returns:
        JSON string with send status
    """
    try:
        if not gmail_service:
            initialize_services()
        
        import base64
        from email.mime.text import MIMEText
        
        message = MIMEText(body)
        message['to'] = to
        message['subject'] = subject
        
        if cc:
            message['cc'] = cc
        if bcc:
            message['bcc'] = bcc
        
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        sent_message = gmail_service.users().messages().send(
            userId='me',
            body={'raw': raw}
        ).execute()
        
        return json.dumps({
            "success": True,
            "message_id": sent_message['id'],
            "thread_id": sent_message['threadId']
        }, indent=2)
    
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def mark_email_read(message_id: str) -> str:
    """
    Mark an email as read
    
    Args:
        message_id: The ID of the email message
    
    Returns:
        JSON string with status
    """
    try:
        if not gmail_service:
            initialize_services()
        
        gmail_service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'removeLabelIds': ['UNREAD']}
        ).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Email {message_id} marked as read"
        })
    
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def search_emails(
    query: str,
    max_results: int = 20
) -> str:
    """
    Search emails with advanced Gmail query syntax
    
    Args:
        query: Gmail search query
               Examples: 
               - "from:example@gmail.com after:2024/01/01"
               - "has:attachment subject:report"
               - "is:important is:unread"
        max_results: Maximum results to return (default: 20)
    
    Returns:
        JSON string with search results
    """
    return list_emails(max_results=max_results, query=query)

# ====================
# RESOURCES
# ====================

@mcp.resource("google://calendar/settings")
def get_calendar_settings() -> str:
    """Get calendar settings and metadata"""
    try:
        if not calendar_service:
            initialize_services()
        
        calendar = calendar_service.calendars().get(calendarId='primary').execute()
        
        return json.dumps({
            "id": calendar.get('id'),
            "summary": calendar.get('summary'),
            "timeZone": calendar.get('timeZone'),
            "description": calendar.get('description', '')
        }, indent=2)
    
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.resource("google://gmail/profile")
def get_gmail_profile() -> str:
    """Get Gmail profile information"""
    try:
        if not gmail_service:
            initialize_services()
        
        profile = gmail_service.users().getProfile(userId='me').execute()
        
        return json.dumps({
            "email": profile.get('emailAddress'),
            "messages_total": profile.get('messagesTotal'),
            "threads_total": profile.get('threadsTotal'),
            "history_id": profile.get('historyId')
        }, indent=2)
    
    except Exception as e:
        return json.dumps({"error": str(e)})

# ====================
# PROMPTS
# ====================

@mcp.prompt()
def schedule_meeting_prompt(
    attendees: str = "",
    duration_minutes: int = 60
) -> str:
    """Generate a prompt for scheduling a meeting"""
    return f"""I need to schedule a meeting. Please help me:

1. Find a free time slot in my calendar for the next 7 days
2. Create a calendar event with:
   - Attendees: {attendees if attendees else "TBD"}
   - Duration: {duration_minutes} minutes
   - Include a meeting link if possible

First, check my calendar for available times, then create the event."""

@mcp.prompt()
def email_summary_prompt(max_emails: int = 10) -> str:
    """Generate a prompt for email summary"""
    return f"""Please provide a summary of my recent emails:

1. List my last {max_emails} unread emails
2. Categorize them by importance/urgency
3. Highlight any that require immediate action
4. Provide a brief summary of each

Use the search query "is:unread" to find unread emails."""

@mcp.prompt()
def calendar_report_prompt(days: int = 7) -> str:
    """Generate a prompt for calendar report"""
    return f"""Generate a calendar report for the next {days} days:

1. List all scheduled events
2. Identify any scheduling conflicts
3. Show daily breakdown of meetings
4. Calculate total meeting hours
5. Suggest any gaps for focused work time"""

def main():
    """Run the MCP server"""
    # Note: No print statements allowed - stdio is used for JSON-RPC only
    # Initialize services silently
    try:
        initialize_services()
    except Exception:
        # Services will be initialized on first tool call
        pass
    
    # Run server with stdio transport
    mcp.run(transport='stdio')

if __name__ == "__main__":
    main()
