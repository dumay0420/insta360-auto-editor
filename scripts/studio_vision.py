"""Insta360 Studio 視窗截圖、文字辨識（macOS Vision OCR）、範本比對、點擊。

只截 Insta360 Studio 自己的視窗（screencapture -l），不截整個螢幕。
座標：OCR／範本比對回傳「螢幕座標（point）」，可直接拿去點。
"""
import os
import re
import subprocess
import tempfile
import time

import cv2
import numpy as np
import Quartz
import Vision
from ApplicationServices import AXIsProcessTrusted
from Foundation import NSURL

def _find_app():
    """找 Insta360 Studio.app：環境變數 INSTA360_STUDIO_APP → Spotlight（bundle id）→ /Applications。"""
    env = os.environ.get("INSTA360_STUDIO_APP")
    if env and os.path.isdir(env):
        return env
    try:
        r = subprocess.run(["mdfind", "kMDItemCFBundleIdentifier == 'com.insta360.studio'"],
                           capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            if line.endswith(".app") and os.path.isdir(line):
                return line
    except Exception:
        pass
    return "/Applications/Insta360 Studio.app"


APP_PATH = _find_app()
PROC_NAME = "studio-main"          # System Events 看到的程序名稱
OWNER_NAMES = ("Insta360 Studio", "studio-main")
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(SKILL_DIR, "templates")
DEBUG_DIR = os.path.join(tempfile.gettempdir(), "insta360-auto-editor")
os.makedirs(DEBUG_DIR, exist_ok=True)


# ---------- 權限 ----------
def check_permissions():
    ax = bool(AXIsProcessTrusted())
    screen = bool(Quartz.CGPreflightScreenCaptureAccess())
    return {"accessibility": ax, "screen_recording": screen}


# ---------- 視窗 ----------
def find_window():
    """回傳 Studio 主視窗 {id, x, y, w, h}（螢幕 point），找不到回 None。"""
    infos = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID) or []
    best = None
    for w in infos:
        if w.get("kCGWindowOwnerName") not in OWNER_NAMES or w.get("kCGWindowLayer", 1) != 0:
            continue
        b = w["kCGWindowBounds"]
        area = b["Width"] * b["Height"]
        if area < 200 * 200:
            continue
        if best is None or area > best["w"] * best["h"]:
            best = dict(id=w["kCGWindowNumber"], x=b["X"], y=b["Y"], w=b["Width"], h=b["Height"])
    return best


def all_windows():
    """Studio 所有在螢幕上的視窗（含對話框），大到小。"""
    infos = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []
    out = []
    for w in infos:
        if w.get("kCGWindowOwnerName") in OWNER_NAMES and w.get("kCGWindowLayer", 1) == 0:
            b = w["kCGWindowBounds"]
            out.append(dict(id=w["kCGWindowNumber"], x=b["X"], y=b["Y"], w=b["Width"], h=b["Height"],
                            name=w.get("kCGWindowName", "")))
    return sorted(out, key=lambda d: -d["w"] * d["h"])


def osa(script):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip()


WIN_POS = (80, 60)       # 視窗固定擺這裡（螢幕 point），每次位置一樣，點擊才準
WIN_SIZE = (1440, 932)


def place_window():
    osa(f'tell application "System Events" to tell (first process whose name is "{PROC_NAME}") to '
        f'tell window 1 to set {{position, size}} to {{{{{WIN_POS[0]}, {WIN_POS[1]}}}, {{{WIN_SIZE[0]}, {WIN_SIZE[1]}}}}}')


def activate(launch_timeout=90, place=True):
    """開啟或切換到 Insta360 Studio，等主視窗出現，擺到固定位置。"""
    subprocess.run(["open", "-a", APP_PATH], check=True)
    t0 = time.time()
    while time.time() - t0 < launch_timeout:
        w = find_window()
        if w:
            osa(f'tell application "System Events" to set frontmost of (first process whose name is "{PROC_NAME}") to true')
            time.sleep(0.8)
            if place:
                place_window()
                time.sleep(0.8)
            return find_window()
        time.sleep(1)
    raise RuntimeError("等了 %d 秒還沒看到 Insta360 Studio 視窗" % launch_timeout)


def quit_studio(timeout=30):
    osa('tell application id "com.insta360.studio" to quit')
    t0 = time.time()
    while time.time() - t0 < timeout:
        if subprocess.run(["pgrep", "-x", PROC_NAME], capture_output=True).returncode != 0:
            return True
        time.sleep(1)
    return False


def is_running():
    return subprocess.run(["pgrep", "-x", PROC_NAME], capture_output=True).returncode == 0


def menu(menu_name, item):
    """點選單列項目，例如 menu("檔案", "導出")。"""
    out, err = osa(f'tell application "System Events" to tell (first process whose name is "{PROC_NAME}") to '
                   f'click menu item "{item}" of menu 1 of menu bar item "{menu_name}" of menu bar 1')
    if err:
        raise RuntimeError(f"點選單 {menu_name} > {item} 失敗：{err}")


def key(code, times=1):
    osa(f'tell application "System Events"\nrepeat {times} times\nkey code {code}\ndelay 0.03\nend repeat\nend tell')


def type_text(text):
    osa(f'tell application "System Events" to keystroke "{text}"')


# ---------- 截圖 ----------
class Shot:
    """一張視窗截圖。img 是 BGR 像素；scale = 像素 / point。"""

    def __init__(self, img, win):
        self.img, self.win = img, win
        self.scale = img.shape[1] / float(win["w"])

    def to_screen(self, px, py):
        return self.win["x"] + px / self.scale, self.win["y"] + py / self.scale

    def save(self, name):
        p = os.path.join(DEBUG_DIR, name)
        cv2.imwrite(p, self.img)
        return p


def capture(win=None):
    win = win or find_window()
    if not win:
        raise RuntimeError("找不到 Insta360 Studio 視窗")
    path = os.path.join(DEBUG_DIR, "_shot.png")
    # 用 -R 只拍 Studio 視窗那一塊（Studio 已在最前面），這樣右鍵選單、對話框這些
    # 浮在視窗上的小視窗也會拍到；-l 只拍主視窗本體，會漏掉它們。
    rect = "%d,%d,%d,%d" % (win["x"], win["y"], win["w"], win["h"])
    subprocess.run(["screencapture", "-x", "-R", rect, path], check=True)
    img = cv2.imread(path)
    if img is None:
        raise RuntimeError("截圖失敗（螢幕錄製權限？）")
    return Shot(img, win)


# ---------- OCR ----------
def ocr(shot, langs=("zh-Hant", "en-US")):
    """回傳 [(文字, 信心, (px, py, pw, ph))]，座標是截圖像素（左上原點）。"""
    path = os.path.join(DEBUG_DIR, "_ocr.png")
    # 非 Retina 螢幕（scale=1）字太小，Vision 會漏字，放大到約 3 倍再辨識。
    up = max(1.0, 3.0 / shot.scale)
    big = cv2.resize(shot.img, None, fx=up, fy=up, interpolation=cv2.INTER_CUBIC) if up > 1 else shot.img
    cv2.imwrite(path, big)
    url = NSURL.fileURLWithPath_(path)
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setRecognitionLanguages_(list(langs))
    req.setUsesLanguageCorrection_(False)
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"OCR 失敗：{err}")
    H, W = shot.img.shape[:2]
    out = []
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)
        if not cand:
            continue
        c = cand[0]
        bb = obs.boundingBox()  # 0~1，左下原點
        px, pw = bb.origin.x * W, bb.size.width * W
        ph = bb.size.height * H
        py = (1 - bb.origin.y - bb.size.height) * H
        out.append((c.string(), float(c.confidence()), (px, py, pw, ph)))
    return out


def find_text(shot, pattern, region=None):
    """找符合 regex 的文字，回傳螢幕座標中心點 (x, y, 文字) 或 None。
    region=(x0,y0,x1,y1) 用 0~1 比例限制搜尋範圍。"""
    rx = re.compile(pattern, re.I)
    H, W = shot.img.shape[:2]
    hits = []
    for text, conf, (px, py, pw, ph) in ocr(shot):
        if not rx.search(text.replace(" ", "")):
            continue
        cx, cy = px + pw / 2, py + ph / 2
        if region and not (region[0] * W <= cx <= region[2] * W and region[1] * H <= cy <= region[3] * H):
            continue
        hits.append((conf, cx, cy, text))
    if not hits:
        return None
    _, cx, cy, text = max(hits)
    x, y = shot.to_screen(cx, cy)
    return x, y, text


# ---------- 範本比對 ----------
def template_path(name):
    return os.path.join(TEMPLATE_DIR, name + ".png")


def find_template(shot, name, threshold=0.82):
    """多尺度比對範本圖，回傳 (x, y, score) 螢幕座標或 None。"""
    p = template_path(name)
    if not os.path.exists(p):
        return None
    tpl = cv2.imread(p)
    meta = p[:-4] + ".scale"
    tpl_scale = float(open(meta).read()) if os.path.exists(meta) else shot.scale
    g = cv2.cvtColor(shot.img, cv2.COLOR_BGR2GRAY)
    best = (0, None, None)
    base = shot.scale / tpl_scale
    for f in (1.0, 0.9, 1.1, 0.8, 1.25, 0.75, 1.5, 0.5, 2.0):
        s = base * f
        t = cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
        if t.shape[0] > g.shape[0] or t.shape[1] > g.shape[1] or min(t.shape[:2]) < 6:
            continue
        r = cv2.matchTemplate(g, cv2.cvtColor(t, cv2.COLOR_BGR2GRAY), cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(r)
        if mx > best[0]:
            best = (mx, loc, t.shape)
        if mx > 0.95:
            break
    score, loc, shape = best
    if loc is None or score < threshold:
        return None
    x, y = shot.to_screen(loc[0] + shape[1] / 2, loc[1] + shape[0] / 2)
    return x, y, score


def locate(name, text_pattern=None, region=None, shot=None):
    """先用範本圖找，找不到再用文字找。回傳 (x, y, 方法) 或 None。"""
    shot = shot or capture()
    hit = find_template(shot, name)
    if hit:
        return hit[0], hit[1], f"template {hit[2]:.2f}"
    if text_pattern:
        hit = find_text(shot, text_pattern, region)
        if hit:
            return hit[0], hit[1], f"ocr '{hit[2]}'"
    return None


# ---------- 滑鼠 ----------
def _post(etype, x, y, button):
    ev = Quartz.CGEventCreateMouseEvent(None, etype, (x, y), button)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def click(x, y, right=False, double=False):
    if right:
        down, up, btn = Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp, Quartz.kCGMouseButtonRight
    else:
        down, up, btn = Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp, Quartz.kCGMouseButtonLeft
    _post(Quartz.kCGEventMouseMoved, x, y, btn)
    time.sleep(0.15)
    for i in range(2 if double else 1):
        ev = Quartz.CGEventCreateMouseEvent(None, down, (x, y), btn)
        Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState, i + 1)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.05)
        ev = Quartz.CGEventCreateMouseEvent(None, up, (x, y), btn)
        Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState, i + 1)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.08)


# ---------- 等待 ----------
def wait_until(fn, timeout, interval=3.0, desc="", on_tick=None):
    """每 interval 秒呼叫 fn()，回傳真值就結束；超時丟錯。"""
    t0 = time.time()
    while True:
        r = fn()
        if r:
            return r
        el = time.time() - t0
        if on_tick:
            on_tick(el)
        if el > timeout:
            raise TimeoutError(f"等 {desc} 超過 {timeout:.0f} 秒")
        time.sleep(interval)
