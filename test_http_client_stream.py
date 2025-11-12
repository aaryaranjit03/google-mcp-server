import json
import threading
import time
import uuid
import requests

BASE = "http://127.0.0.1:8000"
MOUNT = "/mcp"

def get_session_id():
    """
    Easiest reliable way with this server:
    - POST any JSON to /mcp with Accept including text/event-stream
    - read 'mcp-session-id' from the response header
    """
    url = f"{BASE}{MOUNT}"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    # send a harmless JSON-RPC that the server may 400 on; we only want the header.
    payload = {"jsonrpc": "2.0", "id": "probe", "method": "ping", "params": {}}
    try:
        r = requests.post(url, headers=headers, data=json.dumps(payload))
    except Exception as e:
        raise RuntimeError(f"Failed to contact server: {e}")
    sid = r.headers.get("mcp-session-id")
    if not sid:
        raise RuntimeError(f"No session id header found; status={r.status_code}, body={r.text!r}")
    return sid

def sse_listener(session_id, stop_event):
    """
    Open the SSE stream for this session and print events as they arrive.
    """
    url = f"{BASE}{MOUNT}"
    headers = {
        "Accept": "text/event-stream",
        "mcp-session-id": session_id
    }
    with requests.get(url, headers=headers, stream=True) as r:
        if r.status_code != 200:
            print(f"[SSE] status={r.status_code} body={r.text}")
            return
        print(f"[SSE] connected. Listening for events for session {session_id} ...")
        buf = ""
        for chunk in r.iter_lines(decode_unicode=True):
            if stop_event.is_set():
                break
            if chunk is None:
                continue
            line = chunk.strip()
            if not line:
                continue
            # Typical SSE lines: "event: message" or "data: {...}"
            if line.startswith("data:"):
                data = line[5:].strip()
                # Pretty print JSON if possible
                try:
                    obj = json.loads(data)
                    print("[SSE data]", json.dumps(obj, indent=2))
                except Exception:
                    print("[SSE data]", data)
            elif line.startswith("event:"):
                print("[SSE event]", line[6:].strip())
            else:
                # Other SSE fields (id:, retry:, etc.)
                print("[SSE]", line)

def call_tool(session_id, name, arguments):
    """
    Send JSON-RPC call_tool to the server, bound to the session id.
    """
    url = f"{BASE}{MOUNT}"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "mcp-session-id": session_id
    }
    req_id = str(uuid.uuid4())
    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "call_tool",
        "params": {
            # some servers require the session in params too; harmless to include
            "session_id": session_id,
            "name": name,
            "arguments": arguments
        }
    }
    r = requests.post(url, headers=headers, data=json.dumps(payload))
    try:
        obj = r.json()
    except Exception:
        obj = {"status": r.status_code, "text": r.text}
    print("[POST call_tool] status", r.status_code)
    print(json.dumps(obj, indent=2))

# def list_tools(session_id):
#     url = f"{BASE}{MOUNT}"
#     headers = {
#         "Content-Type": "application/json",
#         "Accept": "application/json, text/event-stream",
#         "mcp-session-id": session_id
#     }
#     payload = {
#         "jsonrpc": "2.0",
#         "id": "list-1",
#         "method": "list_tools",
#         "params": {}
#     }
#     r = requests.post(url, headers=headers, data=json.dumps(payload))
#     try:
#         print("[list_tools]", json.dumps(r.json(), indent=2))
#     except Exception:
#         print("[list_tools] raw", r.text)

def main():
    print("[1/3] Creating/obtaining session id...")
    sid = get_session_id()
    print(f"[OK] session id: {sid}")

    # list_tools(sid)

    print("[2/3] Opening SSE listener in background...")
    stop = threading.Event()
    t = threading.Thread(target=sse_listener, args=(sid, stop), daemon=True)
    t.start()

    time.sleep(0.4)  # small delay so SSE is up

    print("[3/3] Sending call_tool(list_calendar_events)...")
    # Adjust arguments to your real tool’s signature if different
    call_tool(
        sid,
        "list_calendar_events",
        arguments={"max_results": 5, "days_ahead": 7}
    )

    print("Watching SSE for 8 seconds…")
    time.sleep(8)
    stop.set()
    t.join(timeout=1.0)
    print("Done.")

if __name__ == "__main__":
    main()
