#!/usr/bin/env python3
# Kavach: offline scam-call guard.
#   live:   python kavach.py                       (call on speaker next to the laptop)
#   replay: python kavach.py --file samples/scam_hi.wav --play
#   add --web for the alert page at http://localhost:8000 (--open also opens the browser)
#
# audio -> transcribe.py (whisper.cpp) -> rules.py (instant) + llm.py (every few seconds)
#       -> risk score -> red alert on screen + spoken Hindi warning
#       -> after a suspicious call: gemma.py writes a Hindi report (Gemma 4 online, local model offline)
#       -> web page: chat about the call, answered the same way

import argparse
import os
import subprocess
import sys
import threading
import time
import urllib.request

import gemma
import llm
import rules
import transcribe
import web

HOME = os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__))
WARN_VOICE = os.environ.get("WARN_VOICE", f"{HOME}/.local/share/kavach/hi_IN-priyamvada-medium.onnx")
WARN_TEXT = "सावधान! यह कॉल धोखाधड़ी लगती है। कोई पैसा या ओटीपी मत दीजिए। फ़ोन काट दीजिए।"

SCAM_AT = 60        # risk >= this: red alert + spoken warning
SUSPICIOUS_AT = 30  # risk >= this: yellow
LLM_EVERY = 4       # seconds between LLM checks
LLM_WINDOW = 600    # characters of recent transcript the LLM sees


class Call:
    """Everything known about the call so far. Shared by the audio, LLM and screen threads."""

    def __init__(self):
        self.lock = threading.Lock()
        self.lines = []      # finished transcript lines
        self.partial = ""    # line still being transcribed
        self.hits = {}       # pattern -> phrase that triggered it (kept for the whole call)
        self.ai = None       # last LLM verdict
        self.ai_text = ""    # transcript that verdict was about
        self.alerted = False
        self.done = False       # set by Ctrl+C, the end of a replay, or the page's "End call" button
        self.reporting = False
        self.report = None      # (who, text, seconds) once the after-call report is written
        self.chat = []          # (question, answer) pairs from the page
        self.online = False     # can we reach the Gemini API right now?

    def text(self):
        return " ".join(self.lines + [self.partial]).strip()

    def risk(self):
        # Words alone can mislead (a friend asking to borrow money says "transfer" too), so once the
        # local AI has judged the call, the risk is the average of both: red needs both to agree.
        # Before the AI's first verdict (first few seconds) the rules decide alone.
        r = rules.score(self.hits)
        risk = (r + self.ai["risk"]) // 2 if self.ai else r
        if not rules.TRICKS & self.hits.keys():
            risk = min(risk, SCAM_AT - 1)  # no scam trick heard yet: at most "suspicious"
        return risk

    def level(self):
        r = self.risk()
        return "scam" if r >= SCAM_AT else "warn" if r >= SUSPICIOUS_AT else "safe"

    def snapshot(self):
        # what the web page shows
        with self.lock:
            who, text, secs = self.report or (None, None, None)
            return {"risk": self.risk(), "level": self.level(), "hits": self.hits, "ai": self.ai,
                    "lines": self.lines[-12:], "partial": self.partial, "ended": self.done,
                    "reporting": self.reporting, "online": self.online,
                    "report": {"who": who, "text": text, "secs": secs} if self.report else None}

    def ask(self, question):
        # chat from the web page: Gemma 4 when online, the local model otherwise
        with self.lock:
            text, hits, history = self.text(), dict(self.hits), list(self.chat)
        who, answer, secs = gemma.chat(question, text, hits, history)
        with self.lock:
            self.chat.append((question, answer))
        return {"who": who, "text": answer, "secs": secs}

    def on_text(self, line, finished):
        with self.lock:
            if finished:
                self.lines.append(line)
                self.partial = ""
            else:
                self.partial = line
            for p, phrase in rules.find(self.text()).items():
                self.hits.setdefault(p, phrase)


def ai_loop(call):
    seen = ""
    while not call.done:
        time.sleep(LLM_EVERY)
        with call.lock:
            text = call.text()[-LLM_WINDOW:]
        if len(text) < 20 or text == seen:
            continue
        seen = text
        verdict = llm.judge(text)
        if verdict:
            with call.lock:
                call.ai, call.ai_text = verdict, text


def net_loop(call):
    # Only for the status pill on the page; the guard itself never needs the internet.
    while True:
        try:
            urllib.request.urlopen("https://generativelanguage.googleapis.com", timeout=3)
            call.online = True
        except urllib.error.HTTPError:
            call.online = True   # any HTTP answer means we are online
        except Exception:
            call.online = False
        time.sleep(10)


def load_warning():
    # Synthesize the warning once at start-up so it plays instantly when needed.
    try:
        from piper import PiperVoice
        v = PiperVoice.load(WARN_VOICE)
        return v.config.sample_rate, b"".join(c.audio_int16_bytes for c in v.synthesize(WARN_TEXT))
    except Exception as e:  # no voice must never stop the guard
        print(f"(no voice warning: {e})")
        return None


def speak(warning):
    if warning:
        rate, pcm = warning
        subprocess.run(["aplay", "-q", "-f", "S16_LE", "-c", "1", "-r", str(rate)], input=pcm)


RED, YEL, GRN, DIM, BOLD, RST = "\x1b[41;97m", "\x1b[43;30m", "\x1b[42;30m", "\x1b[2m", "\x1b[1m", "\x1b[0m"


def draw(call):
    with call.lock:
        risk, hits, ai = call.risk(), dict(call.hits), call.ai
        lines, partial = call.lines[-8:], call.partial
    cols = os.get_terminal_size().columns if sys.stdout.isatty() else 100
    if risk >= SCAM_AT:
        color, label = RED, "⚠  SCAM LIKELY: HANG UP. DON'T SHARE OTP OR SEND MONEY."
    elif risk >= SUSPICIOUS_AT:
        color, label = YEL, "!  SUSPICIOUS: be careful"
    else:
        color, label = GRN, "✓  No scam signs yet"
    bar = int(risk / 100 * (cols - 20))
    out = ["\x1b[H\x1b[2J", f"{BOLD}🛡  KAVACH{RST}  {DIM}offline scam-call guard{RST}\n",
           f"{color}{BOLD} {label.ljust(cols - 2)}{RST}\n",
           f" risk {risk:3d}  [{'█' * bar}{' ' * (cols - 20 - bar)}]\n"]
    if hits:
        out.append(f"\n{BOLD} Signals heard{RST}\n")
        out += [f"  • {p:<15} “{phrase}”\n" for p, phrase in hits.items()]
    if ai:
        out.append(f"\n{BOLD} Local AI{RST} {DIM}({ai['ms']} ms){RST}: {ai['verdict']} · {ai['pattern']}"
                   f" · {ai.get('reason', '')}\n")
    out.append(f"\n{BOLD} Live transcript{RST}\n")
    out += [f"  {l}\n" for l in lines]
    if partial:
        out.append(f"  {DIM}{partial}…{RST}\n")
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser(description="Kavach: offline scam-call guard")
    ap.add_argument("--file", help="replay a 16 kHz mono wav instead of listening to the mic")
    ap.add_argument("--play", action="store_true", help="with --file: also play the audio")
    ap.add_argument("--stream", help="test: feed a wav through the live pipeline instead of the mic")
    ap.add_argument("--quiet", action="store_true", help="don't speak the warning")
    ap.add_argument("--web", action="store_true", help="serve the alert page on http://localhost:8000")
    ap.add_argument("--open", action="store_true", help="with --web: open the page in the browser")
    args = ap.parse_args()

    print("Loading…")
    call = Call()
    warning = None if args.quiet else load_warning()
    if args.file:
        src = threading.Thread(target=transcribe.from_file, args=(args.file, call.on_text, args.play))
    else:
        src = threading.Thread(target=transcribe.live, args=(call.on_text, lambda: call.done, args.stream))
    src.daemon = True
    src.start()
    threading.Thread(target=ai_loop, args=(call,), daemon=True).start()
    if args.web:
        def end():
            call.done = True
        web.serve(call.snapshot, end, call.ask)
        threading.Thread(target=net_loop, args=(call,), daemon=True).start()
        if args.open:
            subprocess.Popen(["xdg-open", "http://localhost:8000"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)

    try:
        while src.is_alive() and not call.done:
            if args.web:
                print(f"\r{DIM}alert page: http://localhost:8000 · risk {call.risk():3d}{RST}", end="", flush=True)
            else:
                draw(call)
            with call.lock:
                fire = call.risk() >= SCAM_AT and not call.alerted
                call.alerted |= fire
            if fire:
                threading.Thread(target=speak, args=(warning,), daemon=True).start()
            time.sleep(0.4)
        # replay ended: give the LLM up to 20 s to judge the whole call
        with call.lock:
            full = call.text()[-LLM_WINDOW:]
        for _ in range(50 if not call.done else 0):
            with call.lock:
                if call.ai_text == full:
                    break
            time.sleep(0.4)
        if not args.web:
            draw(call)
    except KeyboardInterrupt:
        pass
    call.done = True
    risk = call.risk()
    print(f"\n{DIM}Call ended. Final risk {risk}.{RST}")
    if risk >= SUSPICIOUS_AT:
        print(f"\n{BOLD}Writing the after-call report…{RST}")
        call.reporting = True
        who, text, secs = gemma.report(call.text(), call.hits)
        call.report = (who, text, secs)
        print(f"\n{BOLD}📋 Report{RST} {DIM}({who}, {secs}s){RST}\n{text}\n")
        os.makedirs(f"{HERE}/reports", exist_ok=True)
        path = time.strftime(f"{HERE}/reports/call-%H%M%S.txt")
        with open(path, "w") as f:
            f.write(f"Risk {risk}\nSignals: {call.hits}\n\nTranscript:\n{call.text()}\n\n{who}:\n{text}\n")
        print(f"{DIM}saved {path}{RST}")
    if args.web:
        print(f"{DIM}page stays up for questions at http://localhost:8000 · Ctrl+C to quit{RST}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
