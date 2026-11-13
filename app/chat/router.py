"""Tool calls for the hosted model.

The test client still receives one packet and does not see tools. A live key
can call a domain by name. The role gate is applied again inside dispatch.
"""

import json

from app.chat.wizard_a import (
    _asks_finance,
    _asks_fixes,
    _asks_forecast,
    _asks_growth,
    _asks_procurement,
    _asks_trends,
    domain_text,
    finance_text,
    forecast_answer,
    growth_text,
    posist_fixes_text,
    trends_text,
    _procurement_text,
)

_TOOLS = (
    ("finance", "Grand Economics lines for a city, store, or month. Owner and finance only.", {"owner", "finance"}),
    ("procurement", "Recipe cost, vendors, wastage, and PO versus GRN.", {"owner", "finance", "hr", "ops"}),
    ("posist_fixes", "What can be fixed on Posist, from the issues list.", {"owner", "finance", "hr", "ops"}),
    ("growth", "Where a sales gap is large enough to act on, with the assumption stated.", {"owner", "finance", "hr", "ops"}),
    ("trends", "Largest week-versus-week sales moves.", {"owner", "finance", "hr", "ops"}),
    ("forecast", "Predicted sales calendar and forecast accuracy.", {"owner", "finance", "hr", "ops"}),
)


def tool_specs(role):
    specs = []
    for name, description, roles in _TOOLS:
        if role not in roles:
            continue
        specs.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {"question": {"type": "string"}},
                    "required": ["question"],
                },
            },
        })
    return specs


def dispatch(name, arguments, role):
    question = ""
    if isinstance(arguments, dict):
        question = str(arguments.get("question") or "")
    allowed = {row[0]: row[2] for row in _TOOLS}
    if name not in allowed or role not in allowed[name]:
        return {"error": "This role cannot see that domain."}
    if name == "finance":
        return {"text": finance_text(question, role)}
    if name == "procurement":
        return {"text": _procurement_text(question)}
    if name == "posist_fixes":
        return {"text": posist_fixes_text()}
    if name == "growth":
        return {"text": growth_text()}
    if name == "trends":
        return {"text": trends_text()}
    if name == "forecast":
        answer = forecast_answer(question, role in {"owner", "finance"})
        return {"text": answer.get("text") or "", "calendar": answer.get("calendar")}
    return {"error": "Unknown tool."}


def select_names(question, role):
    """Domains a question should pull. Used when the model asks for tools and in the packet."""
    names = []
    if _asks_finance(question):
        names.append("finance")
    if _asks_procurement(question):
        names.append("procurement")
    if _asks_fixes(question):
        names.append("posist_fixes")
    if _asks_growth(question):
        names.append("growth")
    if _asks_trends(question):
        names.append("trends")
    if _asks_forecast(question):
        names.append("forecast")
    return [name for name in names if role in {row[0]: row[2] for row in _TOOLS}[name]]


def packet_for(question, role):
    return domain_text(question, role)


def run_tool_loop(messages, role, complete_message, model):
    """Up to three rounds. Returns (text, error)."""
    specs = tool_specs(role)
    if not specs:
        return None, "no_tools"
    working = list(messages)
    for _round in range(3):
        message, error = complete_message(working, model, specs)
        if error:
            return None, error
        calls = message.get("tool_calls") or []
        if not calls:
            return (message.get("content") or "").strip(), None
        working.append({
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": calls,
        })
        for call in calls[:4]:
            function = call.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            payload = dispatch(function.get("name") or "", arguments, role)
            text = json.dumps(payload, ensure_ascii=False)
            if len(text) > 8000:
                text = text[:8000] + "...[truncated]"
            working.append({
                "role": "tool",
                "tool_call_id": call.get("id") or "",
                "content": text,
            })
    return None, "tool_limit"
