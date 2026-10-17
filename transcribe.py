#!/usr/bin/env python3
# Speech to text for Kavach, using whisper.cpp.
#   live: python transcribe.py                  (mic)
#   file: python transcribe.py samples/x.wav --play
#   test the live pipeline without a mic: python transcribe.py samples/x.wav --stream
# Every source calls on_text(line, finished): finished=False while a sentence is still being spoken.

import array
import io
import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import wave

HOME = os.path.expanduser("~")
WHISPER_DIR = os.environ.get("WHISPER_DIR", f"{HOME}/whisper.cpp")
WHISPER_MODEL = f"{WHISPER_DIR}/models/ggml-{os.environ.get('WHISPER_MODEL', 'large-v3-turbo-q5_0')}.bin"
LANG = os.environ.get("KAVACH_LANG", "hi")  # "auto" also works
SERVER_PORT = 8178
# A tiny hint keeps whisper writing Hindi in Devanagari (longer hints leak into the transcript).
HINT = "नमस्ते।"

RATE = 16000
FRAME = 480                 # 30 ms of audio per frame
END_SILENCE = 0.7           # a pause this long ends a sentence
MAX_SENTENCE = 18           # never wait longer than this before transcribing
PREVIEW_EVERY = 2.0         # show what's being said every 2 s while someone talks


def is_junk(line):
    # whisper hallucinates on silence: very short lines, or one word repeated ("झाल झाल झाल").
    # Also drops whisper's own status lines like "[Start speaking]" or "[BLANK_AUDIO]".
    words = line.split()
    if len(line) < 4 or (line.startswith("[") and line.endswith("]")):
        return True
    return len(words) >= 3 and len(set(words)) / len(words) < 0.5


# ── whisper-server: keeps the model loaded so each sentence takes ~1 s ───────────
def _start_server():
    base = [f"{WHISPER_DIR}/build/bin/whisper-server", "-m", WHISPER_MODEL, "-l", LANG, "-t", "6",
            "-bs", "1", "-nt", "--prompt", HINT, "--port", str(SERVER_PORT)]
    for cmd in (base, base + ["-ng"]):  # GPU first; CPU if the GPU is full
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            if proc.poll() is not None:
                break  # crashed (usually out of GPU memory): try the next command
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{SERVER_PORT}/", timeout=1)
                if "-ng" in cmd:
                    print("(whisper: GPU busy, using CPU)", file=sys.stderr)
                return proc
            except Exception:
                time.sleep(0.25)
        proc.kill()
    raise RuntimeError("whisper-server would not start")


def _transcribe(pcm):
    # send one sentence (16-bit mono PCM) to whisper-server as a wav upload
    wav = io.BytesIO()
    with wave.open(wav, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE), w.writeframes(pcm)
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"response_format\"\r\n\r\njson\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"temperature\"\r\n\r\n0.0\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"s.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode() + wav.getvalue() + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(f"http://127.0.0.1:{SERVER_PORT}/inference", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read()).get("text", "").strip()
    except Exception:
        return ""


def _louder(pcm):
    # automatic gain: bring quiet speech up to a healthy level (max 20x) so the mic setting doesn't matter
    a = array.array("h", pcm)
    peak = max(1, max(abs(x) for x in a))
    gain = min(20.0, 0.8 * 32767 / peak)
    if gain > 1.1:
        a = array.array("h", (int(max(-32767, min(32767, x * gain))) for x in a))
    return a.tobytes()


def _rms(frame):
    a = array.array("h", frame)
    return math.sqrt(sum(x * x for x in a) / len(a)) if a else 0


# ── live: sentence by sentence ──────────────────────────────────────────────────
def live(on_text, stop=lambda: False, wav_path=None):
    """Listen to the mic (or replay wav_path at real speed through the same pipeline)."""
    server = _start_server()
    frames = queue.Queue()
    reader = _wav_reader if wav_path else _mic_reader
    threading.Thread(target=reader, args=(frames, stop, wav_path), daemon=True).start()

    noise = 200.0          # running estimate of background noise loudness
    sentence, pre = [], []
    silent = spoken = 0.0
    last_preview = time.time()
    try:
        while not stop():
            try:
                f = frames.get(timeout=1)
            except queue.Empty:
                continue
            if f is None:  # end of the wav file
                break
            level = _rms(f)
            talking = level > max(noise * 2.5, 250)
            if not talking:
                noise = 0.95 * noise + 0.05 * level  # learn the room's noise from quiet moments
            if not sentence:
                pre = (pre + [f])[-10:]  # keep 300 ms before speech starts so the first word isn't cut
                if talking:
                    sentence, silent, spoken = pre + [f], 0.0, 0.03
                continue
            sentence.append(f)
            silent = 0.0 if talking else silent + 0.03
            spoken += 0.03 if talking else 0
            length = len(sentence) * 0.03
            if silent >= END_SILENCE or length >= MAX_SENTENCE:
                if spoken > 0.4:  # ignore clicks and coughs
                    _emit(on_text, _transcribe(_louder(b"".join(sentence))), True)
                sentence, pre = [], []
            elif length > 1.5 and time.time() - last_preview > PREVIEW_EVERY:
                last_preview = time.time()
                _emit(on_text, _transcribe(_louder(b"".join(sentence))), False)
        if sentence and spoken > 0.4:
            _emit(on_text, _transcribe(_louder(b"".join(sentence))), True)
    finally:
        server.terminate()


def _mic_reader(frames, stop, _):
    rec = subprocess.Popen(["arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"],
                           stdout=subprocess.PIPE)
    try:
        while not stop():
            f = rec.stdout.read(FRAME * 2)
            if not f:
                break
            frames.put(f)
    finally:
        rec.terminate()


def _wav_reader(frames, stop, path):
    # pretend the file is a mic: same frames, same pace, plus a second of silence after it
    with wave.open(path) as w:
        data = w.readframes(w.getnframes()) + b"\0" * RATE * 2
    start = time.time()
    for i in range(0, len(data), FRAME * 2):
        if stop():
            break
        time.sleep(max(0, start + i / 2 / RATE - time.time()))
        frames.put(data[i:i + FRAME * 2])
    frames.put(None)


# ── file: whole recording at once (demo backup) ──────────────────────────────────
def from_file(path, on_text, play=False):
    # Transcribe the whole file, then release each segment at its real time,
    # optionally playing the audio so it looks and sounds like a live call.
    cmd = [f"{WHISPER_DIR}/build/bin/whisper-cli", "-m", WHISPER_MODEL, "-l", LANG,
           "-f", path, "-np", "-bs", "1", "-bo", "1", "--prompt", HINT]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:  # usually the GPU is full (the LLM uses most of it): retry on the CPU
        print("(whisper: GPU busy, falling back to CPU)", file=sys.stderr)
        out = subprocess.run(cmd + ["-ng"], capture_output=True, text=True)
    segs = re.findall(r"\[(\d+):(\d+):([\d.]+) --> (\d+):(\d+):([\d.]+)\]\s*(.*)", out.stdout)
    if not segs:
        raise RuntimeError(f"whisper-cli gave no text: {out.stderr.strip()[-300:]}")
    if play:
        subprocess.Popen(["aplay", "-q", path])
    start = time.time()
    for *t, text in segs:
        end = int(t[3]) * 3600 + int(t[4]) * 60 + float(t[5])
        time.sleep(max(0, start + end - time.time()))
        _emit(on_text, text, True)


def _emit(on_text, line, finished):
    line = line.strip()
    if not is_junk(line):
        on_text(line, finished)


if __name__ == "__main__":
    def show(line, finished):
        print(("✔ " if finished else "… ") + line, flush=True)

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    try:
        if args and "--stream" in sys.argv:
            live(show, wav_path=args[0])
        elif args:
            from_file(args[0], show, play="--play" in sys.argv)
        else:
            print("Listening… Ctrl+C to stop")
            live(show)
    except KeyboardInterrupt:
        pass
