# gemini_mcp_agent.py
"""
Minimal Gemini + demo 'MCP tools' agent.

- Uses google-genai generate_content with structured JSON output to ask the model
  which demo tools to call and with what arguments.
- Executes up to TWO tool calls concurrently (ThreadPoolExecutor).
- Mock tools are local functions (no external server).
"""

import os
from dotenv import load_dotenv
import time
import json
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from pydantic import BaseModel, Field
from google import genai

load_dotenv()

# -------------------------
# Mock/demo MCP tools
# -------------------------
def mock_lookup(resource: str, limit: int = 3) -> Dict[str, Any]:
    time.sleep(0.8)
    return {"tool": "lookup", "resource": resource, "limit": limit,
            "results": [f"{resource}_result_{i+1}" for i in range(limit)]}


def mock_compute(x: int, y: int, op: str = "add") -> Dict[str, Any]:
    time.sleep(1.0)
    if op == "add":
        val = x + y
    elif op == "mul":
        val = x * y
    elif op == "sub":
        val = x - y
    else:
        val = None
    return {"tool": "compute", "x": x, "y": y, "op": op, "result": val}


TOOL_REGISTRY = {
    "lookup": mock_lookup,
    "compute": mock_compute
}


# -------------------------
# Pydantic schema for structured response from Gemini
# -------------------------
class ToolCall(BaseModel):
    name: str = Field(..., description="Tool name as in TOOL_REGISTRY")
    args: Dict[str, Any] = Field(default_factory=dict, description="Arguments for the tool")


class PlanSchema(BaseModel):
    tool_calls: List[ToolCall] = Field(..., description="Ordered list of tool calls to perform")


# -------------------------
# Agent
# -------------------------
class GeminiMCPAgent:
    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model = model
        self.client = self._setup_client()

    def _setup_client(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            return genai.Client(api_key=api_key)
        return genai.Client()  # use ADC if no API key

    def plan_tool_calls(self, user_query: str) -> List[Dict[str, Any]]:
        """
        Ask Gemini (generate_content) for a JSON plan. Use contents as a string.
        """
        prompt = (
            "You are an agent that issues calls to demo tools. "
            "Return a JSON object exactly matching this schema:\n\n"
            "{ 'tool_calls': [ { 'name': str, 'args': { ... } }, ... ] }\n\n"
            "Valid tool names: 'lookup' (args: resource:str, limit:int), "
            "'compute' (args: x:int, y:int, op:str where op in [add,mul,sub]).\n\n"
            "Return ONLY the JSON (application/json) with the key 'tool_calls'.\n\n"
            f"User request: {user_query}\n\n"
            "If you want two tools to be executed concurrently, include two tool_calls early in the list."
        )

        try:
            response = self.client.models.generate_content(
                model=self.model,
                # IMPORTANT: pass a plain string for contents (not a list-of-dicts)
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": PlanSchema.model_json_schema()
                }
            )
        except Exception as e:
            print("Error calling Gemini for planning:", e)
            return []

        raw_text = getattr(response, "text", None)
        if raw_text is None:
            # sometimes SDK shapes vary; try other fields
            raw_text = str(response)

        # Try to validate using Pydantic schema (preferred)
        try:
            parsed = PlanSchema.model_validate_json(raw_text)
            return [tc.model_dump() for tc in parsed.tool_calls]
        except Exception as e:
            print("Error validating structured output:", e)
            print("Raw response text (for debugging):")
            print(raw_text)
            # fallback: best-effort json loads
            try:
                parsed_json = json.loads(raw_text)
                return parsed_json.get("tool_calls", [])
            except Exception as ex:
                print("Fallback json.loads also failed:", ex)
                return []

    def execute_tool(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        name = tool_call.get("name")
        args = tool_call.get("args", {}) or {}
        func = TOOL_REGISTRY.get(name)
        if not func:
            return {"ok": False, "error": f"unknown tool '{name}'", "name": name}
        try:
            result = func(**args)
            return {"ok": True, "name": name, "output": result}
        except TypeError as e:
            return {"ok": False, "name": name, "error": f"bad args: {e}"}
        except Exception as e:
            return {"ok": False, "name": name, "error": str(e)}

    def run_plan(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = [None] * len(tool_calls)

        # Run up to 2 concurrently
        with ThreadPoolExecutor(max_workers=2) as ex:
            futures = {}
            for i in range(min(2, len(tool_calls))):
                futures[ex.submit(self.execute_tool, tool_calls[i])] = i

            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    results[idx] = fut.result()
                except Exception as e:
                    results[idx] = {"ok": False, "error": str(e), "index": idx}

            # run remaining sequentially
            for i in range(2, len(tool_calls)):
                results[i] = self.execute_tool(tool_calls[i])

        return results

    def compile_final(self, user_query: str, plan: List[Dict[str, Any]], results: List[Dict[str, Any]]) -> str:
        parts = [f"User request: {user_query}", "", "Planned tool calls:"]
        for i, p in enumerate(plan):
            parts.append(f" {i+1}. {p.get('name')} args={p.get('args')}")
        parts.append("")
        parts.append("Tool results:")
        for i, r in enumerate(results):
            parts.append(f" {i+1}. {r}")
        return "\n".join(parts)
    
    def compile_final_with_gemini(self, user_query: str, plan: List[Dict[str,Any]], results: List[Dict[str,Any]]) -> str:
        # Build a prompt summarizing plan + results, ask Gemini to write a friendly summary.
        plan_text = json.dumps(plan, indent=2)
        results_text = json.dumps(results, indent=2)
        prompt = (
            "You are an assistant. The user requested:\n"
            f"{user_query}\n\n"
            "The agent executed the following plan:\n"
            f"{plan_text}\n\n"
            "Tool outputs:\n"
            f"{results_text}\n\n"
            "Write a short, friendly summary for the user (2-4 short paragraphs)."
        )
        resp = self.client.models.generate_content(model=self.model, contents=prompt)
        return getattr(resp, "text", str(resp))


    def handle(self, user_query: str) -> str:
        plan = self.plan_tool_calls(user_query)
        if not plan:
            return "Agent could not produce a plan."
        results = self.run_plan(plan)
        return self.compile_final_with_gemini(user_query, plan, results)


# -------------------------
# Example run
# -------------------------
def main():
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    agent = GeminiMCPAgent(model=model)

    # Example request: ask for two tool calls so the agent demonstrates concurrency
    user_query = "Lookup 3 resources about 'edge computing' and compute 7 * 8 (use compute). " \
                 "Please call the two tools as part of the plan."
    print("Planning tool calls with Gemini...")
    output = agent.handle(user_query)
    print("\n--- AGENT OUTPUT ---\n")
    print(output)


if __name__ == "__main__":
    main()
