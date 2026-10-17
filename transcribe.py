#!/usr/bin/env python3
# Speech to text for Kavach, using whisper.cpp.
#   live: python transcribe.py                  (mic)
#   file: python transcribe.py samples/x.wav --play
# Both sources call on_text(line, finished): finished=False while a line is still changing.

import codecs
import os
import re
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
WHISPER_DIR = os.environ.get("WHISPER_DIR", f"{HOME}/whisper.cpp")
WHISPER_MODEL = f"{WHISPER_DIR}/models/ggml-{os.environ.get('WHISPER_MODEL', 'large-v3-turbo-q5_0')}.bin"
LANG = os.environ.get("KAVACH_LANG", "hi")  # "auto" also works


def is_junk(line):
    # whisper hallucinates on silence: very short lines, or one word repeated ("झाल झाल झाल").
    # Also drops whisper's own status lines like "[Start speaking]" or "[BLANK_AUDIO]".
    words = line.split()
    if len(line) < 4 or (line.startswith("[") and line.endswith("]")):
        return True
    return len(words) >= 3 and len(set(words)) / len(words) < 0.5


def live(on_text, stop=lambda: False):
    # whisper-stream re-transcribes a sliding 10 s window every 3 s. Each update redraws the
    # current line ("\x1b[2K\r" + text); a newline means that window is final.
    # -bs 1 (greedy) keeps GPU memory low enough to share 4 GB with the LLM.
    cmd = [f"{WHISPER_DIR}/build/bin/whisper-stream", "-m", WHISPER_MODEL, "-l", LANG, "-t", "6",
           "--step", "3000", "--length", "10000", "--keep", "200", "-bs", "1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    dec, buf = codecs.getincrementaldecoder("utf-8")(errors="ignore"), ""
    got_text = False
    try:
        while not stop():
            data = os.read(proc.stdout.fileno(), 4096)
            if not data:
                if not got_text and "-ng" not in cmd:
                    # exited before any text: usually the GPU is full. Retry on the CPU.
                    print("(whisper: GPU busy, falling back to CPU)", file=sys.stderr)
                    cmd.append("-ng")
                    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                    continue
                break
            got_text = True
            buf += dec.decode(data)
            *done, buf = buf.split("\n")
            for chunk in done:
                _emit(on_text, chunk.split("\x1b[2K\r")[-1], True)
            _emit(on_text, buf.split("\x1b[2K\r")[-1], False)
    finally:
        proc.terminate()


def from_file(path, on_text, play=False):
    # Demo backup: transcribe the whole file, then release each segment at its real time,
    # optionally playing the audio so it looks and sounds like a live call.
    cmd = [f"{WHISPER_DIR}/build/bin/whisper-cli", "-m", WHISPER_MODEL, "-l", LANG,
           "-f", path, "-np", "-bs", "1", "-bo", "1"]
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
        if args:
            from_file(args[0], show, play="--play" in sys.argv)
        else:
            print("Listening… Ctrl+C to stop")
            live(show)
    except KeyboardInterrupt:
        pass
