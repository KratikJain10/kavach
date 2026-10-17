#!/usr/bin/env python3
# Local AI judgement: asks the Ollama model whether a transcript sounds like a scam.
#   python llm.py "आप डिजिटल अरेस्ट में हैं, पैसे ट्रांसफर कीजिए"

import json
import os
import sys
import time
import urllib.error
import urllib.request

from rules import PATTERNS

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
LLM = os.environ.get("LLM", "llama3.2:3b")

PROMPT = f"""You check live phone-call transcripts (Hindi, English or Hinglish, may contain speech-to-text
errors) for scams common in India. The language of the call is not a signal; only what is said is.

Asking for money is NOT a scam by itself: friends and family borrow money all the time. A call is a scam
when the caller uses a TRICK, for example:
- pretends to be police, CBI, customs, a court, a bank, TRAI, an electricity board or a courier company
- threatens arrest, "digital arrest", FIR, account block or a power cut
- asks for an OTP, PIN, CVV, or to install AnyDesk/TeamViewer/screen share
- demands secrecy from a stranger ("don't tell anyone") together with urgency and payment
- promises a prize, lottery, refund or job that needs a fee first

Examples:
"bhai 2000 bhej de, kal lauta dunga" -> safe, risk 10 (a friend borrowing money)
"mummy bol rahi hoon, dinner pe aa rahe ho?" -> safe, risk 0
"main police se bol raha hoon, aapka beta pakda gaya, 50000 bhejo warna FIR" -> scam, risk 95
"your SBI KYC is expiring, tell me the OTP" -> scam, risk 95

Reply ONLY with JSON:
{{"verdict": "scam" | "suspicious" | "safe",
  "risk": 0-100 (how likely this call is a scam),
  "pattern": one of {PATTERNS + ["none"]},
  "reason": "one short sentence in English (never Hindi) quoting what the caller said"}}"""


def judge(text, timeout=30):
    """Return {"verdict", "risk", "pattern", "reason", "ms"}, or None if the model is unavailable."""
    body = json.dumps({
        "model": LLM, "format": "json", "stream": False, "keep_alive": "30m",
        "options": {"temperature": 0, "num_ctx": 2048},  # same transcript -> same answer;
        # 2048-token context (we send ~600 chars) frees ~235 MB of GPU memory for whisper
        "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": text}],
    }).encode()
    t0 = time.time()
    try:
        req = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            v = json.loads(json.loads(r.read())["message"]["content"])
        v["risk"] = max(0, min(100, int(v.get("risk", 0))))
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError):
        return None  # a bad or missing reply must never break the guard; the rules still work
    if v.get("verdict") not in ("scam", "suspicious", "safe"):
        v["verdict"] = "suspicious" if v["risk"] >= 30 else "safe"
    if v.get("pattern") not in PATTERNS or v["verdict"] == "safe":
        v["pattern"] = "none"
    v["ms"] = int((time.time() - t0) * 1000)
    return v


if __name__ == "__main__":
    print(judge(" ".join(sys.argv[1:])))
