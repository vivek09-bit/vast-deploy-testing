"""IndicF5 TTS server.

Environment variables:
  HF_TOKEN        Hugging Face token (model is gated; accept terms first)
  API_KEY         If set, clients must send header  X-API-Key: <value>
  REF_AUDIO_PATH  Reference voice clip (required)
  REF_TEXT        Transcript of that reference clip (required)
  MODEL_ID        Default: ai4bharat/IndicF5
  HOST / PORT     Default: 0.0.0.0 / 8000
"""
import io
import os
import secrets
import threading
from contextlib import asynccontextmanager

import numpy as np
import soundfile as sf
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

MODEL_ID = os.environ.get("MODEL_ID", "ai4bharat/IndicF5")
API_KEY = os.environ.get("API_KEY")
SAMPLE_RATE = 24000

_state = {}
_gpu_lock = threading.Lock()  # serialize inference on the single GPU


@asynccontextmanager
async def lifespan(app: FastAPI):
    from transformers import AutoModel

    ref_audio = os.environ.get("REF_AUDIO_PATH")
    ref_text = os.environ.get("REF_TEXT")
    if not ref_audio or not ref_text:
        raise RuntimeError("Set REF_AUDIO_PATH and REF_TEXT environment variables.")

    model = AutoModel.from_pretrained(MODEL_ID, trust_remote_code=True)
    try:
        import torch

        if torch.cuda.is_available():
            model = model.to("cuda")
    except Exception as exc:
        print(f"[warn] could not move model to CUDA: {exc}")

    _state.update(model=model, ref_audio=ref_audio, ref_text=ref_text)
    yield
    _state.clear()


app = FastAPI(title="IndicF5 TTS", lifespan=lifespan)


def check_key(x_api_key: str | None = Header(default=None)):
    if API_KEY and not (x_api_key and secrets.compare_digest(x_api_key, API_KEY)):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": "model" in _state}


@app.post("/tts", dependencies=[Depends(check_key)])
def tts(req: TTSRequest):
    with _gpu_lock:
        audio = _state["model"](
            req.text,
            ref_audio_path=_state["ref_audio"],
            ref_text=_state["ref_text"],
        )
    if audio.dtype == np.int16:
        audio = audio.astype(np.float32) / 32768.0
    buf = io.BytesIO()
    sf.write(buf, np.array(audio, dtype=np.float32), SAMPLE_RATE, format="WAV")
    return Response(buf.getvalue(), media_type="audio/wav")


def main():
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    main()