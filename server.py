#!/usr/bin/env python3
"""PC Remote - streame l'ecran + le son de Windows vers un navigateur (Switch 2)
et permet de controler le PC (souris, clavier, texte).

Lancement :  start.bat   (ou :  python server.py --help)
"""
import os

# --- DPI : DOIT etre fait avant mss / pyautogui -------------------------------
# Sans ca, avec une mise a l'echelle Windows (125 %, 150 %...) les coordonnees
# de la souris et celles de la capture d'ecran ne sont pas dans la meme unite
# et le curseur n'atteint qu'une partie de l'ecran.
if os.name == "nt":
    import ctypes as _ct
    try:
        _ct.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor
    except Exception:
        try:
            _ct.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import argparse
import asyncio
import ctypes
import ctypes.wintypes as wt   # seulement pour SendInput.restype
import io
import json
import logging
import math
import queue
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

import numpy as np
import av
import mss
from PIL import Image
import pyautogui
from flask import Flask, Response, jsonify, request
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from aiortc.mediastreams import MediaStreamError

# --- Saisie clavier compatible jeux (DirectInput : Roblox, jeux Unity...) -----
# pydirectinput envoie des SCAN CODES (comme un vrai clavier) et non des
# caracteres : indispensable pour les jeux qui lisent DirectInput/raw input et
# ignorent completement SendInput (donc pyautogui). Repli propre si absent.
try:
    import pydirectinput
    pydirectinput.PAUSE = 0
    pydirectinput.FAILSAFE = False
    _HAVE_PDI = True
except Exception:
    pydirectinput = None
    _HAVE_PDI = False

# pygetwindow permet de forcer une fenetre au premier plan : les jeux ignorent
# les entrees quand leur fenetre n'est pas active.
try:
    import pygetwindow as _gw
except Exception:
    _gw = None

try:
    import soundcard as sc
except Exception as _exc:                                  # audio optionnel
    sc = None
    _SC_ERROR = _exc

pyautogui.PAUSE = 0          # defaut = 0.1 s de pause APRES chaque action !
pyautogui.FAILSAFE = False   # sinon le coin haut-gauche leve une exception

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

log = logging.getLogger("pcremote")


# ============================================================================
#  Reglages
# ============================================================================
class Settings:
    host = "0.0.0.0"
    port = 5000
    fps = 30
    max_width = 1280       # largeur max du flux (l'image est reduite si plus large)
    bitrate = 4000         # kbit/s
    monitor = 1            # 1 = ecran principal, 2 = second ecran, 0 = tous
    audio = True
    cursor = True          # dessiner le curseur (mss ne le capture pas)


CFG = Settings()


class Geometry:
    """Rectangle de l'ecran capture, en pixels physiques (memes unites que le curseur)."""
    left, top, width, height = 0, 0, 1920, 1080


GEOM = Geometry()


# --- Suivi des changements d'ecran (permet de choisir l'ecran a la volee) -----
_monitor_lock = threading.Lock()
_monitor_gen = 0


def get_monitor_gen():
    with _monitor_lock:
        return _monitor_gen


def bump_monitor_gen():
    """Force tous les ScreenGrabber a re-ouvrir mss au prochain grab()."""
    global _monitor_gen
    with _monitor_lock:
        _monitor_gen += 1


# ============================================================================
#  Entrees : souris / clavier / texte
# ============================================================================
BUTTONS = {"left", "right", "middle"}
MODIFIERS = {"ctrl", "alt", "shift", "win"}
NAMED_KEYS = {
    "esc", "enter", "space", "backspace", "tab", "up", "down", "left", "right",
    "home", "end", "pageup", "pagedown", "delete", "insert", "win",
    "volumeup", "volumedown", "volumemute", "playpause", "nexttrack", "prevtrack",
    # modificateurs et verrou : maintenables via keydown / keyup (mode jeu ZQSD)
    "shift", "ctrl", "alt", "capslock",
} | {"f%d" % i for i in range(1, 13)}
CHAR_KEYS = set("abcdefghijklmnopqrstuvwxyz0123456789")
ALL_KEYS = NAMED_KEYS | CHAR_KEYS

MAX_TYPE_CHARS = 500
SCROLL_UNIT = 120 if os.name == "nt" else 1     # 120 = un cran de molette sous Windows

# --- SendInput (Windows) : saisie de texte Unicode (accents, emojis...) ------
# ATTENTION : ne PAS definir SendInput.argtypes ici. pydirectinput utilise sa
# propre structure INPUT et appelle la meme fonction SendInput ; si on impose
# notre type via argtypes, ctypes rejette l'appel de pydirectinput avec
#   TypeError: expected LP_INPUT instance instead of LP_Input
# On se contente donc de restype, qui ne gene personne.
ULONG_PTR = ctypes.c_size_t


# Types a taille fixe (LONG/DWORD = 32 bits, WORD = 16 bits) : identiques a Windows,
# mais la disposition memoire reste correcte et verifiable sur n'importe quel OS.
_I32, _U32, _U16 = ctypes.c_int32, ctypes.c_uint32, ctypes.c_uint16


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", _I32), ("dy", _I32), ("mouseData", _U32),
                ("dwFlags", _U32), ("time", _U32), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", _U16), ("wScan", _U16), ("dwFlags", _U32),
                ("time", _U32), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", _U32), ("wParamL", _U16), ("wParamH", _U16)]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", _U32), ("u", _INPUT_UNION)]


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

_user32 = None
if os.name == "nt":
    _user32 = ctypes.windll.user32
    # PAS de _user32.SendInput.argtypes : voir le commentaire plus haut.
    _user32.SendInput.restype = wt.UINT
    _user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)


def _send_utf16_units(units):
    n = len(units) * 2
    arr = (INPUT * n)()
    for i, unit in enumerate(units):
        for j in range(2):                                   # appui puis relache
            inp = arr[2 * i + j]
            inp.type = INPUT_KEYBOARD
            inp.ki.wVk = 0
            inp.ki.wScan = unit
            inp.ki.dwFlags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if j else 0)
    _user32.SendInput(n, arr, ctypes.sizeof(INPUT))


def _type_segment(seg):
    data = seg.encode("utf-16-le", "surrogatepass")
    units = struct.unpack("<%dH" % (len(data) // 2), data)
    for i in range(0, len(units), 16):                       # petits paquets : plus fiable
        _send_utf16_units(units[i:i + 16])
        time.sleep(0.004)


def type_text(text):
    """Ecrit du texte quelle que soit la disposition du clavier (AZERTY, accents, emojis)."""
    text = text[:MAX_TYPE_CHARS]
    if os.name != "nt":
        pyautogui.write(text, interval=0.01)                 # repli (ASCII seulement)
        return
    seg = []
    for ch in text:
        if ch in "\r\n\t":
            if seg:
                _type_segment("".join(seg))
                seg = []
            if ch == "\n":
                _press("enter")
            elif ch == "\t":
                _press("tab")
        else:
            seg.append(ch)
    if seg:
        _type_segment("".join(seg))


def _num(value, lo=None, hi=None):
    v = float(value)
    if not math.isfinite(v):
        raise ValueError("nombre invalide")
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def move_to(nx, ny):
    """(nx, ny) sont normalises 0..1 par rapport a l'image diffusee."""
    g = GEOM
    px = g.left + int(round(_num(nx, 0, 1) * (g.width - 1)))
    py = g.top + int(round(_num(ny, 0, 1) * (g.height - 1)))
    if _user32 is not None:
        _user32.SetCursorPos(px, py)
    else:
        pyautogui.moveTo(px, py)


def _button(msg):
    b = msg.get("b", "left")
    return b if b in BUTTONS else "left"


# --------------------------------------------------------------- clavier ----
def _keydown(k):
    """Appui d'une touche. pydirectinput envoie un scan code : indispensable pour
    les jeux (Roblox, Unity...) qui lisent DirectInput et ignorent SendInput."""
    if _HAVE_PDI:
        try:
            pydirectinput.keyDown(k)
            return
        except Exception as exc:
            log.warning("pydirectinput.keyDown(%s) : %s", k, exc)
    pyautogui.keyDown(k)


def _keyup(k):
    if _HAVE_PDI:
        try:
            pydirectinput.keyUp(k)
            return
        except Exception as exc:
            log.warning("pydirectinput.keyUp(%s) : %s", k, exc)
    pyautogui.keyUp(k)


def _press(k):
    if _HAVE_PDI:
        try:
            pydirectinput.press(k)
            return
        except Exception as exc:
            log.warning("pydirectinput.press(%s) : %s", k, exc)
    pyautogui.press(k)


def _hotkey(keys):
    if _HAVE_PDI:
        try:
            for mod in keys[:-1]:
                pydirectinput.keyDown(mod)
            pydirectinput.press(keys[-1])
            for mod in reversed(keys[:-1]):
                pydirectinput.keyUp(mod)
            return
        except Exception as exc:
            log.warning("pydirectinput.hotkey(%s) : %s", keys, exc)
    pyautogui.hotkey(*keys)


def focus_window(title_substr):
    """Met au premier plan la premiere fenetre dont le titre contient `title_substr`.
    Les jeux n'acceptent les entrees que si leur fenetre est active."""
    if _gw is None:
        log.debug("pygetwindow indisponible : impossible de forcer le premier plan")
        return False
    try:
        matches = [w for w in _gw.getAllWindows()
                   if title_substr.lower() in (w.title or "").lower()]
        if not matches:
            return False
        w = matches[0]
        if w.isMinimized:
            w.restore()
            time.sleep(0.1)
        w.activate()
        time.sleep(0.15)
        return True
    except Exception as exc:
        log.debug("focus_window(%s) : %s", title_substr, exc)
        return False


def handle_input(msg):
    """Execute UN message d'entree. Appele depuis le thread InputController."""
    t = msg.get("t")
    if t in ("move", "click", "dblclick", "down", "up") and "x" in msg and "y" in msg:
        move_to(msg["x"], msg["y"])
    if t == "move":
        return
    if t == "click":
        pyautogui.click(button=_button(msg))
    elif t == "dblclick":
        pyautogui.doubleClick(button=_button(msg))
    elif t == "down":
        pyautogui.mouseDown(button=_button(msg))
    elif t == "up":
        pyautogui.mouseUp(button=_button(msg))
    elif t == "scroll":
        dy = _num(msg.get("dy", 0), -20, 20)
        if dy:
            pyautogui.scroll(int(dy * SCROLL_UNIT))
    elif t == "key":
        k = msg.get("k")
        if k in ALL_KEYS:
            _press(k)
    elif t == "keydown":                # touche maintenue (mode jeu ZQSD)
        k = msg.get("k")
        if k in ALL_KEYS:
            _keydown(k)
    elif t == "keyup":                  # relachement de la touche maintenue
        k = msg.get("k")
        if k in ALL_KEYS:
            _keyup(k)
    elif t == "hotkey":
        keys = msg.get("keys")
        if (isinstance(keys, list) and 2 <= len(keys) <= 4
                and all(k in MODIFIERS for k in keys[:-1]) and keys[-1] in ALL_KEYS):
            _hotkey(keys)
    elif t == "type":
        text = msg.get("text")
        if isinstance(text, str) and text:
            type_text(text)
    elif t == "focus":                  # forcer une fenetre au premier plan (jeu)
        title = msg.get("title") or "Roblox"
        if isinstance(title, str):
            focus_window(title[:120])


class InputController(threading.Thread):
    """Execute les entrees dans UN thread : dans l'ordre, sans bloquer la boucle
    asyncio, et en fusionnant les deplacements de souris successifs."""

    def __init__(self):
        super().__init__(name="input", daemon=True)
        self.q = queue.Queue(maxsize=512)

    def submit(self, msg):
        if not isinstance(msg, dict):
            return
        try:
            self.q.put_nowait(msg)
        except queue.Full:
            pass                                             # on prefere perdre un mouvement

    def submit_json(self, raw):
        try:
            self.submit(json.loads(raw))
        except ValueError:
            pass

    def run(self):
        pending = None
        while True:
            msg = pending if pending is not None else self.q.get()
            pending = None
            if msg.get("t") == "move":
                while True:                                  # ne garder que le dernier move
                    try:
                        nxt = self.q.get_nowait()
                    except queue.Empty:
                        break
                    if nxt.get("t") == "move":
                        msg = nxt
                    else:
                        pending = nxt
                        break
            try:
                handle_input(msg)
            except Exception as exc:                         # une entree ratee ne doit pas tuer le thread
                log.warning("entree ignoree (%s): %s", msg.get("t"), exc)


CONTROLLER = InputController()


# ============================================================================
#  Video : capture de l'ecran
# ============================================================================
VIDEO_CLOCK = 90000
VIDEO_TIME_BASE = Fraction(1, VIDEO_CLOCK)

_ARROW = [
    "X...........",
    "XX..........",
    "XWX.........",
    "XWWX........",
    "XWWWX.......",
    "XWWWWX......",
    "XWWWWWX.....",
    "XWWWWWWX....",
    "XWWWWWWWX...",
    "XWWWWWWWWX..",
    "XWWWWWXXXXX.",
    "XWWXWWX.....",
    "XWX.XWWX....",
    "XX..XWWX....",
    "X....XWWX...",
    ".....XWWX...",
    "......XX....",
]
_sprite_cache = {}


def cursor_sprite(k):
    """(image BGRA, masque) du curseur, agrandi k fois."""
    if k not in _sprite_cache:
        h, w = len(_ARROW), len(_ARROW[0])
        img = np.zeros((h, w, 4), np.uint8)
        mask = np.zeros((h, w), bool)
        for y, row in enumerate(_ARROW):
            for x, c in enumerate(row):
                if c == "X":
                    img[y, x] = (0, 0, 0, 255)
                    mask[y, x] = True
                elif c == "W":
                    img[y, x] = (255, 255, 255, 255)
                    mask[y, x] = True
        if k > 1:
            img = np.repeat(np.repeat(img, k, axis=0), k, axis=1)
            mask = np.repeat(np.repeat(mask, k, axis=0), k, axis=1)
        _sprite_cache[k] = (img, mask)
    return _sprite_cache[k]


def draw_cursor(arr, cx, cy, k):
    """Dessine le curseur en (cx, cy) dans arr (H, W, 4) BGRA, en place."""
    h, w = arr.shape[:2]
    if not (0 <= cx < w and 0 <= cy < h):
        return
    img, mask = cursor_sprite(k)
    x2, y2 = min(w, cx + mask.shape[1]), min(h, cy + mask.shape[0])
    m = mask[:y2 - cy, :x2 - cx]
    arr[cy:y2, cx:x2][m] = img[:y2 - cy, :x2 - cx][m]


def target_size(w, h, max_w):
    """Taille du flux : reduite si trop large, toujours paire (exige par yuv420p)."""
    if w > max_w:
        h = int(round(h * max_w / w))
        w = max_w
    return max(2, w & ~1), max(2, h & ~1)


class ScreenGrabber:
    """Capture d'ecran (mss + curseur dessine). A utiliser depuis UN SEUL thread :
    mss/GDI doit rester dans le thread qui l'a cree."""

    def __init__(self):
        self._sct = None
        self._mon = None
        self._refresh_at = 0.0
        self._gen = None              # generation du choix d'ecran vue par cet objet

    def open(self):
        self.close()
        self._sct = mss.mss()
        mons = self._sct.monitors
        idx = CFG.monitor if 0 <= CFG.monitor < len(mons) else 1
        self._mon = dict(mons[idx])
        GEOM.left, GEOM.top = self._mon["left"], self._mon["top"]
        GEOM.width, GEOM.height = self._mon["width"], self._mon["height"]
        # on re-enumere les ecrans de temps en temps (changement de resolution, jeu plein ecran...)
        self._refresh_at = time.monotonic() + 5.0

    def close(self):
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None

    def grab(self):
        """-> (image BGRA (H, W, 4) avec curseur, largeur du flux, hauteur du flux)"""
        gen = get_monitor_gen()                  # l'utilisateur a-t-il change d'ecran ?
        if gen != self._gen:
            self._gen = gen
            self._refresh_at = 0                 # force la reouverture de mss
        if self._sct is None or time.monotonic() >= self._refresh_at:
            self.open()
        try:
            shot = self._sct.grab(self._mon)
        except Exception:
            self.open()                                      # 2e essai (changement de bureau, UAC...)
            shot = self._sct.grab(self._mon)
        arr = np.asarray(shot)
        tw, th = target_size(shot.width, shot.height, CFG.max_width)
        if CFG.cursor:
            try:
                pos = pyautogui.position()
                if not arr.flags.writeable:
                    arr = arr.copy()
                k = max(1, int(round(shot.width / tw)))
                draw_cursor(arr, int(pos[0]) - self._mon["left"], int(pos[1]) - self._mon["top"], k)
            except Exception:
                pass
        return arr, tw, th


class ScreenTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self):
        super().__init__()
        self._interval = 1.0 / max(1, CFG.fps)
        # UN seul thread dedie : la capture ne doit pas bloquer la boucle asyncio (audio, reseau...).
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="screen")
        self._grabber = ScreenGrabber()
        self._t0 = None
        self._next = None
        self._last_warn = 0.0

    def _grab(self):                                         # tourne dans le thread de capture
        arr, tw, th = self._grabber.grab()
        frame = av.VideoFrame.from_ndarray(arr, format="bgra")
        return frame.reformat(width=tw, height=th, format="yuv420p")

    # -- cote asyncio ------------------------------------------------------------
    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError
        loop = asyncio.get_running_loop()
        now = loop.time()
        if self._next is None:
            self._t0 = self._next = now
        if now < self._next:
            await asyncio.sleep(self._next - now)
        self._next = max(self._next + self._interval, loop.time())

        while True:
            try:
                frame = await loop.run_in_executor(self._pool, self._grab)
                break
            except Exception as exc:
                if self.readyState != "live":
                    raise MediaStreamError
                if time.monotonic() - self._last_warn > 5:
                    self._last_warn = time.monotonic()
                    log.warning("capture d'ecran impossible (%s), nouvel essai...", exc)
                await asyncio.sleep(0.25)
        if self.readyState != "live":
            raise MediaStreamError
        frame.pts = int((loop.time() - self._t0) * VIDEO_CLOCK)
        frame.time_base = VIDEO_TIME_BASE
        return frame

    def stop(self):
        if self.readyState == "live":
            try:
                self._pool.submit(self._grabber.close)
                self._pool.shutdown(wait=False)
            except Exception:
                pass
        super().stop()


# ============================================================================
#  Audio : loopback WASAPI (le son que le PC joue)
# ============================================================================
AUDIO_RATE = 48000
AUDIO_BLOCK = 960                     # 20 ms
AUDIO_GRACE = 0.04                    # au-dela, on insere du silence


def pcm16_stereo(data):
    """float (N, canaux) -> int16 (N, 2) contigu, entrelace L R L R..."""
    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 1:
        data = data[:, None]
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    return np.ascontiguousarray((np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16))


class LoopbackCapture(threading.Thread):
    """Thread dedie : soundcard/COM doivent rester dans le meme thread du debut a la fin."""

    def __init__(self, on_pcm):
        super().__init__(name="audio-capture", daemon=True)
        self._on_pcm = on_pcm
        self._halt = threading.Event()
        self.ready = threading.Event()
        self.error = None

    def stop(self):
        self._halt.set()

    @staticmethod
    def _open():
        speaker = sc.default_speaker()
        if speaker is None:
            raise RuntimeError("Aucune sortie audio Windows trouvee.")
        try:
            mic = sc.get_microphone(speaker.id, include_loopback=True)
        except Exception:
            mic = sc.get_microphone(speaker.name, include_loopback=True)
        rec = mic.recorder(samplerate=AUDIO_RATE, channels=2, blocksize=AUDIO_BLOCK)
        return speaker.name, rec

    def run(self):
        first = True
        while not self._halt.is_set():
            try:
                name, rec = self._open()
                with rec:
                    log.info("audio : capture de \"%s\"", name)
                    first = False
                    self.ready.set()
                    while not self._halt.is_set():
                        self._on_pcm(rec.record(numframes=AUDIO_BLOCK))
            except Exception as exc:
                if first:                                    # echec au demarrage : on le signale
                    self.error = exc
                    self.ready.set()
                    return
                log.warning("audio : %s - nouvel essai dans 1 s", exc)   # ex. casque branche/debranche
                self._halt.wait(1.0)


class SystemAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, loop):
        super().__init__()
        self._loop = loop
        self._q = asyncio.Queue(maxsize=25)                  # 0,5 s max
        self._silence = np.zeros((1, AUDIO_BLOCK * 2), np.int16)
        self._t0 = None
        self._samples = 0
        self._capture = LoopbackCapture(self._from_thread)
        self._capture.start()

    def wait_ready(self, timeout):
        """Bloquant : a appeler dans un executor. Leve une exception si le loopback est indisponible."""
        self._capture.ready.wait(timeout)
        if self._capture.error is not None:
            raise self._capture.error
        if not self._capture.ready.is_set():
            raise TimeoutError("le peripherique audio ne repond pas")

    def _from_thread(self, data):
        # s16 "packed" : PyAV veut la forme (1, echantillons * canaux), entrelace L R L R...
        pcm = pcm16_stereo(data).reshape(1, -1)
        try:
            self._loop.call_soon_threadsafe(self._enqueue, pcm)
        except RuntimeError:                                 # boucle fermee
            self._capture.stop()

    def _enqueue(self, pcm):
        if self._q.full():
            self._q.get_nowait()                             # trop de retard : on jette le plus vieux
        self._q.put_nowait(pcm)

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError
        loop = asyncio.get_running_loop()
        if self._t0 is None:
            self._t0 = loop.time()
        if not self._q.empty():
            pcm = self._q.get_nowait()
        else:
            due = self._t0 + self._samples / AUDIO_RATE
            timeout = due + AUDIO_GRACE - loop.time()
            pcm = self._silence
            if timeout > 0:
                try:
                    pcm = await asyncio.wait_for(self._q.get(), timeout)
                except asyncio.TimeoutError:
                    pass                                     # rien de joue : silence (le flux reste continu)
        if self.readyState != "live":
            raise MediaStreamError
        frame = av.AudioFrame.from_ndarray(pcm, format="s16", layout="stereo")
        frame.sample_rate = AUDIO_RATE
        frame.time_base = Fraction(1, AUDIO_RATE)
        frame.pts = self._samples          # compteur d'echantillons, PAS l'horloge : evite les craquements
        self._samples += AUDIO_BLOCK
        return frame

    def stop(self):
        self._capture.stop()
        super().stop()


# ============================================================================
#  WebRTC
# ============================================================================
pcs = set()
loop = asyncio.new_event_loop()


def _run_loop():
    asyncio.set_event_loop(loop)
    loop.run_forever()


def tune_bitrate(kbps):
    """aiortc encode par defaut a ~0,5-1,5 Mbit/s : illisible pour du texte. On releve."""
    bps = int(kbps) * 1000
    for name in ("vpx", "h264"):
        try:
            mod = __import__("aiortc.codecs." + name, fromlist=["x"])
        except Exception:
            continue
        if hasattr(mod, "DEFAULT_BITRATE"):
            mod.DEFAULT_BITRATE = bps
        if hasattr(mod, "MAX_BITRATE"):
            mod.MAX_BITRATE = bps * 2


async def shutdown_pc(pc):
    pcs.discard(pc)
    for sender in pc.getSenders():             # sinon la capture continue apres la deconnexion
        if sender.track is not None:
            try:
                sender.track.stop()
            except Exception:
                pass
    try:
        await pc.close()
    except Exception:
        pass


async def make_answer(sdp, typ):
    for old in list(pcs):                      # un seul spectateur : le plus recent prend la main
        await shutdown_pc(old)

    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_state():
        log.info("WebRTC : %s", pc.connectionState)
        # "disconnected" est souvent transitoire (Wi-Fi) : on n'abandonne que sur failed/closed
        if pc.connectionState in ("failed", "closed"):
            await shutdown_pc(pc)

    @pc.on("datachannel")
    def on_channel(channel):
        @channel.on("message")
        def on_message(message):
            if isinstance(message, str):
                CONTROLLER.submit_json(message)

    audio_ok = False
    audio = None
    try:
        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=typ))
        pc.addTrack(ScreenTrack())
        if CFG.audio:
            try:
                if sc is None:
                    raise RuntimeError("module soundcard indisponible : %s" % _SC_ERROR)
                audio = SystemAudioTrack(asyncio.get_running_loop())
                await asyncio.get_running_loop().run_in_executor(None, audio.wait_ready, 4.0)
                pc.addTrack(audio)
                audio_ok = True
            except Exception as exc:           # pas de son ne doit pas empecher l'image
                log.warning("audio desactive : %s", exc)
                if audio is not None:
                    audio.stop()
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
    except Exception:
        await shutdown_pc(pc)
        raise
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "audio": audio_ok}


# ============================================================================
#  Mode de secours SANS WebRTC (ex. navigateur de la Switch 2)
#    image : flux MJPEG (<img>) ou images JPEG une par une
#    son   : PCM 16 bits brut lu par fetch() et joue avec Web Audio
# ============================================================================
JPEG_QUALITY = 72
_RESAMPLE = getattr(getattr(Image, "Resampling", Image), "BILINEAR")


def encode_jpeg(arr, tw, th):
    img = Image.frombuffer("RGB", (arr.shape[1], arr.shape[0]), arr.tobytes(), "raw", "BGRX", 0, 1)
    if img.size != (tw, th):
        img = img.resize((tw, th), _RESAMPLE)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


class JpegStreamer:
    """UN thread de capture partage par tous les clients MJPEG ; il s'arrete tout seul
    quelques secondes apres le dernier client."""
    IDLE_STOP = 5.0

    def __init__(self):
        self._cond = threading.Condition()
        self._seq = 0
        self._jpg = None
        self._clients = 0
        self._last_used = 0.0
        self._thread = None

    def _ensure_thread(self):                                # verrou deja pris
        self._last_used = time.monotonic()
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="mjpeg", daemon=True)
            self._thread.start()

    def acquire(self):
        with self._cond:
            self._clients += 1
            self._ensure_thread()

    def release(self):
        with self._cond:
            self._clients -= 1
            self._last_used = time.monotonic()

    def wait_frame(self, after, timeout):
        """Attend une image plus recente que `after`. -> (numero, jpeg) ; jpeg=None si rien."""
        with self._cond:
            self._cond.wait_for(lambda: self._seq > after, timeout)
            return self._seq, (self._jpg if self._seq > after else None)

    def latest(self, timeout=3.0):
        with self._cond:
            self._ensure_thread()
            self._cond.wait_for(lambda: self._jpg is not None, timeout)
            return self._jpg

    def _run(self):
        grabber = ScreenGrabber()
        interval = 1.0 / max(1, CFG.fps)
        last_warn = 0.0
        try:
            while True:
                with self._cond:
                    if self._clients <= 0 and time.monotonic() - self._last_used > self.IDLE_STOP:
                        self._thread = None
                        self._jpg = None
                        return
                t0 = time.monotonic()
                try:
                    arr, tw, th = grabber.grab()
                    jpg = encode_jpeg(arr, tw, th)
                except Exception as exc:
                    if time.monotonic() - last_warn > 5:
                        last_warn = time.monotonic()
                        log.warning("capture MJPEG impossible (%s), nouvel essai...", exc)
                    time.sleep(0.25)
                    continue
                with self._cond:
                    self._jpg = jpg
                    self._seq += 1
                    self._cond.notify_all()
                time.sleep(max(0.0, interval - (time.monotonic() - t0)))
        finally:
            grabber.close()
            with self._cond:
                if self._thread is threading.current_thread():
                    self._thread = None


JPEG = JpegStreamer()
NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}


# ============================================================================
#  Flask
# ============================================================================
app = Flask(__name__, static_folder=None)


@app.get("/")
def index():
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return Response(page, mimetype="text/html", headers={"Cache-Control": "no-store"})


@app.post("/offer")
def offer():
    data = request.get_json(silent=True) or {}
    sdp, typ = data.get("sdp"), data.get("type")
    if not isinstance(sdp, str) or typ != "offer":
        return jsonify(error="Offre WebRTC invalide"), 400
    future = asyncio.run_coroutine_threadsafe(make_answer(sdp, typ), loop)
    try:
        return jsonify(future.result(timeout=30))
    except Exception as exc:
        future.cancel()
        log.exception("echec de la connexion WebRTC")
        return jsonify(error=str(exc) or exc.__class__.__name__), 500


@app.get("/video.mjpg")
def video_mjpg():
    """Flux MJPEG : fonctionne dans un simple <img>, sans WebRTC."""
    def gen():
        JPEG.acquire()
        seq = 0
        try:
            while True:
                seq, jpg = JPEG.wait_frame(seq, 2.0)
                if jpg:
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpg)
                           + jpg + b"\r\n")
        finally:
            JPEG.release()
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame", headers=NO_CACHE)


@app.get("/frame.jpg")
def frame_jpg():
    """Une seule image (repli si le navigateur ne sait pas lire le flux MJPEG)."""
    jpg = JPEG.latest()
    if not jpg:
        return "capture indisponible", 503
    return Response(jpg, mimetype="image/jpeg", headers=NO_CACHE)


@app.get("/audio.pcm")
def audio_pcm():
    """Son du PC en PCM 16 bits, 48 kHz, stereo, little-endian, en flux continu."""
    if not CFG.audio or sc is None:
        return "audio indisponible", 503
    q = queue.Queue(maxsize=60)

    def on_pcm(data):
        chunk = pcm16_stereo(data).tobytes()
        try:
            q.put_nowait(chunk)
        except queue.Full:
            try:
                q.get_nowait()                               # trop de retard : on jette le plus vieux
                q.put_nowait(chunk)
            except (queue.Empty, queue.Full):
                pass

    cap = LoopbackCapture(on_pcm)
    cap.start()
    cap.ready.wait(4.0)
    if cap.error is not None or not cap.ready.is_set():
        cap.stop()
        log.warning("audio (mode secours) indisponible : %s", cap.error or "delai depasse")
        return "audio indisponible", 503

    silence = bytes(AUDIO_BLOCK * 4)

    def gen():
        try:
            while True:
                try:
                    chunk = q.get(timeout=0.06)
                except queue.Empty:
                    chunk = silence                          # rien ne joue : le flux reste continu
                try:
                    chunk += q.get_nowait()                  # petits paquets de ~40 ms
                except queue.Empty:
                    pass
                yield chunk
        finally:
            cap.stop()                                       # client parti -> on libere le loopback
    return Response(gen(), mimetype="application/octet-stream", headers=NO_CACHE)


@app.post("/input")
def input_http():
    """Repli si le canal de donnees WebRTC n'est pas (encore) ouvert."""
    msg = request.get_json(silent=True)
    if isinstance(msg, dict):
        CONTROLLER.submit(msg)
    return "", 204


@app.get("/monitors")
def monitors_list():
    """Liste les ecrans disponibles + l'ecran actuellement diffuse."""
    try:
        with mss.mss() as sct:
            items = []
            for i, mon in enumerate(sct.monitors):
                if i == 0:
                    items.append({
                        "index": 0,
                        "label": "🖥  Tous les écrans (%d×%d)" % (mon["width"], mon["height"]),
                    })
                else:
                    items.append({
                        "index": i,
                        "label": "Écran %d  (%d×%d)" % (i, mon["width"], mon["height"]),
                    })
            return jsonify(monitors=items, current=CFG.monitor)
    except Exception as exc:
        log.warning("liste des ecrans impossible : %s", exc)
        return jsonify(error=str(exc)), 500


@app.post("/monitor")
def monitor_set():
    """Change l'ecran diffuse a chaud."""
    data = request.get_json(silent=True) or {}
    idx = data.get("index")
    if not isinstance(idx, int) or idx < 0 or idx > 16:
        return jsonify(error="index invalide"), 400
    CFG.monitor = idx
    bump_monitor_gen()
    log.info("ecran de diffusion -> %d", idx)
    return jsonify(ok=True, current=idx)


# ============================================================================
#  Demarrage
# ============================================================================
def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))       # aucun paquet n'est envoye
        return s.getsockname()[0]
    except OSError:
        return "IP_DU_PC"
    finally:
        s.close()


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="PC Remote : ecran + son + controle du PC dans un navigateur.")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--fps", type=int, default=30, help="images/seconde (defaut 30)")
    p.add_argument("--width", type=int, default=1280, help="largeur max du flux, ex. 1920 (defaut 1280)")
    p.add_argument("--bitrate", type=int, default=4000, help="debit video en kbit/s (defaut 4000)")
    p.add_argument("--monitor", type=int, default=1, help="ecran a diffuser : 0=tous, 1, 2... (defaut 1)")
    p.add_argument("--no-audio", action="store_true", help="ne pas envoyer le son")
    p.add_argument("--no-cursor", action="store_true", help="ne pas dessiner le curseur dans l'image")
    return p.parse_args(argv)


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("aiortc", "aioice", "werkzeug"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    CFG.host, CFG.port = args.host, args.port
    CFG.fps = max(1, min(60, args.fps))
    CFG.max_width = max(320, args.width)
    CFG.bitrate = max(300, args.bitrate)
    CFG.monitor = max(0, args.monitor)
    CFG.audio = not args.no_audio
    CFG.cursor = not args.no_cursor

    tune_bitrate(CFG.bitrate)

    try:                                       # geometrie de depart (mise a jour ensuite par la capture)
        with mss.mss() as sct:
            mon = sct.monitors[CFG.monitor if CFG.monitor < len(sct.monitors) else 1]
            GEOM.left, GEOM.top, GEOM.width, GEOM.height = mon["left"], mon["top"], mon["width"], mon["height"]
    except Exception as exc:
        log.warning("ecran non detecte (%s)", exc)

    CONTROLLER.start()
    threading.Thread(target=_run_loop, name="asyncio", daemon=True).start()

    if _HAVE_PDI:
        log.info("clavier : pydirectinput actif (jeux DirectInput/Roblox compatibles)")
    else:
        log.warning("clavier : pydirectinput ABSENT -> les jeux DirectInput ignoreront les touches")
        log.warning("          installe-le avec : pip install pydirectinput pygetwindow")

    url = "http://%s:%d" % (lan_ip(), CFG.port)
    print()
    print("  PC Remote")
    print("  ---------------------------------------------")
    print("  Sur la Switch 2, ouvre :  %s" % url)
    print("  Ecran %d - %dx%d - %d ips - audio %s" % (
        CFG.monitor, GEOM.width, GEOM.height, CFG.fps, "oui" if CFG.audio else "non"))
    print("  Clavier jeux : %s" % ("pydirectinput OK" if _HAVE_PDI else "pyautogui seul (jeux non supportes)"))
    print("  Ctrl+C pour arreter.")
    print()
    try:
        app.run(host=CFG.host, port=CFG.port, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()