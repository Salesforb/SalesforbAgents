"""Voce locale di SalesForB (niente ElevenLabs, niente costi).

1) Kokoro-82M su Apple Silicon (mlx-audio), voce italiana "if_sara" o "im_nicola".
2) Se Kokoro non è disponibile: la voce italiana di macOS (comando `say`).
Restituisce sempre un WAV (il browser lo suona come prima suonava l'mp3)."""
import io, os, subprocess, tempfile, threading, wave

from toro_paths import MODELS

KOKORO_DIR = os.path.join(MODELS, "kokoro-82m")
_MODEL = None
_LOCK = threading.Lock()
MOTORE = {"nome": "in preparazione"}


def _env():
    try:
        from llm import env
        return env()
    except Exception:
        return {}


def _kokoro():
    global _MODEL
    if _MODEL is None:
        from mlx_audio.tts.utils import load_model
        _MODEL = load_model(KOKORO_DIR if os.path.isdir(KOKORO_DIR) else "mlx-community/Kokoro-82M-bf16")
    return _MODEL


def _wav(campioni, rate):
    import numpy as np
    pcm = (np.clip(np.asarray(campioni, dtype=np.float32).reshape(-1), -1, 1) * 32767).astype("<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm.tobytes())
    return out.getvalue()


def _con_kokoro(testo):
    import numpy as np
    e = _env()
    with _LOCK:
        model = _kokoro()
        pezzi = [np.array(r.audio) for r in model.generate(text=testo, voice=e.get("SF_VOCE", "if_sara"),
                                                           speed=float(e.get("SF_VOCE_VELOCITA", "1.05")), lang_code="i")]
    if not pezzi:
        raise RuntimeError("Kokoro non ha prodotto audio")
    MOTORE["nome"] = "Kokoro locale · " + e.get("SF_VOCE", "if_sara")
    return _wav(np.concatenate([p.reshape(-1) for p in pezzi]), 24000)


def _con_say(testo):
    voce = _env().get("SF_VOCE_MAC", "Alice")
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "v.wav")
        subprocess.run(["/usr/bin/say", "-v", voce, "-r", "190", "--file-format=WAVE", "--data-format=LEI16@22050", "-o", f, testo],
                       check=True, timeout=60, capture_output=True)
        MOTORE["nome"] = "Voce macOS · " + voce
        return open(f, "rb").read()


def sintetizza(testo):
    testo = (testo or "").strip()[:900]
    if not testo:
        return b""
    if _env().get("SF_TTS", "kokoro") == "kokoro":
        try:
            return _con_kokoro(testo)
        except Exception as e:
            MOTORE["errore_kokoro"] = f"{type(e).__name__}: {e}"[:200]
    return _con_say(testo)


def prepara():
    """Scalda il modello e prepara il saluto."""
    try:
        from toro_paths import BASE
        f = os.path.join(BASE, "app", "saluto.wav")
        audio = sintetizza("Eccomi, ti ascolto.")
        if audio and not os.path.exists(f):
            open(f, "wb").write(audio)
    except Exception as e:
        MOTORE["errore"] = str(e)[:200]
