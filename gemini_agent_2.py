# gemini_mcp_agent.py
"""
Gemini MCP demo agent with many mock tools.
- Uses models.generate_content with structured output (PlanSchema).
- Executes up to two tool calls concurrently.
- Add/modify tools in TOOL_REGISTRY; update prompts to instruct Gemini which tools to call.
"""

import os
from dotenv import load_dotenv
import time
import json
import random
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean, median
from datetime import datetime
from pydantic import BaseModel, Field
from google import genai

load_dotenv()


# -------------------------
# Demo tools (purely local)
# -------------------------
def mock_lookup(resource: str, limit: int = 3) -> Dict[str, Any]:
    """Return dummy search-like results for the given resource."""
    time.sleep(0.6)
    return {
        "tool": "lookup",
        "resource": resource,
        "limit": limit,
        "results": [f"{resource}_result_{i+1}" for i in range(limit)]
    }


def mock_compute(x: float, y: float, op: str = "add") -> Dict[str, Any]:
    """Simple arithmetic operations with basic error handling."""
    time.sleep(0.3)
    try:
        if op == "add":
            val = x + y
        elif op == "mul":
            val = x * y
        elif op == "sub":
            val = x - y
        elif op == "div":
            val = x / y
        else:
            return {"tool": "compute", "error": f"unsupported op '{op}'"}
        return {"tool": "compute", "x": x, "y": y, "op": op, "result": val}
    except Exception as e:
        return {"tool": "compute", "error": str(e)}


def mock_summarize(text: str, max_sentences: int = 3) -> Dict[str, Any]:
    """Mock summary: returns the first N sentences (naive)."""
    time.sleep(0.2)
    sentences = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
    summary = ". ".join(sentences[:max_sentences])
    if summary and not summary.endswith("."):
        summary += "."
    return {"tool": "summarize", "summary": summary}


def mock_stats(numbers: List[float]) -> Dict[str, Any]:
    """Return basic statistics for a list of numbers."""
    time.sleep(0.2)
    if not numbers:
        return {"tool": "stats", "error": "no numbers provided"}
    try:
        return {
            "tool": "stats",
            "count": len(numbers),
            "mean": mean(numbers),
            "median": median(numbers),
            "min": min(numbers),
            "max": max(numbers)
        }
    except Exception as e:
        return {"tool": "stats", "error": str(e)}


def mock_now() -> Dict[str, Any]:
    """Return current local date/time info (ISO and components)."""
    now = datetime.now()
    return {
        "tool": "now",
        "iso": now.isoformat(),
        "date": now.date().isoformat(),
        "time": now.time().isoformat(timespec="seconds")
    }


def mock_translate(text: str, target_lang: str = "en") -> Dict[str, Any]:
    """Mock translate — just indicate the target language and return the original text prefixed."""
    time.sleep(0.1)
    return {"tool": "translate", "target_lang": target_lang, "translated": f"[{target_lang}] {text}"}


def mock_fetch_meta(url: str) -> Dict[str, Any]:
    """Mock fetch metadata for a URL (no network)."""
    time.sleep(0.4)
    fake_title = f"Title for {url}"
    fake_desc = f"Description snippet for {url}"
    return {"tool": "fetch_meta", "url": url, "title": fake_title, "description": fake_desc}


def mock_echo(msg: str) -> Dict[str, Any]:
    time.sleep(0.05)
    return {"tool": "echo", "msg": msg}


def mock_report(title: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a simple structured report object."""
    time.sleep(0.4)
    return {"tool": "report", "title": title, "item_count": len(items), "items": items[:10]}


def mock_random_choice(choices: List[Any]) -> Dict[str, Any]:
    time.sleep(0.05)
    if not choices:
        return {"tool": "random_choice", "error": "no choices"}
    return {"tool": "random_choice", "choice": random.choice(choices)}


# Registry: name -> callable
TOOL_REGISTRY = {
    "lookup": mock_lookup,
    "compute": mock_compute,
    "summarize": mock_summarize,
    "stats": mock_stats,
    "now": mock_now,
    "translate": mock_translate,
    "fetch_meta": mock_fetch_meta,
    "echo": mock_echo,
    "report": mock_report,
    "random_choice": mock_random_choice
}


# -------------------------
# Pydantic schema for structured plan
# -------------------------
class ToolCall(BaseModel):
    name: str = Field(..., description="Tool name from the registry")
    args: Dict[str, Any] = Field(default_factory=dict, description="Arguments for the tool")


class PlanSchema(BaseModel):
    tool_calls: List[ToolCall] = Field(..., description="Ordered list of tool calls")


# -------------------------
# Agent implementation
# -------------------------
class GeminiMCPAgent:
    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model = model
        self.client = self._setup_client()

    def _setup_client(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            return genai.Client(api_key=api_key)
        return genai.Client()  # tries ADC

    def plan_tool_calls(self, user_query: str) -> List[Dict[str, Any]]:
        """
        Ask Gemini for a JSON plan using PlanSchema. contents must be a string.
        The model should only return JSON with {"tool_calls": [...]}.
        """
        prompt = (
            "You are an agent planner that returns a JSON plan with the exact key 'tool_calls'.\n"
            "Each entry must be {\"name\": TOOL_NAME, \"args\": {...}}.\n"
            "Available tools and their args:\n"
            " - lookup(resource:str, limit:int=3)\n"
            " - compute(x:number, y:number, op:str in [add,mul,sub,div])\n"
            " - summarize(text:str, max_sentences:int=3)\n"
            " - stats(numbers:list[number])\n"
            " - now()\n"
            " - translate(text:str, target_lang:str)\n"
            " - fetch_meta(url:str)\n"
            " - echo(msg:str)\n"
            " - report(title:str, items:list[object])\n"
            " - random_choice(choices:list)\n\n"
            "Return ONLY JSON (application/json). Make arguments sensible for the user request.\n\n"
            f"User request: {user_query}\n\n"
            "If the user asks multiple independent tasks that can be done in parallel, include those first\n"
            "so the agent can execute them concurrently (we will run up to two in parallel)."
        )

        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=prompt,   # IMPORTANT: string
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": PlanSchema.model_json_schema()
                }
            )
        except Exception as e:
            print("Error calling Gemini for planning:", e)
            return []

        raw_text = getattr(resp, "text", None)
        if raw_text is None:
            raw_text = str(resp)

        # Prefer structured validation
        try:
            parsed = PlanSchema.model_validate_json(raw_text)
            return [tc.model_dump() for tc in parsed.tool_calls]
        except Exception as e:
            print("Warning: structured validation failed:", e)
            print("Raw response (for debugging):")
            print(raw_text[:4000])
            # best-effort fallback
            try:
                j = json.loads(raw_text)
                return j.get("tool_calls", [])
            except Exception:
                return []

    def execute_tool(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        name = tool_call.get("name")
        args = tool_call.get("args", {}) or {}
        func = TOOL_REGISTRY.get(name)
        if not func:
            return {"ok": False, "name": name, "error": f"unknown tool '{name}'"}
        try:
            # call the tool with kwargs; if tool expects different signature, it'll raise TypeError
            result = func(**args)
            return {"ok": True, "name": name, "output": result}
        except TypeError as e:
            return {"ok": False, "name": name, "error": f"bad args: {e}"}
        except Exception as e:
            return {"ok": False, "name": name, "error": str(e)}

    def run_plan(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = [None] * len(tool_calls)
        with ThreadPoolExecutor(max_workers=2) as ex:
            futures = {}
            # submit first two concurrently
            for idx in range(min(2, len(tool_calls))):
                futures[ex.submit(self.execute_tool, tool_calls[idx])] = idx
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    results[idx] = fut.result()
                except Exception as e:
                    results[idx] = {"ok": False, "error": str(e)}
            # rest sequentially
            for idx in range(2, len(tool_calls)):
                results[idx] = self.execute_tool(tool_calls[idx])
        return results

    def compile_final(self, user_query: str, plan: List[Dict[str, Any]], results: List[Dict[str, Any]]) -> str:
        parts = [f"User request: {user_query}", "", "Planned tool calls:"]
        for i, p in enumerate(plan):
            parts.append(f" {i+1}. {p.get('name')} args={p.get('args')}")
        parts.append("")
        parts.append("Tool results:")
        for i, r in enumerate(results):
            parts.append(f" {i+1}. {json.dumps(r, default=str)}")
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
# Example prompt variants (modify these to test different tools)
# -------------------------
EXAMPLES = [
    # ask for two tasks that can be run concurrently: lookup + compute
    "Lookup 5 resources about 'edge computing security' and compute 12 * 9. Run both as part of the plan.",

    # ask to summarize + stats
    "Summarize this text: 'Python is a widely used language. It is friendly for beginners. It is used in AI.' "
    "Also compute statistics for the numbers [1,2,3,10,50].",

    # fetch meta + report
    "Fetch meta information for 'https://example.com' and produce a short report titled 'Example scan' "
    "with the meta result included as items."
]


# -------------------------
# Run example
# -------------------------
def main():
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    agent = GeminiMCPAgent(model=model)

    # Choose one of the EXAMPLES or set your own query
    user_query = EXAMPLES[1]
    print("Planning tool calls with Gemini...")
    out = agent.handle(user_query)
    print("\n--- AGENT OUTPUT ---\n")
    print(out)


if __name__ == "__main__":
    main()
