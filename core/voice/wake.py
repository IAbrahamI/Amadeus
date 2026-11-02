#!/usr/bin/env python3
"""Wake word: "Amadeus, what's on my calendar today?" in one go (the assistant's name, or your own wake words).
The listener hears the name at the start of what you say, keeps recording until you are really done (1.5 s of quiet;
pauses between words are fine), turns it into text with the local Whisper service and hands it to the small window,
which answers. Saying only the name makes it greet you (if you added voice lines) and listen for the request.

Light by design: the microphone is only checked for loudness; the word spotter (Vosk, small English model, limited
to the wake words) runs only while someone speaks, Whisper only for a request. Audio is never stored or sent anywhere.
Paused while ~/.local/share/amadeus/core/wake-off exists (tray: Wake word on/off)."""
import io
import json
import os
import random
import re
import subprocess
import threading
import time
import urllib.request
import wave
from collections import deque

import numpy as np
import vosk

HOME = os.path.expanduser("~")
DATA = os.path.join(HOME, ".local/share/amadeus/core")
VOICE = os.path.join(HOME, ".local/share/amadeus/voice")
MODEL = os.path.join(VOICE, "models/vosk-model-small-en-us-0.15")
CLIPS = os.path.join(VOICE, "clips")
OFF = os.path.join(DATA, "wake-off")
CFG_FILE = os.path.join(HOME, ".config/amadeus-core/config.json")
RATE, CHUNK = 16000, 1600  # 100 ms of 16-bit mono
GREETINGS = ["hey", "okay", "ok", "hi"]


def _cfg():
    try:
        return json.load(open(CFG_FILE))
    except Exception:
        return {}


def _pack():
    """Your optional voice lines: which clip plays when (clips/voice-pack.json, see docs/INSTALL.md)."""
    try:
        return json.load(open(os.path.join(CLIPS, "voice-pack.json")))
    except Exception:
        return {}


def _words():
    """The wake words: config "wake_words", else the assistant's name and "assistant"."""
    c = _cfg()
    return [w.lower() for w in c.get("wake_words") or [c.get("assistant_name", "Amadeus"), "assistant"]]


def _token():
    return open(os.path.join(DATA, "token")).read().strip()


def _post(url, body, ctype="application/json", timeout=60):
    req = urllib.request.Request(url, body, {"authorization": f"Bearer {_token()}", "content-type": ctype})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"{}")


def tell_window(**data):
    """The small window: 'listening' (show it), 'text' (your request), 'cancel'."""
    try:
        _post(f"http://127.0.0.1:{_cfg().get('port', 8095)}/api/wake", json.dumps(data).encode(), timeout=10)
    except Exception as e:
        print("window call failed:", e, flush=True)


def play(names, wait=True):
    names = [n for n in names if os.path.exists(os.path.join(CLIPS, n + ".ogg"))]
    if not names:
        return
    p = subprocess.Popen(["paplay", os.path.join(CLIPS, random.choice(names) + ".ogg")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if wait:
        p.wait(timeout=10)


def transcribe(pcm):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    try:
        return _post("http://127.0.0.1:8896/stt", buf.getvalue(), "audio/wav", timeout=90).get("text", "").strip()
    except Exception as e:
        print("speech recognition failed:", e, flush=True)
        return ""


FILLERS = {"hey", "hi", "ok", "okay", "im", "uh", "um", "oh", "so", "yo", "a", "and"}


def strip_name(heard):
    """What was said after the name, or None if the first words don't sound like one of the names. Whisper spells the
    name in many ways ("Amadeus", "Amadeo", "Amadius", "I'm a deus", "Kristina"), so this compares by sound-alike
    spelling, not exact words."""
    import difflib
    tokens = re.findall(r"[\w']+|[^\w\s]", heard)
    words = [(i, re.sub(r"\W", "", t).lower()) for i, t in enumerate(tokens) if re.sub(r"\W", "", t)]
    for k in range(min(4, len(words))):
        for n in (1, 2, 3):  # the name may come out as one word or split ("a deus", "a ma deus")
            chunk = "".join(w for _, w in words[k:k + n])
            if any(difflib.SequenceMatcher(None, chunk, name).ratio() >= 0.75 for name in _words()):
                rest = tokens[words[k + n - 1][0] + 1:] if k + n - 1 < len(words) else []
                out = re.sub(r"\s+([,.!?;:])", r"\1", " ".join(rest)).lstrip(" ,.!?;:-")
                return out
        if words[k][1] not in FILLERS:
            break
    return None


def called(result, words, min_conf):
    """The wake word must START what was said (after an optional "hey"), like calling someone: "Amadeus, …".
    A name in the middle of a sentence ("my sister Christine…", "it was assisted…") doesn't count."""
    said = [w for w in result.get("result", []) if w.get("word") not in GREETINGS]
    return said[0]["word"] if said and said[0].get("word") in words and said[0].get("conf", 0) >= min_conf else None


def partial_call(partial, words):
    said = [w for w in partial.split() if w not in GREETINGS]
    return said[0] if said and said[0] in words else None


class Mic:
    def __init__(self):
        self.p = subprocess.Popen(["parec", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1",
                                   "--latency-msec=100", "--client-name=Amadeus wake word"], stdout=subprocess.PIPE)
        self.floor = 300.0

    def read(self):
        buf = self.p.stdout.read(CHUNK * 2)
        if len(buf) < CHUNK * 2:
            raise EOFError("microphone closed")
        rms = float(np.sqrt(np.mean(np.frombuffer(buf, np.int16).astype(np.float32) ** 2)))
        loud = rms > max(self.floor * 2.5, 250)
        if not loud:
            self.floor = 0.95 * self.floor + 0.05 * rms  # follows the room's own noise
        return buf, loud

    def close(self):
        self.p.terminate()


def record_request(mic, audio, start_wait=80, quiet_end=15, max_len=300):
    """Keep recording until the user is done: `quiet_end` chunks of quiet after speech (1.5 s), or nothing at all
    for `start_wait` chunks (8 s), or `max_len` chunks (30 s)."""
    spoke, quiet, n = bool(audio), 0, 0
    while n < max_len:
        buf, loud = mic.read()
        n += 1
        if not spoke and not loud:
            if n >= start_wait:
                return b""
            continue
        spoke = True
        audio.append(buf)
        quiet = 0 if loud else quiet + 1
        if quiet >= quiet_end:
            break
    return b"".join(audio)


def handle(mic, word, phrase_audio):
    """After the wake word: get the whole request, transcribe it, hand it to the window. The window only appears once
    Whisper confirmed the name: the word spotter alone mistakes normal talk for "Amadeus" now and then (that's what
    made it pop up while you were talking to a friend)."""
    pcm = record_request(mic, list(phrase_audio))
    heard = transcribe(pcm) if pcm else ""
    text = strip_name(heard)
    if text is None:  # Whisper (more accurate) didn't hear anything like the name at the start: a false alarm
        print(f"wake: false alarm (Whisper's first word: {(heard.split() or ['-'])[0][:20]!r})", flush=True)
        return
    if len(re.sub(r"\W", "", text)) < 2:  # only the name: greet, then listen for the request
        tell_window(stage="listening", word=word)
        greet = _pack().get("wake_greet", {})
        play(greet.get(word) or greet.get("", []))
        pcm = record_request(mic, [])
        heard = transcribe(pcm) if pcm else ""
        text = strip_name(heard) if strip_name(heard) is not None else heard
    if len(re.sub(r"\W", "", text)) < 2:
        tell_window(stage="cancel")
        return
    print(f"wake request: {len(text.split())} words", flush=True)
    heard_lines = _pack().get("actions", {}).get("heard", [])  # e.g. "OK": it heard you and is on it
    threading.Thread(target=play, args=(heard_lines,), daemon=True).start()
    tell_window(stage="text", word=word, text=text)


def listen():
    words = _words()
    min_conf = float(_cfg().get("wake_confidence", 0.6))
    vosk.SetLogLevel(-1)
    model, grammar = vosk.Model(MODEL), json.dumps(words + GREETINGS + ["[unk]"])
    mic = Mic()
    pre = deque(maxlen=4)  # 0.4 s before the sound started, so the word's beginning isn't cut off
    try:
        while not os.path.exists(OFF):
            buf, loud = mic.read()
            if not loud:
                pre.append(buf)
                continue
            # a phrase starts: feed it to the word spotter until a pause; react as soon as it starts with the name
            phrase, quiet, word = list(pre) + [buf], 0, None
            pre.clear()
            # a fresh recognizer per phrase: a reused one keeps adapting to the last request and then hears the
            # next "Amadeus" as an unknown word first (that's why only the first request used to work)
            rec = vosk.KaldiRecognizer(model, RATE, grammar)
            rec.SetWords(True)
            for b in phrase:
                rec.AcceptWaveform(b)
            while quiet < 6 and len(phrase) < 30:
                buf, loud = mic.read()
                phrase.append(buf)
                quiet = 0 if loud else quiet + 1
                rec.AcceptWaveform(buf)
                if len(phrase) % 3 == 0 and len(phrase) >= 6:
                    word = partial_call(json.loads(rec.PartialResult()).get("partial", ""), words)
                    if word:
                        break
            if not word:
                word = called(json.loads(rec.FinalResult()), words, min_conf)
            if word:
                print(f"wake: {word}", flush=True)
                handle(mic, word, phrase)
            elif len(phrase) >= 30:  # a long sentence without the name at its start: skip until the next pause
                while True:
                    buf, loud = mic.read()
                    if not loud:
                        break
    finally:
        mic.close()


def main():
    while True:
        if os.path.exists(OFF):  # paused: the microphone is not opened at all
            time.sleep(2)
            continue
        try:
            listen()
        except Exception as e:
            print("wake listener error:", e, flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
