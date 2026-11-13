"""Ask the hosted model, then keep only figures that match the source data."""

import json
import logging
import os
import urllib.error
import urllib.request

from app.chat.context import build_context
from app.chat.facts import answer_from_data
from app.chat.memory import record_ask, record_gap
from app.chat.snapshot import view_for
from app.chat.visuals import verify_block, allowed_numbers

log = logging.getLogger(__name__)

NOT_CONNECTED = "Answers aren't connected yet."
AI_UNAVAILABLE = "AI unavailable."
_DEFAULT_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-4.1"
_SYSTEM = (
    "You are Dosa Coffee's sharp analyst for the Command Centre. "
    "Use only the data packet and the house notes. Never invent a number, a store, or a date. "
    "If the packet does not cover the question, say that in one plain sentence and then answer the closest question the packet does cover. "
    "Write scannable markdown, under about 150 words unless the user asks for detail. "
    "Start with one bold sentence that is the direct answer. "
    "Then at most 3 to 5 short bullets with the key numbers. "
    "Add a compact markdown table only when comparing 3 or more items: at most 6 rows and 4 columns, short headers, units in the header, rupees as ₹1.61 Cr or ₹9.85 L. "
    "Do not repeat a number in both the bullets and the table. "
    "Do not leave an empty heading. Do not write filler such as 'performing moderately well'. "
    "Then a 'Next steps' heading with at most 3 numbered actions, one line each, each tied to a figure in the packet. "
    "End with one small line, 'Data: ...', stating the dates once, for example 'Data: sales to 8 Nov, pace to 11 Nov'. "
    "When a trend helps, add one fenced block exactly like ```chart {\"type\":\"bar\",\"title\":\"\",\"unit\":\"\",\"series\":[{\"label\":\"\",\"value\":0}]} ``` "
    "and use only values that appear in the packet. "
    "Follow the house notes on closed stores, mall bulk bills, Navratri, and city costs."
)


def configured():
    """A key, or the screenshot mock, means the page can answer."""
    return bool(os.environ.get("CHAT_API_KEY", "").strip()) or _mock_on()


def _event(payload):
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def _mock_on():
    return os.environ.get("CHAT_MOCK", "").strip() == "1"


def model_name():
    return os.environ.get("CHAT_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def messages_for(question, context):
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": "Question: " + (question or "").strip() + "\n\n" + context},
    ]


def _log_ask(model, fallback):
    """One line. The key and the prompt are never written."""
    log.info("chat ask model_used=%s fallback=%s", model or "none", fallback or "none")


def _pull_chart(text, context):
    """Lift one chart spec out of the reply. Drop it if a number is not in the packet."""
    if not text or "```chart" not in text:
        return text, None
    start = text.find("```chart")
    after = text.find("\n", start)
    end = text.find("```", after if after > start else start + 8)
    if after < 0 or end < 0:
        return text, None
    raw = text[after + 1:end].strip()
    kept = text[:start].rstrip() + text[end + 3:]
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError:
        return kept.strip(), None
    allowed = allowed_numbers(context)
    chart = verify_block(spec, allowed)
    return kept.strip(), chart


def complete_message(messages, model=None, tools=None):
    """Call the hosted model. Returns (message dict, error)."""
    key = os.environ.get("CHAT_API_KEY", "").strip()
    if not key:
        return None, "no_key"
    url = os.environ.get("CHAT_API_URL", _DEFAULT_URL).strip() or _DEFAULT_URL
    chosen = model or model_name()
    body = {
        "model": chosen,
        "temperature": 0,
        "max_tokens": 2000,
        "messages": messages,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return None, "http_" + str(exc.code)
    except Exception:
        return None, "request_error"
    try:
        payload = json.loads(raw)
        message = payload["choices"][0]["message"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None, "bad_response"
    if not isinstance(message, dict):
        return None, "bad_response"
    return message, None


def complete_chat(messages, model=None):
    """Call the hosted model. Returns (text, error). Error is None on success."""
    message, error = complete_message(messages, model)
    if error:
        return None, error
    text = str((message or {}).get("content") or "").strip()
    if not text:
        return None, "empty_response"
    return text, None


def produce_answer(question, data, owner, client=None, when_offline="notice"):
    """Ask the model with the data packet. Fall back only when that call fails."""
    context = build_context(question, data)
    local = answer_from_data(question, data, owner)
    messages = messages_for(question, context)
    result = {
        "text": local.get("text") or "",
        "as_of": local.get("as_of") or "",
        "table": local.get("table"),
        "chart": local.get("chart"),
        "followups": local.get("followups") or [],
        "topic": local.get("topic") or "",
        "actions": local.get("actions") or [],
        "calendar": local.get("calendar"),
        "context": context,
        "messages": messages,
        "model": None,
        "fallback": None,
    }
    if _mock_on():
        result["text"] = "Mock answer. " + result["text"]
        result["fallback"] = "mock"
        _log_ask(None, "mock")
        return result
    if not os.environ.get("CHAT_API_KEY", "").strip() and client is None:
        result["fallback"] = "no_key"
        _log_ask(None, "no_key")
        if when_offline == "notice" and os.environ.get("CHAT_SHOW_LOCAL", "").strip() != "1":
            result["text"] = NOT_CONNECTED
            result["table"] = None
            result["chart"] = None
            result["calendar"] = None
        return result
    chosen = model_name()
    if client is not None:
        text, error = client(messages, chosen)
    else:
        from app.chat.router import run_tool_loop

        text, error = run_tool_loop(
            messages,
            data.get("role") or "ops",
            complete_message,
            chosen,
        )
        if error:
            text, error = complete_chat(messages, chosen)
    if error or not text:
        result["text"] = AI_UNAVAILABLE + " " + (local.get("text") or "")
        result["fallback"] = error or "empty_response"
        _log_ask(None, result["fallback"])
        return result
    prose, chart = _pull_chart(text, context)
    result["text"] = prose
    result["chart"] = chart
    result["table"] = None
    result["model"] = chosen
    result["fallback"] = None
    _log_ask(chosen, None)
    return result


def stream_pieces(text):
    """Split a reply for streaming without eating newlines or markdown."""
    if not text:
        return
    size = 80
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind(" ", start + 20, end)
            if cut > start:
                end = cut + 1
        yield text[start:end]
        start = end


def iter_answer(question, email, client=None):
    """SSE events. The model writes the answer when a key is set."""
    from app.chat.limit import allow

    if not allow(email or "anonymous"):
        _log_ask(None, "rate_limit")
        yield _event({"text": "Too many questions just now. Wait a few minutes and try again.", "done": True})
        return
    data = view_for(email)
    owner = _owner(email)
    produced = produce_answer(question, data, owner, client=client)
    role = data.get("role") or "ops"
    ask_id = record_ask(question, produced.get("topic") or "", produced.get("as_of") or "", role, "person", "")
    record_gap(question, produced.get("topic") or "", produced.get("text") or "", produced.get("as_of") or "", role, "person", "")
    text = produced.get("text") or ""
    for piece in stream_pieces(text):
        yield _event({"text": piece})
    yield _event({
        "done": True,
        "markdown": text,
        "as_of": produced.get("as_of") or "",
        "table": produced.get("table"),
        "chart": produced.get("chart"),
        "calendar": produced.get("calendar"),
        "followups": produced.get("followups") or [],
        "cos": {"connected": _cos_connected()} if role == "owner" else None,
        "topic": produced.get("topic") or "",
        "ask_id": ask_id,
        "mock": _mock_on(),
        "fallback": produced.get("fallback"),
    })


def _cos_connected():
    import os
    return bool(os.environ.get("WIZARD_WEBHOOK_URL", "").strip() and os.environ.get("WIZARD_WEBHOOK_KEY", "").strip())


def _owner(email):
    from app.access import is_owner
    return is_owner(email)
