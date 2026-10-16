#!/usr/bin/env python3
"""Send text to your IndicF5 server and save the audio locally.

PowerShell:
    $env:INDICF5_URL = "http://IP:PORT"
    $env:INDICF5_API_KEY = "your-secret"
    python client/tts_client.py "नमस्ते, आप कैसे हैं?" -o hello.wav
    python client/tts_client.py -f story.txt -o story.wav
"""
import argparse
import io
import os
import re
import sys
import wave

import requests

MAX_CHARS = 500


def split_text(text, limit=MAX_CHARS):
    sentences = re.split(r"(?<=[.!?।॥])\s+", text.strip())
    chunks, cur = [], ""
    for s in sentences:
        if cur and len(cur) + len(s) + 1 > limit:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def synthesize(url, key, text):
    headers = {"X-API-Key": key} if key else {}
    r = requests.post(f"{url.rstrip('/')}/tts", json={"text": text}, headers=headers, timeout=300)
    if r.status_code == 401:
        sys.exit("401: wrong or missing API key.")
    r.raise_for_status()
    return r.content


def join_wavs(parts, out_path):
    with wave.open(out_path, "wb") as out:
        for i, data in enumerate(parts):
            with wave.open(io.BytesIO(data), "rb") as w:
                if i == 0:
                    out.setparams(w.getparams())
                out.writeframes(w.readframes(w.getnframes()))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("text", nargs="?", help="text to speak")
    p.add_argument("-f", "--file", help="read text from this UTF-8 file")
    p.add_argument("-o", "--output", default="output.wav")
    p.add_argument("--url", default=os.environ.get("INDICF5_URL"))
    p.add_argument("--key", default=os.environ.get("INDICF5_API_KEY"))
    a = p.parse_args()

    if not a.url:
        sys.exit("Set INDICF5_URL or pass --url.")
    text = open(a.file, encoding="utf-8").read() if a.file else a.text
    if not text:
        sys.exit("Provide text or --file.")

    chunks = split_text(text)
    parts = []
    for i, c in enumerate(chunks, 1):
        print(f"[{i}/{len(chunks)}] generating...", flush=True)
        parts.append(synthesize(a.url, a.key, c))

    if len(parts) == 1:
        with open(a.output, "wb") as f:
            f.write(parts[0])
    else:
        join_wavs(parts, a.output)
    print(f"Saved {a.output}")


if __name__ == "__main__":
    main()