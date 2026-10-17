#!/usr/bin/env python3
# After-call report and chat about the call.
# Online: Gemma 4 via the Gemini API (better Hindi, deeper reasoning).
# Offline or on any error: the local Ollama model answers instead, so it always works.
#   python gemma.py "transcript text"

import json
import os
import sys
import time
import urllib.error
import urllib.request

import llm

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_env():
    # tiny .env reader so we don't need python-dotenv
    path = os.path.join(HERE, ".env")
    if os.path.exists(path):
        for line in open(path):
            k, sep, v = line.strip().partition("=")
            if sep and not k.startswith("#"):
                os.environ.setdefault(k, v)


_load_env()
GEMMA_MODEL = os.environ.get("GEMMA_MODEL", "gemma-4-26b-a4b-it")
API = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMMA_MODEL}:generateContent"

PROMPT = """You are helping an Indian family member who just received a suspicious phone call.
Below is the call transcript (speech-to-text, may have errors) and the scam signals detected.
Write a short report in simple Hindi (Devanagari), at most 120 words, with these 3 headings:
1. क्या हुआ: what the caller tried to do, quoting their words
2. धोखे की चाल: which scam tactic this is and why it is fake (e.g. police never do "digital arrest")
3. अब क्या करें: concrete steps: don't pay or share OTP, call 1930 (cyber crime helpline),
   report at cybercrime.gov.in, call the bank if money or details were shared.
Plain text only, no markdown symbols."""

CHAT_PROMPT = """You are Kavach, a calm assistant helping an Indian family member understand a phone call
they just had. Use the transcript and detected scam signals below. Answer the user's question in the
same language they ask in (Hindi, English or Hinglish), in at most 80 words, plainly and kindly.
If money or an OTP may have been shared, always mention calling 1930 and the bank right away.
Never tell them a real police officer, bank or court would ask for money or OTP on a call.
Plain text only, no markdown symbols."""


def _ask_gemma(text, timeout=40):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    body = json.dumps({
        "contents": [{"parts": [{"text": text}]}],
        # Gemma 4 thinks ~1200 tokens by default (~30 s). Minimal thinking answers in ~5 s,
        # which matters on stage, and the report is just as clear.
        "generationConfig": {"thinkingConfig": {"thinkingLevel": "minimal"}},
    }).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json",
                                                          "x-goog-api-key": key})
    for attempt in range(2):  # one retry: the API sometimes answers 503 "high demand"
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                parts = json.loads(r.read())["candidates"][0]["content"]["parts"]
            # Gemma 4 may return its thinking as separate parts marked "thought"; keep only the answer.
            return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip() or None
        except urllib.error.HTTPError as e:
            if e.code != 503 or attempt:
                return None
            time.sleep(1)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError):
            return None


def _ask_local(text):
    body = json.dumps({"model": llm.LLM, "stream": False, "keep_alive": "30m", "options": {"num_ctx": 2048},
                       "messages": [{"role": "user", "content": text}]}).encode()
    try:
        req = urllib.request.Request(llm.OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["message"]["content"].strip()
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        return None


def _ask(text):
    """Gemma 4 first, local model if that fails. Return (who_answered, answer, seconds)."""
    t0 = time.time()
    out = _ask_gemma(text)
    if out:
        return "Gemma 4", out, round(time.time() - t0, 1)
    out = _ask_local(text)
    return f"local {llm.LLM} (offline)", out or "Sorry, no answer right now.", round(time.time() - t0, 1)


def _signals(hits):
    return ", ".join(f"{p} (“{w}”)" for p, w in (hits or {}).items()) or "none"


def report(transcript, hits=None):
    """After-call report. Return (who_wrote_it, report_text, seconds)."""
    return _ask(f"{PROMPT}\n\nSignals: {_signals(hits)}\n\nTranscript:\n{transcript}")


def chat(question, transcript, hits=None, history=()):
    """Answer a question about the call. history: earlier (question, answer) pairs."""
    past = "".join(f"\nUser: {q}\nKavach: {a}" for q, a in history[-4:])
    return _ask(f"{CHAT_PROMPT}\n\nSignals: {_signals(hits)}\n\nTranscript:\n{transcript or '(nothing heard yet)'}"
                f"\n\nConversation so far:{past or ' none'}\n\nUser: {question}\nKavach:")


if __name__ == "__main__":
    who, text, secs = report(" ".join(sys.argv[1:]))
    print(f"[{who}, {secs}s]\n{text}")
