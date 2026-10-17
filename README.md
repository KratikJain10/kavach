# Kavach 🛡️

**An offline, open-source scam-call guard for India.**

Put a phone call on speaker next to your laptop. Kavach listens, transcribes the call live in Hindi, English
or Hinglish, and warns you **mid-call** when the caller uses a known scam script: fake police and
"digital arrest", KYC/OTP requests, parcels "with drugs", electricity cut-off threats, lottery prizes and more.
It tells you *why* (the exact words that gave it away) and says out loud:
*"सावधान! यह कॉल धोखाधड़ी लगती है…"*

Everything that listens to the call runs **on your own laptop**. The call never leaves your device.
When you're online, **Gemma 4** writes a short after-call report in simple Hindi and answers your
questions about the call ("I already sent money, what now?").

## How it works

```
 phone on speaker
       │
       ▼
 transcribe.py ── whisper.cpp (large-v3-turbo, GPU) ── sentence by sentence, auto volume boost
       │
       ├──► rules.py   instant: scam phrases in Hindi, English and romanized Hindi,
       │               including the misspellings speech-to-text really produces
       │
       ├──► llm.py     every 4 s: local llama3.2:3b (Ollama) judges the call → scam / suspicious / safe
       │
       ▼
 kavach.py ── risk = rules + local AI together ── red alert + spoken Hindi warning (Piper)
       │
       ├──► web.py     alert page on localhost: live transcript, signals, verdict, chat
       │
       └──► gemma.py   after the call: Gemma 4 report + chat (falls back to the local model offline)
```

**Not every money request is a scam.** A friend saying *"bhai 2000 bhej de, kal lauta dunga"* uses the
same words as a scammer. So Kavach only turns red when it hears an actual **trick** (fake authority, arrest
threats, OTP or remote-access requests, fake prizes, KYC, electricity), and only when the phrase rules and
the local AI agree. Money + urgency alone is at most "suspicious".

| Test call | Result |
|---|---|
| Fake Mumbai cyber police, "digital arrest", transfer money | 🔴 scam |
| Fake police: "your cousin is arrested, pay or FIR" | 🔴 scam |
| SBI KYC expiring, share OTP, install AnyDesk | 🔴 scam |
| Electricity will be cut tonight, call this number | 🔴 scam |
| KBC lottery, pay a processing fee | 🔴 scam |
| Friend borrowing ₹2000 / ₹5000 | 🟢 / 🟡 never red |
| Mom asking about dinner | 🟢 safe |

## Run it

Needs: Linux, [whisper.cpp](https://github.com/ggml-org/whisper.cpp) built at `~/whisper.cpp`
(with the `large-v3-turbo-q5_0` model), [Ollama](https://ollama.com) with `llama3.2:3b`, Python 3 and
`piper-tts`. Tested on an RTX 3050 laptop with 4 GB VRAM.

```sh
python -m venv .venv && .venv/bin/pip install piper-tts
ollama pull llama3.2:3b
echo "GEMINI_API_KEY=your-key" > .env      # optional: Gemma 4 reports and chat

./kavach check    # is everything ready?
./kavach          # live: the page opens at http://localhost:8000, press Start, put the call on speaker
./kavach demo     # same page, Start replays a sample scam call
./kavach safe     # same page, Start replays a normal call
```

## Stack

whisper.cpp · Ollama + llama3.2:3b · Piper TTS · Gemma 4 (Gemini API) · Python standard library only.

## License

MIT
