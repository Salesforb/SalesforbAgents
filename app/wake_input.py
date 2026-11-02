"""Rilevamento locale e rapido della frase di risveglio di SalesForB Agent ("SalesForB, sveglia")."""
import io
import os
import re
import threading
import time

_MODEL = None
_LOCK = threading.Lock()
from toro_paths import MODELS
MODEL_PATH = os.path.join(MODELS, "whisper-wake")
WAKE_RE = re.compile(
    r"\b(?:sales ?for\w*|sale ?for\w*|sails ?for\w*|selsforb|salesforce|sales|ehi sales|hey sales)[\s,.!]*"
    r"(?:sveglia|svegliati|sveglio|svelia|svela|sveia|sveja)\b|"
    r"^\s*(?:sveglia|svegliati|svelia|sveia)[\s.!?]*$", re.I)


def _modello():
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        _MODEL = WhisperModel(MODEL_PATH, device="cpu", compute_type="int8",
                              cpu_threads=2, num_workers=1, local_files_only=True)
    return _MODEL


def prepara():
    with _LOCK:
        _modello()


def _decodifica(audio):
    import av
    import numpy as np
    pezzi, totale = [], 0
    with av.open(io.BytesIO(audio)) as contenitore:
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=16000)
        for frame in contenitore.decode(audio=0):
            for out in resampler.resample(frame):
                valori = out.to_ndarray().reshape(-1)
                totale += len(valori)
                if totale > 20 * 16000:
                    raise ValueError("Frase di risveglio troppo lunga")
                pezzi.append(valori)
        for out in resampler.resample(None):
            pezzi.append(out.to_ndarray().reshape(-1))
    return np.concatenate(pezzi).astype(np.float32, copy=False) if pezzi else np.zeros(0, dtype=np.float32)


def _isola_voce(audio):
    import numpy as np
    from faster_whisper.vad import get_speech_timestamps, VadOptions
    if not len(audio):
        return audio
    picco = float(np.max(np.abs(audio)))
    if picco < .00001:
        return np.zeros(0, dtype=np.float32)
    audio = audio * min(20., .5 / picco)
    parti = get_speech_timestamps(audio, vad_options=VadOptions(
        threshold=.3, min_speech_duration_ms=40,
        min_silence_duration_ms=180, speech_pad_ms=180))
    if not parti:
        return np.zeros(0, dtype=np.float32)
    return audio[parti[0]["start"]:parti[-1]["end"]]


def rileva(audio):
    t0 = time.monotonic()
    campioni = _isola_voce(_decodifica(audio))
    if not len(campioni):
        return {"sveglia": False, "testo": "", "secondi": round(time.monotonic() - t0, 3)}
    with _LOCK:
        segmenti, _ = _modello().transcribe(
            campioni, language="it", beam_size=1, temperature=0,
            condition_on_previous_text=False, vad_filter=False,
            initial_prompt="SalesForB sveglia. SalesForB, svegliati.")
        testo = " ".join(x.text.strip() for x in segmenti if x.no_speech_prob < .85).strip()
    match = WAKE_RE.search(testo)
    resto = testo[match.end():].strip(" ,.!?:;") if match else ""
    return {"sveglia": bool(match), "solo_sveglia": bool(match and not resto),
            "testo": testo, "secondi": round(time.monotonic() - t0, 3)}
