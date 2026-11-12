"""Ask the hosted model, then keep only figures that match the source data."""

import json
import logging
import os
import urllib.error
import urllib.request

from app.chat.facts import answer_from_data
from app.chat.house import house_notes
from app.chat.memory import record_ask, record_gap
from app.chat.snapshot import view_for
from app.chat.visuals import verify_block, allowed_numbers

log = logging.getLogger(__name__)

NOT_CONNECTED = "Answers aren't connected yet."
_DEFAULT_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-4o-mini"


def configured():
    """A key, or the screenshot mock, means the page can answer."""
    return bool(os.environ.get("CHAT_API_KEY", "").strip()) or _mock_on()


def _event(payload):
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def _mock_on():
    return os.environ.get("CHAT_MOCK", "").strip() == "1"


def _model_json(question, grounded):
    """One HTTPS call. The key and the prompt are not logged."""
    key = os.environ.get("CHAT_API_KEY", "").strip()
    if not key:
        return None
    url = os.environ.get("CHAT_API_URL", _DEFAULT_URL).strip() or _DEFAULT_URL
    model = os.environ.get("CHAT_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Reply with JSON only: {\"text\": \"...\", \"table\": null, \"chart\": null}. "
                    "text is one or two short sentences and starts with the number. "
                    "Use only numbers from the context. If a figure is missing, say that in one line. "
                    "table is {\"title\",\"columns\",\"rows\"} or null. "
                    "chart is {\"type\":\"bar\",\"title\",\"unit\",\"series\":[{\"label\",\"value\"}]} or null. "
                    "Add a table or chart only when it compares several figures. Do not invent."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Question: " + question
                    + "\nHouse notes:\n" + house_notes()
                    + "\nContext:\n" + grounded["text"]
                ),
            },
        ],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
        log.info("chat complete status=200")
    except urllib.error.HTTPError as exc:
        log.info("chat complete status=%s", exc.code)
        return None
    except Exception:
        log.info("chat complete status=error")
        return None
    try:
        payload = json.loads(raw)
        content = payload["choices"][0]["message"]["content"]
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            return None
        return json.loads(content[start:end + 1])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _checked(model, grounded):
    allowed = allowed_numbers(grounded.get("source") or {"text": grounded["text"]})
    text = str((model or {}).get("text") or "").strip() or grounded["text"]
    table = verify_block((model or {}).get("table"), allowed) or grounded.get("table")
    chart = verify_block((model or {}).get("chart"), allowed) or grounded.get("chart")
    # A model sentence that introduces a new number is discarded.
    extra = allowed_numbers({"text": text})
    if any(not any(abs(number - item) <= 0.51 for item in allowed) for number in extra):
        text = grounded["text"]
    return text, table, chart


def iter_answer(question, email):
    """SSE events. Text first, then the checked table or chart and follow-ups."""
    from app.chat.limit import allow

    if not allow(email or "anonymous"):
        yield _event({"text": "Too many questions just now. Wait a few minutes and try again.", "done": True})
        return
    data = view_for(email)
    grounded = answer_from_data(question, data, _owner(email))
    role = data.get("role") or "ops"
    ask_id = record_ask(question, grounded.get("topic") or "", grounded.get("as_of") or "", role, "person", "")
    record_gap(question, grounded.get("topic") or "", grounded.get("text") or "", grounded.get("as_of") or "", role, "person", "")
    mock = _mock_on()
    if not configured() and not mock:
        yield _event({"text": NOT_CONNECTED, "done": True, "followups": []})
        return
    text, table, chart = grounded["text"], grounded.get("table"), grounded.get("chart")
    if configured() and not mock:
        model = _model_json(question, grounded)
        text, table, chart = _checked(model, grounded)
    if mock:
        text = "Mock answer. " + text
    chunk = ""
    for word in text.split(" "):
        chunk = (chunk + " " + word).strip()
        if len(chunk) >= 48:
            yield _event({"text": chunk + " "})
            chunk = ""
    if chunk:
        yield _event({"text": chunk})
    yield _event({
        "done": True,
        "as_of": grounded.get("as_of") or "",
        "table": table,
        "chart": chart,
        "followups": grounded.get("followups") or [],
        "topic": grounded.get("topic") or "",
        "ask_id": ask_id,
        "mock": mock,
    })


def _owner(email):
    from app.access import is_owner
    return is_owner(email)
