__author__ = "Viet Nguyen"
# Gesture Control Edition — modified for NEU FIT
# v3: 2x scale, aggressive difficulty curve, MediaPipe gesture, leaderboard

import os, sys, json, threading, datetime, random, base64, io, math
import pygame
from pygame import *
import time as time   # must come AFTER `from pygame import *` to shadow pygame.time
import math as std_math  # from pygame import * shadows the standard math module

try:
    import cv2, mediapipe as mp
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    print("[WARN] mediapipe/opencv not found — keyboard-only mode.")

# ─────────────────────────────────────────────────────────────────────────────
#  SCALE FACTOR  — change this one constant to resize everything
# ─────────────────────────────────────────────────────────────────────────────
S = 2   # 2 = double size

# ─────────────────────────────────────────────────────────────────────────────
#  PYGAME INIT
# ─────────────────────────────────────────────────────────────────────────────
pygame.mixer.pre_init(44100, -16, 2, 2048)
pygame.init()

# Original canvas was 600x150 — scale both dimensions
width, height = 600 * S, 150 * S
scr_size = (width, height)
FPS      = 60
gravity  = 0.6 * S          # gravity scales with height

background_col = (235, 235, 235)
dark_col       = (83,  83,  83)
white          = (255, 255, 255)
accent_col     = (26,  115, 232)
gold_col       = (249, 168,  37)
silver_col     = (120, 144, 156)
bronze_col     = (141, 110,  99)
panel_col      = (215, 215, 215)
green_col      = (46,  125,  50)
red_col        = (198,  40,  40)
black          = (0,   0,   0)

# Backgrounds are selected by score. Put these PNG files in ./sprites/.
# The /mnt/data fallback only helps when testing inside this chat environment.
BACKGROUND_STAGES = [
    # score, filename, UI theme
    (0,    "background_1.png",  "light"),
    (250,  "background_4.png",  "light"),
    (500,  "background_3.png",  "dark"),
    (800,  "background_5.png",  "light"),
    (1100, "background_6.png",  "light"),
    (1450, "background_7.png",  "light"),
    (1850, "background_8.png",  "light"),
    (2300, "background_9.png",  "dark"),
    (2800, "background_10.png", "dark"),
    (3400, "background_12.png", "light"),
    (4100, "background_13.png", "light"),
    (5000, "background_11.png", "dark"),
]

high_score = 0

# Real fullscreen display.
# The game is still drawn on a fixed logical canvas, then scaled into the center.
# This lets us draw extra HUD panels in the black letterbox areas.
try:
    # vsync=1 helps reduce tearing/stutter on Pygame 2 when the driver supports it.
    display = pygame.display.set_mode((0, 0), pygame.FULLSCREEN, vsync=1)
except TypeError:
    display = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
except Exception:
    display = pygame.display.set_mode(scr_size)

screen = pygame.Surface(scr_size).convert()
clock  = pygame.time.Clock()
pygame.display.set_caption("T-Rex Rush  |  Gesture Control")

# Small runtime optimizations:
# - ignore unused event types because this version does not use mouse input
# - prevent OS screensaver from interrupting fullscreen gameplay
try:
    pygame.event.set_allowed([pygame.QUIT, pygame.KEYDOWN, pygame.KEYUP])
except Exception:
    pass
try:
    pygame.display.set_allow_screensaver(False)
except Exception:
    pass


def _background_candidates(filename):
    return [
        os.path.join("sprites", filename),
        filename,
        os.path.join("/mnt/data", filename),
    ]


def load_optional_background(filename):
    for path in _background_candidates(filename):
        try:
            if path and os.path.exists(path):
                print(f"[INFO] background loaded: {path}")
                return pygame.image.load(path).convert()
        except Exception as e:
            print(f"[WARN] cannot load background image {path}: {e}")
    print(f"[WARN] background not found: {filename}")
    return None


game_background_image = None
current_background_stage = None
current_background_theme = "light"
_background_image_cache = {}
_game_bg_cache = {}
_aligned_game_bg_cache = {}


def get_background_stage_for_score(score):
    selected = BACKGROUND_STAGES[0]
    for stage in BACKGROUND_STAGES:
        if score >= stage[0]:
            selected = stage
        else:
            break
    return selected


def set_background_for_score(score, force=False):
    """Switch background only when the score enters a new stage."""
    global game_background_image, current_background_stage, current_background_theme

    stage = get_background_stage_for_score(score)
    if not force and current_background_stage == stage:
        return

    _, filename, theme = stage
    img = _background_image_cache.get(filename)
    if img is None:
        img = load_optional_background(filename)
        _background_image_cache[filename] = img

    # If a selected file is missing, keep the previous background instead of flashing.
    if img is None and game_background_image is not None:
        current_background_stage = stage
        current_background_theme = theme
        return

    game_background_image = img
    current_background_stage = stage
    current_background_theme = theme
    _game_bg_cache.clear()
    _aligned_game_bg_cache.clear()


def get_current_theme_colors():
    if current_background_theme == "dark":
        return {
            "hud_text": (245, 248, 255),
            "hud_shadow": (12, 18, 30),
            "score_panel": (10, 18, 34, 155),
            "score_border": (120, 180, 255, 150),
            "hint_text": (240, 245, 255),
        }
    return {
        "hud_text": dark_col,
        "hud_shadow": (255, 255, 255),
        "score_panel": (255, 250, 235, 155),
        "score_border": (114, 83, 50, 130),
        "hint_text": (65, 65, 65),
    }


def draw_alpha_round_rect(target, rect, color, radius=8, width=0):
    """Draw RGBA rounded rectangles on normal display surfaces."""
    if len(color) == 4 and color[3] < 255:
        temp = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(temp, color, temp.get_rect(), width=width, border_radius=radius)
        target.blit(temp, rect.topleft)
    else:
        pygame.draw.rect(target, color, rect, width=width, border_radius=radius)


set_background_for_score(0, force=True)


def get_scaled_background(size):
    if game_background_image is None:
        return None
    key = (int(size[0]), int(size[1]))
    if key[0] <= 0 or key[1] <= 0:
        return None
    if key not in _game_bg_cache:
        src_w, src_h = game_background_image.get_size()
        scale = max(key[0] / src_w, key[1] / src_h)
        scaled_w = max(1, int(src_w * scale))
        scaled_h = max(1, int(src_h * scale))
        scaled = pygame.transform.smoothscale(game_background_image, (scaled_w, scaled_h))
        x = max(0, (scaled_w - key[0]) // 2)
        y = max(0, (scaled_h - key[1]) // 2)
        crop = pygame.Surface(key).convert()
        crop.blit(scaled, (0, 0), pygame.Rect(x, y, key[0], key[1]))
        _game_bg_cache[key] = crop
    return _game_bg_cache[key]


def draw_game_background(target_surface):
    bg = None

    # Important:
    # The fullscreen display is usually 16:9, while the logical game canvas is 4:1.
    # If we crop the background separately for the 4:1 canvas, the sky/ground will
    # not align with the fullscreen background. So for the game canvas, we take the
    # exact slice of the fullscreen background that sits behind the gameplay area.
    # This version caches that aligned slice instead of re-cropping and re-scaling
    # it every frame, which removes a common source of stutter.
    if target_surface is screen and game_background_image is not None:
        try:
            display_size = display.get_size()
            game_rect = get_game_rect_on_display()
            cache_key = (
                display_size,
                target_surface.get_size(),
                game_rect.x,
                game_rect.y,
                game_rect.width,
                game_rect.height,
            )
            bg = _aligned_game_bg_cache.get(cache_key)
            if bg is None:
                full_bg = get_scaled_background(display_size)
                if full_bg is not None and game_rect.width > 0 and game_rect.height > 0:
                    src_x = max(0, game_rect.x)
                    src_y = max(0, game_rect.y)
                    src_rect = pygame.Rect(
                        src_x,
                        src_y,
                        min(game_rect.width, display_size[0] - src_x),
                        min(game_rect.height, display_size[1] - src_y),
                    )

                    if src_rect.width > 0 and src_rect.height > 0:
                        crop = pygame.Surface((src_rect.width, src_rect.height)).convert()
                        crop.blit(full_bg, (0, 0), src_rect)
                        bg = pygame.transform.smoothscale(crop, target_surface.get_size())
                        _aligned_game_bg_cache.clear()
                        _aligned_game_bg_cache[cache_key] = bg
        except Exception as e:
            print(f"[WARN] cannot align game background: {e}")

    if bg is None:
        bg = get_scaled_background(target_surface.get_size())

    if bg is not None:
        target_surface.blit(bg, (0, 0))
    else:
        target_surface.fill(background_col)

jump_sound       = pygame.mixer.Sound('sprites/jump.wav')
die_sound        = pygame.mixer.Sound('sprites/die.wav')
checkPoint_sound = pygame.mixer.Sound('sprites/checkPoint.wav')

# ─────────────────────────────────────────────────────────────────────────────
#  DIFFICULTY CONFIG
#  Score bands → (gamespeed, max_cacti, ptera_chance_per_frame, min_gap_px)
#  gamespeed is pixels/frame; original started at 4
# ─────────────────────────────────────────────────────────────────────────────
#  Each tuple: (score_threshold, speed, max_cactus_count, ptera_prob/frame,
#               cactus_new_prob/frame, min_gap_fraction_of_width)
DIFF_TABLE = [
    #  score  speed  maxC  pteraP  cactP   minGap
    (    0,    4*S,   1,   0.000,  1/50,   0.70),
    (  100,    5*S,   1,   0.000,  1/45,   0.68),
    (  200,    6*S,   2,   1/300,  1/42,   0.65),
    (  350,    7*S,   2,   1/250,  1/38,   0.62),
    (  500,    8*S,   2,   1/200,  1/34,   0.58),
    (  700,    9*S,   3,   1/180,  1/30,   0.55),
    (  900,   10*S,   3,   1/160,  1/28,   0.52),
    ( 1200,   11*S,   3,   1/140,  1/26,   0.48),
    ( 1600,   12*S,   3,   1/120,  1/24,   0.45),
    ( 2000,   13*S,   3,   1/100,  1/22,   0.42),
]

def get_difficulty(score):
    cfg = DIFF_TABLE[0]
    for row in DIFF_TABLE:
        if score >= row[0]:
            cfg = row
        else:
            break
    return cfg   # (score, speed, maxC, pteraP, cactP, minGap)

# ─────────────────────────────────────────────────────────────────────────────
#  LEADERBOARD  (scores.json  +  scores.txt backup)
# ─────────────────────────────────────────────────────────────────────────────
SCORES_FILE = "scores.json"
SCORES_TXT  = "scores.txt"

def load_leaderboard():
    try:
        with open(SCORES_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d, list): return d
    except Exception: pass
    return []

def save_leaderboard(scores):
    try:
        with open(SCORES_FILE, "w", encoding="utf-8") as f:
            json.dump(scores, f, ensure_ascii=False, indent=2)
    except Exception as e: print(f"[WARN] scores.json: {e}")
    try:
        with open(SCORES_TXT, "w", encoding="utf-8") as f:
            f.write("T-Rex Rush - Gesture Control Edition\nNEU College of Technology (FIT)\n")
            f.write("=" * 44 + "\n\n")
            f.write(f"{'RANK':<5} {'PLAYER':<14} {'SCORE':>6}   DATE\n" + "-"*44 + "\n")
            for i, s in enumerate(scores):
                label = str(s.get('name', 'FACE')).upper()[:12]
                f.write(f"{i+1:<5} {label:<14} {int(s.get('score', 0)):>06d}   {s.get('date','')}\n")
            f.write(f"\nUpdated: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
    except Exception as e: print(f"[WARN] scores.txt: {e}")

def add_score(avatar_data, score):
    scores = load_leaderboard()
    entry_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    scores.append({
        "id": entry_id,
        "name": "FACE",
        "avatar": avatar_data or "",
        "score": int(score),
        "date": datetime.date.today().strftime("%d/%m/%Y"),
    })
    scores.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
    scores = scores[:10]
    save_leaderboard(scores)
    return scores, entry_id

# ─────────────────────────────────────────────────────────────────────────────
#  GESTURE CONTROLLER  (daemon thread)
# ─────────────────────────────────────────────────────────────────────────────
class GestureController:
    def __init__(self):
        self._lock         = threading.Lock()
        self._gesture      = "none"
        self._preview_rgb  = None
        self._raw_rgb      = None
        self.running       = False
        self.cam_ok        = False
        self._thread       = None

    def start(self):
        if not MEDIAPIPE_AVAILABLE: return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        with self._lock: self.running = False

    def get_gesture(self):
        with self._lock: return self._gesture

    def get_preview_frame(self):
        with self._lock:
            return None if self._preview_rgb is None else self._preview_rgb.copy()

    def get_raw_frame(self):
        with self._lock:
            return None if self._raw_rgb is None else self._raw_rgb.copy()

    def capture_face_avatar(self, size=128):
        """Return a small PNG data URL of the player's face, best effort.
        This is called only after game over, so face detection does not slow
        down the normal webcam recognition loop.
        """
        frame = self.get_raw_frame()
        if frame is None:
            frame = self.get_preview_frame()
        if frame is None or not MEDIAPIPE_AVAILABLE:
            return ""
        try:
            h, w = frame.shape[:2]
            try:
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
                cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
                cascade = cv2.CascadeClassifier(cascade_path)
                faces = cascade.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=4, minSize=(48, 48))
                if len(faces) > 0:
                    x, y, fw, fh = max(faces, key=lambda r: r[2] * r[3])
                    pad = int(max(fw, fh) * 0.38)
                    cx, cy = x + fw // 2, y + fh // 2
                    side = int(max(fw, fh) + pad * 2)
                    x1 = max(0, cx - side // 2)
                    y1 = max(0, cy - side // 2)
                    x2 = min(w, x1 + side)
                    y2 = min(h, y1 + side)
                    x1 = max(0, x2 - side)
                    y1 = max(0, y2 - side)
                else:
                    raise RuntimeError("no face")
            except Exception:
                side = int(min(w, h) * 0.58)
                cx = w // 2
                cy = int(h * 0.36)
                x1 = max(0, cx - side // 2)
                y1 = max(0, cy - side // 2)
                x2 = min(w, x1 + side)
                y2 = min(h, y1 + side)
                x1 = max(0, x2 - side)
                y1 = max(0, y2 - side)

            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                return ""
            crop = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".png", cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
            if not ok:
                return ""
            return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
        except Exception as e:
            print(f"[WARN] capture_face_avatar: {e}")
            return ""

    @staticmethod
    def _classify(lm):
        def dist(a, b):
            return std_math.hypot(a.x - b.x, a.y - b.y)

        index_ext  = lm[8].y  < lm[6].y  - 0.02
        middle_ext = lm[12].y < lm[10].y - 0.02
        ring_ext   = lm[16].y < lm[14].y - 0.02
        pinky_ext  = lm[20].y < lm[18].y - 0.02
        thumb_ext = (
            dist(lm[4], lm[5]) > dist(lm[3], lm[5]) + 0.025 and
            dist(lm[4], lm[0]) > dist(lm[3], lm[0]) + 0.015
        )
        ext = sum([index_ext, middle_ext, ring_ext, pinky_ext])

        if thumb_ext and index_ext and pinky_ext and not middle_ext and not ring_ext:
            return "iloveyou"
        if index_ext and middle_ext and not ring_ext and not pinky_ext:
            return "vtwo"
        if ext >= 3:
            return "open"
        if ext <= 1:
            return "fist"
        return "other"

    def _run(self):
        mp_hands = mp.solutions.hands
        mp_draw  = mp.solutions.drawing_utils
        mp_style = mp.solutions.drawing_styles
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(0)
        if not cap.isOpened():
            print("[GestureController] Cannot open camera.")
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        with self._lock:
            self.running = True
            self.cam_ok = True
        hands = mp_hands.Hands(static_image_mode=False, max_num_hands=1,
                               model_complexity=0,
                               min_detection_confidence=0.70,
                               min_tracking_confidence=0.60)
        while True:
            with self._lock:
                if not self.running: break
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.03)
                continue
            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            results = hands.process(rgb)
            rgb.flags.writeable = True

            g = "none"
            preview = rgb.copy()
            if results.multi_hand_landmarks:
                hand_landmarks = results.multi_hand_landmarks[0]
                g = self._classify(hand_landmarks.landmark)
                mp_draw.draw_landmarks(
                    preview,
                    hand_landmarks,
                    mp_hands.HAND_CONNECTIONS,
                    mp_style.get_default_hand_landmarks_style(),
                    mp_style.get_default_hand_connections_style(),
                )
            with self._lock:
                self._gesture = g
                self._raw_rgb = rgb.copy()
                self._preview_rgb = preview
        cap.release()
        hands.close()
        with self._lock:
            self.running = False
            self.cam_ok = False
            self._raw_rgb = None
            self._preview_rgb = None

gesture_ctrl = GestureController()

# ─────────────────────────────────────────────────────────────────────────────
#  SPRITE HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def load_image(name, sizex=-1, sizey=-1, colorkey=None):
    raw = pygame.image.load(os.path.join('sprites', name))

    # Preserve real PNG transparency when the asset has an alpha channel.
    # Otherwise use normal RGB conversion for best performance.
    if raw.get_alpha() is not None:
        img = raw.convert_alpha()
    else:
        img = raw.convert()

    if colorkey is not None:
        ck = img.get_at((0,0)) if colorkey == -1 else colorkey
        img.set_colorkey(ck, RLEACCEL)
    if sizex != -1 or sizey != -1:
        img = pygame.transform.scale(img, (sizex, sizey))
    return img, img.get_rect()


def remove_border_background(surface):
    """Make only the outer light/gray background transparent.

    This is used for call_out.png. The original image has a light gray/white
    rectangular background. A simple color key is not enough because the
    background may contain many slightly different gray pixels, and removing
    all white pixels would also destroy the white inside the speech bubble.

    The safer approach is flood-fill from the image borders and remove only
    light neutral pixels connected to the outside border. The white inside the
    bubble is protected by the black outline, so it stays visible.
    """
    img = surface.convert_alpha()
    w, h = img.get_size()
    if w <= 0 or h <= 0:
        return img

    def removable(rgb):
        r, g, b = rgb[:3]
        return min(r, g, b) >= 175 and (max(r, g, b) - min(r, g, b)) <= 45

    from collections import deque
    q = deque()
    seen = set()

    for x in range(w):
        for y in (0, h - 1):
            if removable(img.get_at((x, y))):
                q.append((x, y))
                seen.add((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if (x, y) not in seen and removable(img.get_at((x, y))):
                q.append((x, y))
                seen.add((x, y))

    while q:
        x, y = q.popleft()
        r, g, b, a = img.get_at((x, y))
        img.set_at((x, y), (r, g, b, 0))
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen:
                if removable(img.get_at((nx, ny))):
                    seen.add((nx, ny))
                    q.append((nx, ny))

    return img


def load_callout_image(name, sizex=-1, sizey=-1):
    img = pygame.image.load(os.path.join('sprites', name)).convert_alpha()
    img = remove_border_background(img)
    if sizex != -1 or sizey != -1:
        img = pygame.transform.scale(img, (sizex, sizey))
    return img, img.get_rect()

def load_sprite_sheet(sheetname, nx, ny, scalex=-1, scaley=-1, colorkey=None):
    sheet = pygame.image.load(os.path.join('sprites', sheetname)).convert()
    sr    = sheet.get_rect()
    sw, sh = sr.width / nx, sr.height / ny
    sprites = []
    for i in range(ny):
        for j in range(nx):
            rect  = pygame.Rect(j*sw, i*sh, sw, sh)
            image = pygame.Surface(rect.size).convert()
            image.blit(sheet, (0,0), rect)
            if colorkey is not None:
                ck = image.get_at((0,0)) if colorkey == -1 else colorkey
                image.set_colorkey(ck, RLEACCEL)
            if scalex != -1 or scaley != -1:
                image = pygame.transform.scale(image, (scalex, scaley))
            sprites.append(image)
    return sprites, sprites[0].get_rect()


def normalize_cactus_outline(image):
    """Make all cactus sprites use a consistent white outline."""
    base = image.copy()
    ck = base.get_colorkey()
    ck_rgb = ck[:3] if isinstance(ck, tuple) else None
    width_i, height_i = base.get_size()

    def is_transparent(rgb):
        return ck_rgb is not None and rgb == ck_rgb

    def is_near_white(rgb):
        return rgb[0] >= 210 and rgb[1] >= 210 and rgb[2] >= 210

    # First, clean any old inconsistent light border pixels.
    color_counts = {}
    for x in range(width_i):
        for y in range(height_i):
            rgb = base.get_at((x, y))[:3]
            if is_transparent(rgb) or is_near_white(rgb):
                continue
            color_counts[rgb] = color_counts.get(rgb, 0) + 1
    dominant = max(color_counts, key=color_counts.get) if color_counts else (84, 168, 65)

    for x in range(width_i):
        for y in range(height_i):
            rgb = base.get_at((x, y))[:3]
            if is_transparent(rgb):
                continue
            if is_near_white(rgb):
                base.set_at((x, y), dominant)

    result = base.copy()
    outline_color = (245, 245, 245)

    for x in range(width_i):
        for y in range(height_i):
            rgb = base.get_at((x, y))[:3]
            if is_transparent(rgb):
                continue

            # If this solid cactus pixel touches transparency, paint a 1px white outline
            # into neighboring transparent pixels.
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < width_i and 0 <= ny < height_i:
                    neighbor_rgb = base.get_at((nx, ny))[:3]
                    if is_transparent(neighbor_rgb):
                        result.set_at((nx, ny), outline_color)

    if ck is not None:
        result.set_colorkey(ck, RLEACCEL)
    return result


def normalize_cactus_images(images):
    return [normalize_cactus_outline(img) for img in images]


_cactus_sheet_cache = {}

def load_normalized_cactus_sheet(sheetname, nx, ny, sizex=-1, sizey=-1):
    """Load and outline cactus sprites once, then reuse them.
    Without this cache, every newly spawned cactus would loop over all pixels to
    rebuild the outline, causing small but visible frame hitches.
    """
    key = (sheetname, nx, ny, sizex, sizey)
    cached = _cactus_sheet_cache.get(key)
    if cached is None:
        images, rect = load_sprite_sheet(sheetname, nx, ny, sizex, sizey, -1)
        images = normalize_cactus_images(images)
        _cactus_sheet_cache[key] = (images, rect.copy())
        return images, rect.copy()
    images, rect = cached
    return images, rect.copy()

def disp_gameOver_msg(retbutton_image, gameover_image):
    rb = retbutton_image.get_rect(); rb.centerx = width/2; rb.top = height*0.52
    go = gameover_image.get_rect();  go.centerx = width/2; go.centery = height*0.35
    screen.blit(retbutton_image, rb); screen.blit(gameover_image, go)

def extractDigits(number):
    if number > -1:
        digits = []
        while number / 10 != 0:
            digits.append(number % 10); number = int(number/10)
        digits.append(number % 10)
        for _ in range(len(digits), 5): digits.append(0)
        digits.reverse()
        return digits

# ─────────────────────────────────────────────────────────────────────────────
#  GAME CLASSES  — all sprite sizes multiplied by S
# ─────────────────────────────────────────────────────────────────────────────
class Dino:
    def __init__(self, sizex=-1, sizey=-1):
        # Original dino frame: 88x95 → scaled
        self.images,  self.rect  = load_sprite_sheet('dino.png',         5, 1, sizex, sizey, -1)
        # ducking width kept proportional; original duck sheet gave 59 wide
        duck_w = int(59 * S / (88/sizex)) if sizex != -1 else 59*S//88*sizex
        # simpler: just scale duck sheet to (duck_w, sizey)
        duck_w = int(sizex * 59 / 88) if sizex != -1 else -1
        self.images1, self.rect1 = load_sprite_sheet('dino_ducking.png', 2, 1, duck_w, sizey, -1)
        self.rect.bottom    = int(0.98 * height)
        self.rect.left      = width // 15
        self.image          = self.images[0]
        self.index          = 0
        self.counter        = 0
        self.score          = 0
        self.isJumping      = False
        self.isDead         = False
        self.isDucking      = False
        self.isBlinking     = False
        self.movement       = [0, 0]
        self.jumpSpeed      = 11.5 * S    # double jump height
        self.stand_pos_width = self.rect.width
        self.duck_pos_width  = self.rect1.width

    def draw(self): screen.blit(self.image, self.rect)

    def checkbounds(self):
        if self.rect.bottom > int(0.98 * height):
            self.rect.bottom = int(0.98 * height)
            self.isJumping   = False

    def update(self):
        if self.isJumping: self.movement[1] += gravity
        if self.isJumping: self.index = 0
        elif self.isBlinking:
            if self.index == 0:
                if self.counter % 400 == 399: self.index = 1
            else:
                if self.counter % 20  == 19:  self.index = 0
        elif self.isDucking:
            if self.counter % 5 == 0: self.index = (self.index+1) % 2
        else:
            if self.counter % 5 == 0: self.index = (self.index+1) % 2 + 2
        if self.isDead: self.index = 4
        if not self.isDucking:
            self.image = self.images[self.index]; self.rect.width = self.stand_pos_width
        else:
            self.image = self.images1[self.index%2]; self.rect.width = self.duck_pos_width
        self.rect = self.rect.move(self.movement)
        self.checkbounds()
        if not self.isDead and self.counter % 7 == 6 and not self.isBlinking:
            self.score += 1
            if self.score % 100 == 0 and self.score != 0:
                if pygame.mixer.get_init(): checkPoint_sound.play()
        self.counter += 1


class Cactus(pygame.sprite.Sprite):
    def __init__(self, speed=5, sizex=-1, sizey=-1):
        pygame.sprite.Sprite.__init__(self, self.containers)
        self.images, self.rect = load_normalized_cactus_sheet('cacti-small.png', 3, 1, sizex, sizey)
        self.rect.bottom = int(0.98 * height)
        self.rect.left   = width + self.rect.width
        self.image       = self.images[random.randrange(0, 3)]
        self.movement    = [-1 * speed, 0]

    def draw(self): screen.blit(self.image, self.rect)

    def update(self):
        self.rect = self.rect.move(self.movement)
        if self.rect.right < 0: self.kill()


class CactusBig(pygame.sprite.Sprite):
    """Large cactus — appears at higher difficulties."""
    def __init__(self, speed=5, sizex=-1, sizey=-1):
        pygame.sprite.Sprite.__init__(self, self.containers)
        self.images, self.rect = load_normalized_cactus_sheet('cacti-big.png', 3, 1, sizex, sizey)
        self.rect.bottom = int(0.98 * height)
        self.rect.left   = width + self.rect.width
        self.image       = self.images[random.randrange(0, 3)]
        self.movement    = [-1 * speed, 0]

    def draw(self): screen.blit(self.image, self.rect)

    def update(self):
        self.rect = self.rect.move(self.movement)
        if self.rect.right < 0: self.kill()


class Ptera(pygame.sprite.Sprite):
    # Height slots — LOW flies at cactus-top level (must duck), HIGH is safe to duck under
    HEIGHT_LOW  = 0   # centery ≈ 82% height  → player must duck
    HEIGHT_HIGH = 1   # centery ≈ 60% height  → player must jump OR duck

    def __init__(self, speed=5, sizex=-1, sizey=-1, height_slot=None, can_shoot=False):
        pygame.sprite.Sprite.__init__(self, self.containers)
        self.images, self.rect = load_sprite_sheet('ptera.png', 2, 1, sizex, sizey, -1)
        # Three possible heights; stored so wave validator can inspect them
        self.ptera_heights = [height*0.82, height*0.75, height*0.60]
        if height_slot is None:
            height_slot = random.randrange(0, 3)
        self.height_slot  = height_slot
        self.rect.centery = self.ptera_heights[height_slot]
        self.rect.left    = width + self.rect.width
        self.image        = self.images[0]
        self.movement     = [-1 * speed, 0]
        self.index = self.counter = 0
        # Shooting
        self.can_shoot     = can_shoot
        self.shoot_timer   = random.randint(60, 130)  # frames until first shot
        self.bullets_fired = 0
        self.max_bullets   = random.randint(1, 3)     # total shots this ptera fires

    def draw(self): screen.blit(self.image, self.rect)

    def update(self):
        if self.counter % 10 == 0: self.index = (self.index+1) % 2
        self.image = self.images[self.index]
        self.rect  = self.rect.move(self.movement)
        self.counter += 1
        # Shooting logic — only when visible on screen
        if self.can_shoot and self.rect.right > 0 and self.rect.left < width:
            self.shoot_timer -= 1
            if self.shoot_timer <= 0 and self.bullets_fired < self.max_bullets:
                # Spawn bullet at ptera's left edge, flying left
                Bullet(self.rect.left, self.rect.centery, self.movement[0] - 4)
                self.bullets_fired += 1
                self.shoot_timer = random.randint(45, 90)
        if self.rect.right < 0: self.kill()


class Bullet(pygame.sprite.Sprite):
    """A horizontal projectile fired by a ptera."""
    R = max(4, 4*S//2)   # radius

    def __init__(self, x, y, speed):
        pygame.sprite.Sprite.__init__(self, self.containers)
        # Draw bullet as a small filled circle on a surface with colorkey
        d = self.R * 2 + 2
        self.image = pygame.Surface((d, d)).convert()
        self.image.fill(background_col)
        self.image.set_colorkey(background_col)
        pygame.draw.circle(self.image, (180, 40, 40), (self.R+1, self.R+1), self.R)
        self.rect     = self.image.get_rect()
        self.rect.centerx = x
        self.rect.centery = int(y)
        self.speed    = speed   # negative = moves left

    def update(self):
        self.rect.left += self.speed
        if self.rect.right < 0: self.kill()


class Ground:
    def __init__(self, speed=-5):
        # Scale ground image width/height
        self.image,  self.rect  = load_image('ground.png', 1203*S//1, 19*S, -1)
        self.image1, self.rect1 = load_image('ground.png', 1203*S//1, 19*S, -1)
        self.rect.bottom  = height
        self.rect1.bottom = height
        self.rect1.left   = self.rect.right
        self.speed        = speed

    def draw(self):
        screen.blit(self.image,  self.rect)
        screen.blit(self.image1, self.rect1)

    def update(self):
        self.rect.left  += self.speed
        self.rect1.left += self.speed
        if self.rect.right  < 0: self.rect.left  = self.rect1.right
        if self.rect1.right < 0: self.rect1.left = self.rect.right


class Cloud(pygame.sprite.Sprite):
    def __init__(self, x, y):
        pygame.sprite.Sprite.__init__(self, self.containers)
        self.image, self.rect = load_image('cloud.png', int(90*S*30/42), 30*S, -1)
        self.rect.left = x; self.rect.top = y
        self.movement  = [-1, 0]

    def draw(self): screen.blit(self.image, self.rect)

    def update(self):
        self.rect = self.rect.move(self.movement)
        if self.rect.right < 0: self.kill()


class Scoreboard:
    def __init__(self, x=-1, y=-1):
        dw = 11*S; dh = int(11*S * 6/5)
        self.tempimages, self.temprect = load_sprite_sheet('numbers.png', 12, 1, dw, dh, -1)
        self.image = pygame.Surface((dw*5 + dw, dh), pygame.SRCALPHA).convert_alpha()
        self.rect  = self.image.get_rect()
        self.rect.left = (width * 0.89) if x == -1 else x
        self.rect.top  = (height * 0.1) if y == -1 else y

    def draw(self):
        theme = get_current_theme_colors()
        pad_x = max(6, 5*S)
        pad_y = max(3, 3*S)
        panel_rect = self.rect.inflate(pad_x * 2, pad_y * 2)
        draw_alpha_round_rect(screen, panel_rect, theme["score_panel"], radius=max(4, 4*S))
        draw_alpha_round_rect(screen, panel_rect, theme["score_border"], radius=max(4, 4*S), width=1)
        screen.blit(self.image, self.rect)

    def update(self, score):
        digits = extractDigits(score)
        self.image.fill((0, 0, 0, 0))
        for d in digits:
            self.image.blit(self.tempimages[d], self.temprect)
            self.temprect.left += self.temprect.width
        self.temprect.left = 0

# ─────────────────────────────────────────────────────────────────────────────
#  UI FONTS  (scaled)
# ─────────────────────────────────────────────────────────────────────────────
pygame.font.init()
_fnt_xs  = pygame.font.SysFont("monospace", max(8,  8*S//2), bold=True)
_fnt_sm  = pygame.font.SysFont("monospace", max(9,  9*S//2), bold=True)
_fnt_md  = pygame.font.SysFont("monospace", max(11,11*S//2), bold=True)
_fnt_lg  = pygame.font.SysFont("monospace", max(13,13*S//2), bold=True)
_fnt_inp = pygame.font.SysFont("monospace", max(14,14*S//2), bold=True)

# Fonts used for panels drawn outside the game canvas, in real screen pixels.
_overlay_xs = pygame.font.SysFont("monospace", 18, bold=True)
_overlay_sm = pygame.font.SysFont("monospace", 22, bold=True)
_overlay_md = pygame.font.SysFont("monospace", 28, bold=True)
_overlay_lg = pygame.font.SysFont("monospace", 32, bold=True)
_overlay_row = pygame.font.SysFont("monospace", 24, bold=True)

def txt(text, font, color, bg=None):
    return font.render(text, True, color) if bg is None else font.render(text, True, color, bg)


def get_game_rect_on_display():
    display_w, display_h = display.get_size()
    if display_w <= 0 or display_h <= 0:
        return pygame.Rect(0, 0, width, height)

    # Preserve the original 4:1 game aspect ratio on any monitor.
    game_w = display_w
    game_h = max(1, int(game_w * height / width))

    max_game_h = max(1, int(display_h * 0.50))
    if game_h > max_game_h:
        game_h = max_game_h
        game_w = max(1, int(game_h * width / height))

    game_x = max(0, (display_w - game_w) // 2)
    desired_bottom = int(display_h * 0.88)
    game_y = desired_bottom - game_h
    game_y = max(0, min(game_y, max(0, display_h - game_h)))

    return pygame.Rect(game_x, game_y, game_w, game_h)


def present_frame(player_dino=None, top_scores=None):
    draw_game_background(display)
    game_rect = get_game_rect_on_display()
    scaled_game = pygame.transform.scale(screen, (game_rect.width, game_rect.height))
    display.blit(scaled_game, game_rect)

    if top_scores is not None:
        draw_top5_scores_panel(display, top_scores, game_rect)
    if player_dino is not None:
        draw_webcam_panel(display, player_dino, game_rect)

    pygame.display.flip()

# ─────────────────────────────────────────────────────────────────────────────
#  GESTURE HUD
# ─────────────────────────────────────────────────────────────────────────────
def draw_gesture_hud():
    # Intentionally hidden during gameplay.
    # The previous version drew a small gesture label, for example "FIST = IDLE",
    # and a tiny camera-status circle near the score area. These were removed to
    # keep the in-game screen cleaner and less distracting.
    return

# ─────────────────────────────────────────────────────────────────────────────
#  SPEED INDICATOR  (right side, shows current difficulty)
# ─────────────────────────────────────────────────────────────────────────────
def draw_speed_indicator(score):
    _, speed, *_ = get_difficulty(score)
    level = min(10, sum(1 for row in DIFF_TABLE if score >= row[0]))
    bar_w = int((width * 0.12) * level / len(DIFF_TABLE))
    bx = width - int(width * 0.15); by = height - 12*S//2
    bw = int(width * 0.12); bh = 6*S//2
    pygame.draw.rect(screen, panel_col, (bx, by, bw, bh))
    col = green_col if level <= 3 else (accent_col if level <= 6 else red_col)
    pygame.draw.rect(screen, col, (bx, by, bar_w, bh))
    pygame.draw.rect(screen, dark_col, (bx, by, bw, bh), 1)
    lbl = txt(f"LVL {level}", _fnt_xs, dark_col, background_col)
    screen.blit(lbl, (bx - lbl.get_width() - 4, by))


def get_dino_action(player_dino):
    if player_dino.isDead:
        return "DEAD", red_col
    if player_dino.isJumping:
        return "JUMP", accent_col
    if player_dino.isDucking:
        return "DUCK", green_col
    return "RUN", dark_col


_avatar_surface_cache = {}


def get_avatar_surface(entry, size):
    avatar = entry.get("avatar") or ""
    cache_key = (avatar[:64], len(avatar), size)
    if avatar and cache_key in _avatar_surface_cache:
        return _avatar_surface_cache[cache_key]
    surf = None
    if avatar.startswith("data:image") and "," in avatar:
        try:
            raw = base64.b64decode(avatar.split(",", 1)[1])
            surf = pygame.image.load(io.BytesIO(raw)).convert()
            surf = pygame.transform.smoothscale(surf, (size, size)).convert()
        except Exception:
            surf = None
    if surf is None:
        surf = pygame.Surface((size, size)).convert()
        surf.fill((230, 218, 190))
        pygame.draw.rect(surf, (150, 105, 62), (0, 0, size, size), 2, border_radius=max(6, size // 8))
        icon = _overlay_xs.render("FACE", True, (90, 66, 45))
        surf.blit(icon, (size // 2 - icon.get_width() // 2, size // 2 - icon.get_height() // 2))
    _avatar_surface_cache[cache_key] = surf
    if len(_avatar_surface_cache) > 40:
        _avatar_surface_cache.clear()
    return surf


def get_webcam_panel_dimensions(target_w, top_space_h):
    panel_w = min(max(420, int(target_w * 0.34)), max(300, target_w // 3))
    panel_h = min(max(260, top_space_h - 32), 420)
    panel_h = min(panel_h, max(180, top_space_h - 24))
    return int(panel_w), int(panel_h)


def draw_top5_scores_panel(target, top_scores, game_rect):
    target_w, target_h = target.get_size()
    top_space_h = game_rect.top
    if top_space_h < 170:
        return

    outer_margin = max(16, int(target_w * 0.012))
    gap = max(16, int(target_w * 0.012))
    webcam_panel_w, _ = get_webcam_panel_dimensions(target_w, top_space_h)
    available_w = target_w - outer_margin * 2 - webcam_panel_w - gap
    panel_w = max(320, min(980, available_w))
    panel_w = min(panel_w, max(320, target_w - outer_margin * 2))
    panel_h = min(max(230, top_space_h - 32), 360)
    panel_x = outer_margin
    panel_y = max(12, (top_space_h - panel_h) // 2)

    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    pygame.draw.rect(panel, (0, 0, 0, 60), (5, 9, panel_w - 10, panel_h - 10), border_radius=28)
    pygame.draw.rect(panel, (250, 240, 216, 242), (0, 0, panel_w, panel_h), border_radius=26)
    pygame.draw.rect(panel, (144, 92, 44, 255), (0, 0, panel_w, panel_h), 3, border_radius=26)
    pygame.draw.rect(panel, (97, 65, 44, 255), (0, 0, panel_w, 62), border_radius=26)
    pygame.draw.rect(panel, (97, 65, 44, 255), (0, 31, panel_w, 31))
    title = _overlay_lg.render("TOP 5 FACES", True, (255, 248, 232))
    panel.blit(title, (24, 13))

    if not top_scores:
        empty = _overlay_md.render("No scores yet", True, (95, 78, 66))
        panel.blit(empty, (24, 92))
    else:
        header_y = 72
        hdr_col = (118, 82, 50)
        panel.blit(_overlay_xs.render("RANK", True, hdr_col), (26, header_y))
        panel.blit(_overlay_xs.render("PLAYER", True, hdr_col), (98, header_y))
        score_header = _overlay_xs.render("SCORE", True, hdr_col)
        panel.blit(score_header, (panel_w - score_header.get_width() - 28, header_y))
        row_y = header_y + 30
        row_h = max(34, (panel_h - row_y - 16) // 5)
        avatar_size = max(28, min(54, row_h - 8))
        medal_cols = [gold_col, silver_col, bronze_col, (146, 123, 96), (146, 123, 96)]
        for i, entry in enumerate(top_scores[:5]):
            row_rect = pygame.Rect(16, row_y - 4, panel_w - 32, row_h)
            bg_col = (255, 252, 240, 178) if i % 2 == 0 else (244, 232, 204, 148)
            pygame.draw.rect(panel, bg_col, row_rect, border_radius=14)
            badge_r = min(18, row_h // 2 - 2)
            badge_cx = 45
            badge_cy = row_y + row_h // 2 - 2
            pygame.draw.circle(panel, medal_cols[i], (badge_cx, badge_cy), badge_r)
            rank_s = _overlay_xs.render(str(i + 1), True, (30, 26, 20))
            panel.blit(rank_s, (badge_cx - rank_s.get_width() // 2, badge_cy - rank_s.get_height() // 2))
            avatar = get_avatar_surface(entry, avatar_size)
            av_x = 92
            av_y = row_y + (row_h - avatar_size) // 2 - 2
            panel.blit(avatar, (av_x, av_y))
            pygame.draw.rect(panel, (122, 84, 48), (av_x, av_y, avatar_size, avatar_size), 2, border_radius=10)
            date = str(entry.get("date", ""))[:10]
            date_s = _overlay_xs.render(date, True, (105, 85, 65))
            score = int(entry.get("score", 0))
            score_s = _overlay_row.render(f"{score:05d}", True, (24, 95, 180))
            panel.blit(score_s, (panel_w - score_s.get_width() - 28, row_y + row_h // 2 - score_s.get_height() // 2 - 3))
            panel.blit(date_s, (av_x + avatar_size + 16, row_y + row_h // 2 - date_s.get_height() // 2 - 2))
            row_y += row_h
    target.blit(panel, (panel_x, panel_y))


def draw_webcam_panel(target, player_dino, game_rect):
    target_w, target_h = target.get_size()
    top_space_h = game_rect.top
    if top_space_h < 170:
        return

    outer_margin = max(16, int(target_w * 0.012))
    panel_w, panel_h = get_webcam_panel_dimensions(target_w, top_space_h)
    panel_x = target_w - panel_w - outer_margin
    panel_y = max(12, (top_space_h - panel_h) // 2)

    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    pygame.draw.rect(panel, (0, 0, 0, 60), (5, 9, panel_w - 10, panel_h - 10), border_radius=24)
    pygame.draw.rect(panel, (248, 250, 252, 244), (0, 0, panel_w, panel_h), border_radius=22)
    pygame.draw.rect(panel, (76, 92, 115, 255), (0, 0, panel_w, panel_h), 2, border_radius=22)
    title = _overlay_sm.render("WEBCAM", True, dark_col)
    panel.blit(title, (18, 14))
    gesture_name = {
        "iloveyou": "I LOVE YOU",
        "open": "OPEN PALM",
        "vtwo": "V-SIGN",
        "fist": "FIST",
        "none": "NO HAND",
        "other": "OTHER",
    }.get(gesture_ctrl.get_gesture(), "UNKNOWN")
    gesture_s = _overlay_xs.render(f"GESTURE: {gesture_name}", True, (72, 72, 72))
    panel.blit(gesture_s, (panel_w - gesture_s.get_width() - 18, 18))
    action, action_col = get_dino_action(player_dino)
    action_s = _overlay_md.render(f"ACTION: {action}", True, action_col)

    frame = gesture_ctrl.get_preview_frame()
    frame_aspect = 4 / 3
    if frame is not None:
        try:
            frame_aspect = frame.shape[1] / max(1, frame.shape[0])
        except Exception:
            frame_aspect = 4 / 3
    info_h = action_s.get_height() + 22
    area_x, area_y = 16, 54
    area_w = panel_w - 32
    area_h = max(120, panel_h - area_y - info_h - 10)
    if area_w / area_h > frame_aspect:
        cam_h = area_h
        cam_w = int(cam_h * frame_aspect)
    else:
        cam_w = area_w
        cam_h = int(cam_w / frame_aspect)
    cam_rect = pygame.Rect(area_x + (area_w - cam_w) // 2, area_y + (area_h - cam_h) // 2, cam_w, cam_h)
    pygame.draw.rect(panel, (231, 237, 245, 255), cam_rect.inflate(8, 8), border_radius=14)

    if frame is not None:
        try:
            frame_surface = pygame.image.frombuffer(frame.tobytes(), (frame.shape[1], frame.shape[0]), "RGB")
            frame_surface = pygame.transform.scale(frame_surface, (cam_rect.width, cam_rect.height))
            panel.blit(frame_surface, cam_rect)
            pygame.draw.rect(panel, (132, 148, 170, 255), cam_rect, 2, border_radius=12)
        except Exception:
            note = _overlay_xs.render("Preview error", True, red_col)
            panel.blit(note, (cam_rect.x + 12, cam_rect.y + cam_rect.height // 2 - 8))
    else:
        pygame.draw.rect(panel, (235, 239, 244, 255), cam_rect, border_radius=12)
        note = _overlay_xs.render("Camera preview unavailable", True, (120, 120, 120))
        panel.blit(note, (cam_rect.x + 12, cam_rect.y + cam_rect.height // 2 - 8))
    panel.blit(action_s, (18, panel_h - action_s.get_height() - 16))
    target.blit(panel, (panel_x, panel_y))

# ─────────────────────────────────────────────────────────────────────────────
#  NAME ENTRY SCREEN
# ─────────────────────────────────────────────────────────────────────────────
def name_entry_screen(final_score):
    name          = ""
    deadline      = time.time() + 15
    hold_start    = None
    HOLD_REQUIRED = 0.6
    gesture_ready = time.time() + 1.5
    cursor_on     = True
    cursor_t      = 0.0

    while True:
        dt = clock.tick(FPS) / 1000.0
        cursor_t += dt
        if cursor_t >= 0.5: cursor_on = not cursor_on; cursor_t = 0.0
        remaining = max(0.0, deadline - time.time())

        for event in pygame.event.get():
            if event.type == pygame.QUIT: pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE):
                    return name
                elif event.key == pygame.K_BACKSPACE:
                    name = name[:-1]
                else:
                    ch = event.unicode
                    if ch.isprintable() and len(name) < 12: name += ch.upper()

        if time.time() >= gesture_ready:
            g = gesture_ctrl.get_gesture()
            if g == "open":
                if hold_start is None: hold_start = time.time()
                elif time.time() - hold_start >= HOLD_REQUIRED: return name
            else: hold_start = None

        if remaining <= 0: return name

        overlay = pygame.Surface(scr_size); overlay.set_alpha(200)
        overlay.fill((250, 251, 252)); screen.blit(overlay, (0,0))

        bw = min(width - 40, 400*S//2); bh = 110*S//2
        bx = (width - bw) // 2; by = (height - bh) // 2
        pygame.draw.rect(screen, panel_col, (bx, by, bw, bh))
        pygame.draw.rect(screen, dark_col,  (bx, by, bw, bh), 2)

        heading = txt(f"SCORE: {final_score:05d}", _fnt_lg, dark_col)
        screen.blit(heading, (bx + (bw - heading.get_width())//2, by + 8))
        sub = txt("ENTER YOUR NAME:", _fnt_sm, dark_col)
        screen.blit(sub, (bx + 10, by + 28))

        fx, fy, fw, fh = bx+10, by+42, bw-20, 22*S//2
        pygame.draw.rect(screen, white,    (fx, fy, fw, fh))
        pygame.draw.rect(screen, dark_col, (fx, fy, fw, fh), 1)
        disp = name + ("|" if cursor_on else " ")
        inp_s = txt(disp, _fnt_inp, dark_col)
        screen.blit(inp_s, (fx+4, fy+3))

        if hold_start and time.time() >= gesture_ready:
            progress = min(1.0, (time.time()-hold_start)/HOLD_REQUIRED)
            bar_w = int((bw-20)*progress)
            pygame.draw.rect(screen, accent_col, (bx+10, by+70*S//2, bar_w, 6*S//2))
            pygame.draw.rect(screen, dark_col,   (bx+10, by+70*S//2, bw-20, 6*S//2), 1)
            lbl = txt("Hold open palm to confirm...", _fnt_xs, accent_col)
            screen.blit(lbl, (bx+10, by+80*S//2))
        else:
            tip1 = txt("Keyboard: type + ENTER to confirm", _fnt_xs, (110,110,110))
            tip2 = txt(f"Gesture: hold open palm  ({remaining:.0f}s auto)", _fnt_xs, (110,110,110))
            screen.blit(tip1, (bx+10, by+70*S//2))
            screen.blit(tip2, (bx+10, by+82*S//2))

        g  = gesture_ctrl.get_gesture()
        gc = {"open":green_col,"vtwo":accent_col,"fist":dark_col}.get(g,(150,150,150))
        gn = {"open":"OPEN PALM","vtwo":"V-SIGN","fist":"FIST","none":"NO HAND"}.get(g, g.upper())
        gs = txt(gn, _fnt_xs, gc)
        screen.blit(gs, (bx+bw-gs.get_width()-6, by+8))
        present_frame()

# ─────────────────────────────────────────────────────────────────────────────
#  LEADERBOARD SCREEN
# ─────────────────────────────────────────────────────────────────────────────
def leaderboard_screen(highlight_id=None, highlight_score=None):
    scores = load_leaderboard()
    deadline = time.time() + 10
    gesture_cd = time.time() + 1.2

    target_w, target_h = display.get_size()

    title_font = pygame.font.SysFont("monospace", max(40, int(target_h * 0.062)), bold=True)
    subtitle_font = pygame.font.SysFont("monospace", max(18, int(target_h * 0.024)), bold=True)
    rank_font = pygame.font.SysFont("monospace", max(28, int(target_h * 0.040)), bold=True)
    score_font = pygame.font.SysFont("monospace", max(32, int(target_h * 0.044)), bold=True)
    date_font = pygame.font.SysFont("monospace", max(15, int(target_h * 0.020)), bold=True)
    tag_font = pygame.font.SysFont("monospace", max(15, int(target_h * 0.020)), bold=True)
    footer_font = pygame.font.SysFont("monospace", max(18, int(target_h * 0.023)), bold=True)

    panel_w = int(target_w * 0.94)
    panel_h = int(target_h * 0.88)
    panel_x = (target_w - panel_w) // 2
    panel_y = (target_h - panel_h) // 2

    header_h = max(96, int(panel_h * 0.16))
    footer_h = max(54, int(panel_h * 0.085))
    content_pad_x = max(30, int(panel_w * 0.035))
    content_pad_y = max(18, int(panel_h * 0.022))
    content_x = content_pad_x
    content_y = header_h + content_pad_y
    content_w = panel_w - content_pad_x * 2
    content_h = panel_h - header_h - footer_h - content_pad_y * 2

    cols = 2 if target_w >= 1100 else 1
    rows = 5 if cols == 2 else 10
    gap_x = max(20, int(panel_w * 0.022))
    gap_y = max(10, int(panel_h * 0.014))
    card_w = (content_w - gap_x * (cols - 1)) // cols
    card_h = max(58, (content_h - gap_y * (rows - 1)) // rows)
    avatar_size = max(64, min(int(card_h * 0.90), int(card_w * 0.24), 138))

    def blit_shadow(surface, font, text_value, pos, color, shadow=(7, 12, 22), offset=3):
        x, y = pos
        surface.blit(font.render(text_value, True, shadow), (x + offset, y + offset))
        surface.blit(font.render(text_value, True, color), (x, y))

    # Pre-render the whole leaderboard screen once.
    # During the waiting loop only the footer countdown is redrawn.
    static_screen = pygame.Surface((target_w, target_h)).convert()
    bg = get_scaled_background((target_w, target_h))
    if bg is not None:
        static_screen.blit(bg, (0, 0))
    else:
        static_screen.fill((28, 34, 46))

    shade = pygame.Surface((target_w, target_h), pygame.SRCALPHA)
    shade.fill((5, 10, 20, 135))
    static_screen.blit(shade, (0, 0))

    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)

    # Large game-like board
    pygame.draw.rect(panel, (0, 0, 0, 95), (10, 14, panel_w - 20, panel_h - 20), border_radius=38)
    pygame.draw.rect(panel, (17, 25, 42, 246), (0, 0, panel_w, panel_h), border_radius=34)
    pygame.draw.rect(panel, (255, 209, 90, 255), (0, 0, panel_w, panel_h), 5, border_radius=34)
    pygame.draw.rect(panel, (38, 57, 91, 250), (0, 0, panel_w, header_h), border_radius=34)
    pygame.draw.rect(panel, (38, 57, 91, 250), (0, header_h // 2, panel_w, header_h // 2))

    # Arcade decorative pixels and divider lines
    for k in range(24):
        px = 26 + (k * 97) % max(1, panel_w - 52)
        py = 18 + (k * 31) % max(1, header_h - 28)
        col = (255, 219, 111, 105) if k % 3 == 0 else (115, 190, 255, 82)
        pygame.draw.rect(panel, col, (px, py, 5, 5), border_radius=1)
    pygame.draw.line(panel, (255, 209, 90, 190), (24, header_h - 2), (panel_w - 24, header_h - 2), 3)
    pygame.draw.line(panel, (90, 140, 210, 135), (30, header_h + 5), (panel_w - 30, header_h + 5), 2)

    title_text = "TOP 10 FACES"
    title_w = title_font.size(title_text)[0]
    blit_shadow(panel, title_font, title_text, (panel_w // 2 - title_w // 2, max(12, header_h // 2 - title_font.get_height() + 2)), (255, 244, 205))
    subtitle = subtitle_font.render("Face leaderboard  |  Gesture Runner", True, (181, 220, 255))
    panel.blit(subtitle, (panel_w // 2 - subtitle.get_width() // 2, header_h // 2 + 18))

    footer_rect = pygame.Rect(0, panel_h - footer_h, panel_w, footer_h)
    pygame.draw.rect(panel, (33, 48, 76, 250), footer_rect, border_radius=34)
    pygame.draw.rect(panel, (33, 48, 76, 250), (0, panel_h - footer_h, panel_w, footer_h // 2))
    pygame.draw.line(panel, (255, 209, 90, 165), (28, panel_h - footer_h), (panel_w - 28, panel_h - footer_h), 2)

    if not scores:
        empty = score_font.render("No scores yet", True, (245, 247, 250))
        panel.blit(empty, (panel_w // 2 - empty.get_width() // 2, panel_h // 2 - empty.get_height() // 2))
    else:
        rank_styles = [
            {
                "card": (255, 238, 184, 245),
                "border": (255, 214, 78, 255),
                "badge": gold_col,
                "score": (126, 72, 0),
                "label": "CHAMPION",
            },
            {
                "card": (235, 241, 250, 238),
                "border": (190, 202, 213, 255),
                "badge": silver_col,
                "score": (54, 79, 105),
                "label": "RUNNER UP",
            },
            {
                "card": (248, 226, 206, 236),
                "border": (205, 135, 82, 255),
                "badge": bronze_col,
                "score": (111, 63, 35),
                "label": "TOP 3",
            },
        ]

        for i, entry in enumerate(scores[:10]):
            col = i // rows if cols == 2 else 0
            row = i % rows if cols == 2 else i
            x = content_x + col * (card_w + gap_x)
            y = content_y + row * (card_h + gap_y)

            is_new = ((highlight_id and entry.get("id") == highlight_id) or
                      (highlight_score and int(entry.get("score", 0)) == int(highlight_score) and i == 0))
            top3 = i < 3
            style = rank_styles[i] if top3 else None

            if top3:
                glow = pygame.Surface((card_w + 14, card_h + 14), pygame.SRCALPHA)
                glow_color = style["border"][:3] + (78,)
                pygame.draw.rect(glow, glow_color, (0, 0, card_w + 14, card_h + 14), border_radius=24)
                panel.blit(glow, (x - 7, y - 7))
                card_col = style["card"]
                border_col = style["border"]
            else:
                card_col = (229, 238, 252, 218) if i % 2 == 0 else (216, 229, 246, 205)
                border_col = (104, 131, 168, 235)

            if is_new:
                card_col = (255, 246, 207, 250)
                border_col = (255, 225, 92, 255)

            pygame.draw.rect(panel, card_col, (x, y, card_w, card_h), border_radius=20)
            pygame.draw.rect(panel, border_col, (x, y, card_w, card_h), 3 if top3 or is_new else 2, border_radius=20)

            # subtle inner highlight
            pygame.draw.line(panel, (255, 255, 255, 120), (x + 16, y + 7), (x + card_w - 16, y + 7), 1)

            badge_r = max(18, min(31, card_h // 3))
            badge_x = x + max(28, int(card_w * 0.055))
            badge_y = y + card_h // 2
            badge_col = style["badge"] if top3 else (82, 104, 135)
            pygame.draw.circle(panel, (0, 0, 0, 45), (badge_x + 2, badge_y + 3), badge_r)
            pygame.draw.circle(panel, badge_col, (badge_x, badge_y), badge_r)
            pygame.draw.circle(panel, (255, 255, 255, 120), (badge_x - badge_r // 3, badge_y - badge_r // 3), max(3, badge_r // 5))

            rank_s = rank_font.render(str(i + 1), True, (21, 24, 30))
            panel.blit(rank_s, (badge_x - rank_s.get_width() // 2, badge_y - rank_s.get_height() // 2))

            avatar = get_avatar_surface(entry, avatar_size)
            av_x = badge_x + badge_r + max(20, int(card_w * 0.035))
            av_y = y + (card_h - avatar_size) // 2
            panel.blit(avatar, (av_x, av_y))
            pygame.draw.rect(panel, (255, 255, 255), (av_x, av_y, avatar_size, avatar_size), 4 if top3 else 3, border_radius=max(12, avatar_size // 7))
            pygame.draw.rect(panel, border_col[:3], (av_x, av_y, avatar_size, avatar_size), 2, border_radius=max(12, avatar_size // 7))

            if i == 0:
                # simple pixel crown above avatar
                crown_y = max(y + 5, av_y - max(13, avatar_size // 8))
                crown_x = av_x + avatar_size // 2 - max(22, avatar_size // 5)
                crown_w = max(44, avatar_size // 2)
                crown_h = max(16, avatar_size // 7)
                points = [
                    (crown_x, crown_y + crown_h),
                    (crown_x + crown_w // 5, crown_y + crown_h // 3),
                    (crown_x + crown_w // 2, crown_y),
                    (crown_x + crown_w * 4 // 5, crown_y + crown_h // 3),
                    (crown_x + crown_w, crown_y + crown_h),
                ]
                pygame.draw.polygon(panel, (255, 218, 82), points)
                pygame.draw.rect(panel, (156, 98, 0), (crown_x, crown_y + crown_h - 3, crown_w, 4), border_radius=2)

            score = int(entry.get("score", 0))
            score_col = style["score"] if top3 else (17, 88, 180)
            score_s = score_font.render(f"{score:05d}", True, score_col)
            date_s = date_font.render(str(entry.get("date", ""))[:10], True, (72, 87, 108))
            text_x = av_x + avatar_size + max(18, int(card_w * 0.035))
            score_y = y + card_h // 2 - score_s.get_height() + 4
            panel.blit(score_s, (text_x, score_y))
            panel.blit(date_s, (text_x, y + card_h // 2 + 12))

            if top3:
                label_s = tag_font.render(style["label"], True, (30, 34, 42))
                tag_w = label_s.get_width() + 22
                tag_h = label_s.get_height() + 9
                tag_x = x + card_w - tag_w - 14
                tag_y = y + 12
                pygame.draw.rect(panel, style["badge"], (tag_x, tag_y, tag_w, tag_h), border_radius=11)
                pygame.draw.rect(panel, (255, 255, 255, 105), (tag_x + 2, tag_y + 2, tag_w - 4, 2), border_radius=2)
                panel.blit(label_s, (tag_x + 11, tag_y + 4))

            if is_new:
                new_s = tag_font.render("NEW", True, (105, 58, 0))
                new_w = new_s.get_width() + 22
                new_h = new_s.get_height() + 10
                new_x = x + card_w - new_w - 14
                new_y = y + card_h - new_h - 12
                pygame.draw.rect(panel, (255, 225, 92), (new_x, new_y, new_w, new_h), border_radius=11)
                panel.blit(new_s, (new_x + 11, new_y + 5))

    static_screen.blit(panel, (panel_x, panel_y))

    while True:
        clock.tick(FPS)
        remaining = max(0.0, deadline - time.time())

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit(); sys.exit()
                return

        if time.time() >= gesture_cd and gesture_ctrl.get_gesture() == "iloveyou":
            return
        if remaining <= 0:
            return

        display.blit(static_screen, (0, 0))
        footer = footer_font.render(
            f"Show I Love You gesture to continue  |  Auto continue in {remaining:.0f}s",
            True,
            (232, 240, 252),
        )
        footer_x = panel_x + panel_w // 2 - footer.get_width() // 2
        footer_y = panel_y + panel_h - footer_h + (footer_h - footer.get_height()) // 2
        display.blit(footer, (footer_x, footer_y))

        pygame.display.flip()

# ─────────────────────────────────────────────────────────────────────────────
#  INTRO SCREEN
# ─────────────────────────────────────────────────────────────────────────────
def introscreen():
    set_background_for_score(0)
    temp_dino = Dino(88*S//2, 95*S//2)
    temp_dino.isBlinking = True

    callout, callout_rect = load_callout_image('call_out.png', 196*S//2, 45*S//2)
    callout_rect.left = width * 0.05
    callout_rect.top  = height * 0.4

    temp_ground, temp_ground_rect = load_sprite_sheet('ground.png', 15, 1, -1, -1, -1)
    # scale the ground tile
    gw = int(temp_ground[0].get_width() * S)
    gh = int(temp_ground[0].get_height() * S)
    temp_ground_scaled = [pygame.transform.scale(g, (gw, gh)) for g in temp_ground]
    temp_ground_rect   = temp_ground_scaled[0].get_rect()
    temp_ground_rect.left   = width // 20
    temp_ground_rect.bottom = height

    logo, logo_rect = load_image('logo.png', 240*S//2, 40*S//2, -1)
    logo_rect.centerx = width  * 0.6
    logo_rect.centery = height * 0.6

    gesture_jump_t = 0.0

    while True:
        if pygame.display.get_surface() is None: return True
        for event in pygame.event.get():
            if event.type == pygame.QUIT: return True
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit(); sys.exit()
                if event.key in (pygame.K_SPACE, pygame.K_UP):
                    if temp_dino.isBlinking:
                        temp_dino.isBlinking  = False
                        temp_dino.isJumping   = True
                        temp_dino.movement[1] = -1 * temp_dino.jumpSpeed

        if temp_dino.isBlinking:
            g = gesture_ctrl.get_gesture()
            if g == "iloveyou" and time.time() >= gesture_jump_t:
                temp_dino.isBlinking  = False
                temp_dino.isJumping   = True
                temp_dino.movement[1] = -1 * temp_dino.jumpSpeed
                gesture_jump_t = time.time() + 1.0

        temp_dino.update()
        draw_game_background(screen)
        screen.blit(temp_ground_scaled[0], temp_ground_rect)
        if temp_dino.isBlinking:
            screen.blit(logo,    logo_rect)
            screen.blit(callout, callout_rect)
            if gesture_ctrl.running:
                theme = get_current_theme_colors()
                hint = txt("I Love You=Start   Open Palm=Jump   V-sign=Duck", _fnt_sm, theme["hint_text"])
                screen.blit(hint, (width//2 - hint.get_width()//2, height - hint.get_height() - 4))
        temp_dino.draw()
        draw_gesture_hud()
        present_frame()
        clock.tick(FPS)
        if not temp_dino.isJumping and not temp_dino.isBlinking: return False

# ─────────────────────────────────────────────────────────────────────────────
#  GAMEPLAY
# ─────────────────────────────────────────────────────────────────────────────
def gameplay():
    global high_score

    # Sprite sizes (2x original)
    DINO_W, DINO_H   = 88*S//2, 95*S//2    # = 88, 95 for S=2
    CACT_W, CACT_H   = 68*S//2, 70*S//2    # = 68, 70
    CBIG_W, CBIG_H   = 101*S//2,101*S//2   # = 101,101
    PTER_W, PTER_H   = 92*S//2, 81*S//2    # = 92, 81

    # Initial difficulty
    set_background_for_score(0)
    _, gamespeed, _, _, _, _ = get_difficulty(0)
    gamespeed = int(gamespeed)

    gameOver = gameQuit = False
    counter  = 0

    playerDino    = Dino(DINO_W, DINO_H)
    new_ground    = Ground(-1 * gamespeed)
    scb           = Scoreboard()
    highsc        = Scoreboard(width * 0.78)
    top5_scores   = load_leaderboard()[:5]

    cacti         = pygame.sprite.Group()
    cacti_big     = pygame.sprite.Group()
    pteras        = pygame.sprite.Group()
    bullets       = pygame.sprite.Group()
    clouds        = pygame.sprite.Group()
    Cactus.containers    = cacti
    CactusBig.containers = cacti_big
    Ptera.containers     = pteras
    Bullet.containers    = bullets
    Cloud.containers     = clouds

    retbutton_image, _ = load_image('replay_button.png', 35*S//2, 31*S//2, -1)
    gameover_image,  _ = load_image('game_over.png',    190*S//2, 11*S//2, -1)

    dw = 11*S; dh = int(11*S * 6/5)
    temp_images, temp_rect = load_sprite_sheet('numbers.png', 12, 1, dw, dh, -1)
    HI_image = pygame.Surface((dw*2, dh), pygame.SRCALPHA).convert_alpha(); HI_rect = HI_image.get_rect()
    HI_image.fill((0, 0, 0, 0))
    HI_image.blit(temp_images[10], temp_rect); temp_rect.left += temp_rect.width
    HI_image.blit(temp_images[11], temp_rect); temp_rect.left = 0
    HI_rect.top  = height * 0.1
    HI_rect.left = width  * 0.73

    GESTURE_JUMP_CD = int(FPS * 0.35)
    gesture_jump_cd = 0

    # ── Wave-based obstacle spawner ───────────────────────────────────────
    # Instead of spawning one obstacle at a time, we queue a full "wave":
    # a list of (type, x_offset) to be placed when the screen is clear.
    # Between waves we wait a random gap (in pixels scrolled).
    spawn_queue    = []   # list of ('cactus'|'cactus_big'|'ptera', x_pixel_offset)
    next_wave_at   = width + random.randint(80, 160)  # px scrolled before first wave
    px_scrolled    = 0    # cumulative pixels scrolled (approx)

    def build_wave(score):
        """
        Build one wave of obstacles guaranteed to be survivable:
        ─ A wave is either CACTUS-only or PTERA-only (never mixed ptera+cactus
          at different heights simultaneously — that would be unplayable).
        ─ Ptera-only waves appear from score 0 with increasing frequency.
        ─ Shooting ptera appear from score 300; shoot probability scales with score.
        ─ Cactus clusters: 1–3 cacti, count weighted by score.
        ─ All clusters are validated: player must have at least one safe action.

        SURVIVABILITY RULES enforced here:
          • Never two pteras at different heights in the same wave.
          • Max cactus cluster width never exceeds a single-jump clearance.
          • Ptera+cactus same wave only if they appear sequentially (not side-by-side).
        """
        # ── Ptera probability per wave ──────────────────────────────────────
        # score   0 →  35%   (appears from the very start)
        # score 200 →  45%
        # score 500 →  55%
        # score 900 →  65%
        ptera_chance = min(0.65, 0.35 + score / 3000)

        # ── Shooting probability (only when ptera wave chosen) ──────────────
        # score 300 →  15%,  score 800 → 40%,  score 1500 → 60%
        shoot_chance = min(0.60, max(0.0, (score - 300) / 2000))

        if random.random() < ptera_chance:
            # ── PTERA WAVE ──────────────────────────────────────────────────
            # Single ptera at ONE random height — never two pteras in one wave.
            h_slot    = random.randrange(0, 3)
            shooting  = random.random() < shoot_chance
            return [('ptera', 0, {'height_slot': h_slot, 'can_shoot': shooting})]

        # ── CACTUS WAVE ─────────────────────────────────────────────────────
        if score < 300:
            count = random.choices([1, 2], weights=[70, 30])[0]
        elif score < 700:
            count = random.choices([1, 2, 3], weights=[30, 45, 25])[0]
        else:
            count = random.choices([1, 2, 3], weights=[20, 38, 42])[0]

        wave   = []
        x_off  = 0
        for _ in range(count):
            use_big = score > 400 and random.random() < 0.35
            kind = 'cactus_big' if use_big else 'cactus'
            wave.append((kind, x_off, {}))
            # Variable spacing within cluster (10–28 px)
            x_off += random.randint(10, 28)

        return wave

    def gap_between_waves(score, gamespeed):
        """
        Random gap (in px scrolled) before the next wave triggers.
        Decreases with difficulty but always has a lower bound so the
        player can physically land from a jump before the next obstacle appears.

        Jump airtime ≈ 2 * jumpSpeed / gravity  frames
        Minimum safe gap = airtime * speed + some margin
        """
        jump_speed = 11.5 * S
        airtime    = int(2 * jump_speed / gravity) + 10    # frames
        safe_min   = gamespeed * airtime                   # px: must clear landing

        # Extra breathing room shrinks with difficulty
        extra_min  = max(40,  int(200 - score * 0.08))
        extra_max  = max(120, int(380 - score * 0.10))

        min_gap = safe_min + extra_min
        max_gap = safe_min + extra_max
        return random.randint(min_gap, max_gap)

    # ── Main loop ────────────────────────────────────────────────────────────
    while not gameOver:
        if pygame.display.get_surface() is None:
            gameQuit = True; break

        # Update difficulty and background every frame based on score
        score = playerDino.score
        set_background_for_score(score)
        _, gamespeed, _, ptera_prob, _, _ = get_difficulty(score)
        gamespeed = int(gamespeed)
        new_ground.speed = -1 * gamespeed
        px_scrolled += gamespeed

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                gameQuit = True; gameOver = True
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit(); sys.exit()
                if event.key in (pygame.K_SPACE, pygame.K_UP):
                    if playerDino.rect.bottom == int(0.98 * height):
                        playerDino.isJumping   = True
                        playerDino.movement[1] = -1 * playerDino.jumpSpeed
                        if pygame.mixer.get_init(): jump_sound.play()
                if event.key == pygame.K_DOWN:
                    if not (playerDino.isJumping or playerDino.isDead):
                        playerDino.isDucking = True
            if event.type == pygame.KEYUP:
                if event.key == pygame.K_DOWN: playerDino.isDucking = False

        # ── Gesture input ─────────────────────────────────────────────────
        # 🖐️ Open Palm  → Jump
        # ✊ Closed Fist → Duck  (just clench the same hand — no wrist flip needed)
        # anything else → neutral
        if gesture_ctrl.running:
            g = gesture_ctrl.get_gesture()
            # DUCK: ✌️ V-sign (index + middle extended, ring + pinky folded)
            if g == "vtwo":
                if not (playerDino.isJumping or playerDino.isDead):
                    playerDino.isDucking = True
            else:
                if playerDino.isDucking: playerDino.isDucking = False
            # JUMP: 🖐️ open palm (with cooldown)
            if gesture_jump_cd > 0: gesture_jump_cd -= 1
            if (g == "open" and gesture_jump_cd == 0 and
                    playerDino.rect.bottom == int(0.98*height) and
                    not playerDino.isDucking):
                playerDino.isJumping   = True
                playerDino.movement[1] = -1 * playerDino.jumpSpeed
                gesture_jump_cd        = GESTURE_JUMP_CD
                if pygame.mixer.get_init(): jump_sound.play()

        # ── Update all obstacle speeds ────────────────────────────────────
        for obs in list(cacti) + list(cacti_big) + list(pteras):
            obs.movement[0] = -1 * gamespeed

        # ── Collision ─────────────────────────────────────────────────────
        for c in list(cacti) + list(cacti_big):
            if pygame.sprite.collide_mask(playerDino, c):
                playerDino.isDead = True
                if pygame.mixer.get_init(): die_sound.play()
        for p in pteras:
            if pygame.sprite.collide_mask(playerDino, p):
                playerDino.isDead = True
                if pygame.mixer.get_init(): die_sound.play()
        # Bullet collision (rect-based, forgiving hitbox)
        dino_rect_shrunk = playerDino.rect.inflate(-8*S//2, -8*S//2)
        for b in list(bullets):
            if dino_rect_shrunk.colliderect(b.rect):
                playerDino.isDead = True
                if pygame.mixer.get_init(): die_sound.play()
                break

        # ── Wave spawner ──────────────────────────────────────────────────
        all_active   = list(cacti) + list(cacti_big) + list(pteras)
        screen_clear = all(obs.rect.right < width * 0.75 for obs in all_active)

        if screen_clear and px_scrolled >= next_wave_at:
            if not spawn_queue:
                spawn_queue = build_wave(score)

        # Place queued items — tuple is now (kind, x_off, kwargs_dict)
        if spawn_queue:
            kind, x_off, kwargs = spawn_queue[0]
            target_x = width + x_off
            if kind == 'cactus':
                obs = Cactus(gamespeed, CACT_W, CACT_H)
                obs.rect.left = target_x
            elif kind == 'cactus_big':
                obs = CactusBig(gamespeed, CBIG_W, CBIG_H)
                obs.rect.left = target_x
            else:  # ptera
                obs = Ptera(gamespeed, PTER_W, PTER_H,
                            height_slot=kwargs.get('height_slot'),
                            can_shoot=kwargs.get('can_shoot', False))
                obs.rect.left = target_x
            spawn_queue.pop(0)
            if not spawn_queue:
                gap = gap_between_waves(score, gamespeed)
                next_wave_at = px_scrolled + gap

        # Clouds
        if len(clouds) < 5 and random.randrange(0, 300) == 10:
            Cloud(width, random.randrange(height//5, height//2))

        # ── Update ────────────────────────────────────────────────────────
        playerDino.update()
        cacti.update(); cacti_big.update(); pteras.update()
        bullets.update(); clouds.update()
        new_ground.update()
        scb.update(playerDino.score)
        highsc.update(high_score)

        # ── Draw ──────────────────────────────────────────────────────────
        draw_game_background(screen)
        new_ground.draw(); clouds.draw(screen)
        scb.draw()
        if high_score != 0: highsc.draw(); screen.blit(HI_image, HI_rect)
        cacti.draw(screen); cacti_big.draw(screen); pteras.draw(screen)
        bullets.draw(screen)
        playerDino.draw()
        draw_gesture_hud()
        draw_speed_indicator(score)
        present_frame(playerDino, top5_scores)
        clock.tick(FPS)

        if playerDino.isDead:
            gameOver = True
            if playerDino.score > high_score: high_score = playerDino.score

        counter += 1

    if gameQuit: pygame.quit(); sys.exit()

    # ── Game-over freeze ──────────────────────────────────────────────────
    for _ in range(int(FPS * 1.8)):
        for event in pygame.event.get():
            if event.type == pygame.QUIT: pygame.quit(); sys.exit()
        draw_game_background(screen)
        new_ground.draw(); clouds.draw(screen); scb.draw()
        if high_score != 0: highsc.draw(); screen.blit(HI_image, HI_rect)
        cacti.draw(screen); cacti_big.draw(screen); pteras.draw(screen)
        bullets.draw(screen)
        playerDino.draw()
        disp_gameOver_msg(retbutton_image, gameover_image)
        draw_gesture_hud()
        present_frame(playerDino, top5_scores); clock.tick(FPS)

    avatar_data = gesture_ctrl.capture_face_avatar(size=128)
    top_scores, entry_id = add_score(avatar_data, playerDino.score)
    leaderboard_screen(highlight_id=entry_id, highlight_score=playerDino.score)
    gameplay()   # restart

# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    gesture_ctrl.start()
    # Do not block startup while MediaPipe warms up. The intro screen will update
    # automatically as soon as the webcam thread is ready.
    quit_flag = introscreen()
    if not quit_flag: gameplay()
    gesture_ctrl.stop()
    pygame.quit(); sys.exit()

main()