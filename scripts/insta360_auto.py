#!/usr/bin/env python3
"""Insta360 Studio 自動化：匯入 .insv → （自動構圖）→ 批次輸出平面 MP4。

用法（建議透過 run.sh，它會自動用 skill 資料夾裡的 .venv）：
  ./run.sh check                         # 檢查權限、Studio 版本、範本
  ./run.sh probe                         # 探測選單、可抓到的按鈕、畫面文字
  ./run.sh calibrate [名稱 ...]           # 校準：手動框選按鈕存成範本圖
  ./run.sh calibrate --test 名稱          # 測試範本找不找得到
  ./run.sh run 素材資料夾 --out 輸出資料夾 [--dry-run]

在 Insta360 Studio 6.0.8（macOS、繁體中文介面）實測。
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import studio_vision as sv  # noqa: E402

INI = os.path.expanduser("~/Library/Application Support/Insta360/Insta360 Studio/startup.ini")

# 校準目標：名稱 → (說明, 找不到範本時改用的 OCR 文字)
TARGETS = {
    "auto_frame_menu": ("右鍵選單裡的「開始自動構圖」那一行", r"自動構圖|自动构图|Auto ?Frame"),
    "auto_frame_done": ("縮圖右下角「自動構圖完成」的小圖示", None),
    "export_button": ("輸出視窗右下角黃色的「輸出」按鈕", r"^[輸翰轉]出$"),
}
POPUP_BUTTONS = r"^(我瞭解了|我知道了|退出引導|知道了|稍後|OK|確定)$"


def log(msg):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


# ---------------- 檔案 ----------------
def list_clips(folder):
    """資料夾裡要匯入的 .insv。雙鏡頭分檔（_00_／_10_）只送 _00_，Studio 會自動配對。"""
    files = sorted(glob.glob(os.path.join(folder, "*.insv")) + glob.glob(os.path.join(folder, "*.INSV")))
    keep = []
    for f in files:
        b = os.path.basename(f)
        if "_10_" in b and os.path.exists(os.path.join(folder, b.replace("_10_", "_00_"))):
            continue
        keep.append(f)
    return keep


def display_name(path):
    """Studio 媒體庫顯示的短名稱：VID_20181123_101349_00_173.insv → VID_173.insv"""
    stem = os.path.splitext(os.path.basename(path))[0]
    parts = stem.split("_")
    if len(parts) >= 3 and parts[0].upper() in ("VID", "IMG", "LRV", "PRO"):
        return f"{parts[0]}_{parts[-1]}"
    return stem


# ---------------- startup.ini（輸出路徑） ----------------
def get_export_location():
    m = re.search(r"(?m)^export_location=(.*)$", open(INI, encoding="utf-8").read())
    return m.group(1) if m else None


def set_export_location(path):
    """Studio 關著的時候改 startup.ini 的 export_location。改之前備份一次。"""
    s = open(INI, encoding="utf-8").read()
    bak = INI + ".bak-insta360-auto-editor"
    if not os.path.exists(bak):
        shutil.copy2(INI, bak)
    s2 = re.sub(r"(?m)^export_location=.*$", "export_location=" + path, s)
    if s2 == s and "export_location=" not in s:
        s2 = s.replace("[preference]\n", "[preference]\nexport_location=" + path + "\n")
    open(INI, "w", encoding="utf-8").write(s2)


# ---------------- 畫面小工具 ----------------
def dismiss_popups(rounds=3):
    """關掉新手引導、警告框之類擋路的東西。"""
    n = 0
    for _ in range(rounds):
        hit = sv.find_text(sv.capture(), POPUP_BUTTONS)
        if not hit:
            break
        log(f"關掉彈出提示：{hit[2]}")
        sv.click(hit[0], hit[1])
        time.sleep(1.2)
        n += 1
    return n


def click_empty():
    """點媒體區下方空白處，收掉選單。"""
    w = sv.find_window()
    sv.click(w["x"] + 330, w["y"] + w["h"] - 120)
    time.sleep(0.6)


def media_labels(shot):
    """媒體庫裡看得到的檔名標籤 → {短名稱: (文字左邊 x, 文字上緣 y) 截圖像素}"""
    W = shot.img.shape[1]
    out = {}
    for text, conf, (px, py, pw, ph) in sv.ocr(shot):
        t = text.replace(" ", "")
        m = re.match(r"^((?:VID|IMG|PRO|LRV)_\d+)", t, re.I)
        if m and px < W * 0.36:
            out[m.group(1).upper()] = (px, py)
    return out


def thumb_point(shot, label_xy):
    """縮圖中心：在檔名標籤上方。（6.0.8 實測：標籤左緣 +48pt、標籤上緣 -58pt）"""
    px, py = label_xy
    s = shot.scale
    return shot.to_screen(px + 48 * s, py - 58 * s)


def cmd_click(x, y):
    import Quartz
    for t in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        ev = Quartz.CGEventCreateMouseEvent(None, t, (x, y), Quartz.kCGMouseButtonLeft)
        Quartz.CGEventSetFlags(ev, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.06)


def scroll_media(lines=-5):
    import Quartz
    w = sv.find_window()
    x, y = w["x"] + 320, w["y"] + w["h"] / 2
    Quartz.CGEventPost(Quartz.kCGHIDEventTap,
                       Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (x, y), 0))
    Quartz.CGEventPost(Quartz.kCGHIDEventTap,
                       Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, lines))
    time.sleep(0.8)


def wait_labels(names, timeout=180):
    def ok():
        dismiss_popups(1)
        got = media_labels(sv.capture())
        miss = [n for n in names if n not in got]
        return not miss and got
    return sv.wait_until(ok, timeout, 3, "素材出現在媒體庫")


# ---------------- 輸出視窗 ----------------
def dialog_open(shot=None):
    return bool(sv.find_text(shot or sv.capture(), r"加入輸出[隊队]列"))


def close_dialog():
    """點輸出視窗左上角的紅點關掉（這個視窗按 Esc 關不掉）。"""
    shot = sv.capture()
    title = sv.find_text(shot, r"^[輸翰]出$", region=(0.3, 0.05, 0.7, 0.3))
    if not title:
        return False
    tx, ty = title[0], title[1]
    # 在標題同一列往左找紅色圓點
    img = shot.img
    py = int((ty - shot.win["y"]) * shot.scale)
    best = None
    for px in range(int((tx - shot.win["x"]) * shot.scale) - 10, 0, -1):
        b, g, r = img[py, px]
        if r > 200 and g < 110 and b < 110:
            best = px
            break
    if best is None:
        return False
    x, y = shot.to_screen(best - 4 * shot.scale, py)
    sv.click(x, y)
    time.sleep(1)
    return not dialog_open()


def label_pos(shot, pattern):
    """找視窗左側欄位標籤（例如「編碼格式：」），回傳 (x, y) 螢幕座標。"""
    return sv.find_text(shot, pattern, region=(0.25, 0.1, 0.62, 0.95))


def pick_dropdown(label_pattern, option_pattern, offset=150):
    """點標籤右邊的下拉選單，再點符合的選項。回傳選到的文字。"""
    shot = sv.capture()
    lab = label_pos(shot, label_pattern)
    if not lab:
        raise RuntimeError(f"輸出視窗找不到欄位：{label_pattern}")
    sv.click(lab[0] + offset, lab[1])
    time.sleep(1.2)
    shot = sv.capture()
    opt = None
    rx = re.compile(option_pattern)
    H = shot.img.shape[0]
    for text, conf, (px, py, pw, ph) in sv.ocr(shot):
        t = re.sub(r"^[V✓♥•<＜\s]+", "", text.replace(" ", ""))
        sx, sy = shot.to_screen(px + pw / 2, py + ph / 2)
        if rx.search(t) and abs(sy - lab[1]) > 8 and abs(sx - (lab[0] + offset)) < 260:
            # 優先選在欄位下方的（選單通常往下開）
            if opt is None or (opt[1] < lab[1] < sy):
                opt = (sx, sy, t)
    if not opt:
        sv.click(lab[0] + offset, lab[1])  # 收起選單
        raise RuntimeError(f"下拉選單裡找不到選項：{option_pattern}")
    sv.click(opt[0], opt[1])
    time.sleep(0.8)
    return opt[2]


def set_number_field(label_pattern, value, offset=80):
    """Studio 的數字欄位不吃 Cmd+A，要先移到最後再全部刪掉。"""
    lab = label_pos(sv.capture(), label_pattern)
    if not lab:
        raise RuntimeError(f"輸出視窗找不到欄位：{label_pattern}")
    sv.click(lab[0] + offset, lab[1])
    time.sleep(0.4)
    sv.key(124, 8)   # →
    sv.key(51, 10)   # Backspace
    sv.type_text(str(value))
    sv.key(36)       # Return
    time.sleep(0.8)
    dismiss_popups(1)


def read_dialog_settings():
    shot = sv.capture()
    W = shot.img.shape[1]
    return [t for t, c, (px, py, pw, ph) in sv.ocr(shot) if W * 0.3 < px < W * 0.7]


def configure_export(single, codec, width, quality, ratio):
    if single:
        # 單支：解析度是選單（最高 4K-3840x2160）、影格率（碼率）、編碼格式
        res = {3840: r"4K", 2560: r"2K", 1920: r"1080P"}.get(width, r"4K")
        log("解析度 → " + pick_dropdown(r"^解析度[:：]?$", res))
        log("碼率 → " + pick_dropdown(r"^影格率", r"^" + quality + "$"))
        log("編碼 → " + pick_dropdown(r"^[編编]碼格式", re.escape(codec) + "$"))
    else:
        # 多支（批次）：比例選單、寬度數字欄位（高度自動算）、碼率品質、編碼格式
        log("比例 → " + pick_dropdown(r"^解析度比例", "^" + re.escape(ratio) + "$"))
        set_number_field(r"^解析度[:：]?$", width)
        log(f"寬度 → {width}")
        log("碼率 → " + pick_dropdown(r"^碼率品質", r"^" + quality + "$"))
        log("編碼 → " + pick_dropdown(r"^[編编]碼格式", re.escape(codec) + "$"))
    log("目前設定：" + " / ".join(read_dialog_settings()))


# ---------------- 自動構圖 ----------------
def auto_frame(clips_xy, mode, timeout):
    """右鍵 → 開始自動構圖 → 等分析完。Studio 6.0 起官方移除此功能，找不到就依 mode 處理。"""
    if mode == "skip":
        return
    started = 0
    for name, (x, y) in clips_xy.items():
        sv.click(x, y, right=True)
        time.sleep(1.2)
        hit = sv.locate("auto_frame_menu", TARGETS["auto_frame_menu"][1])
        if not hit:
            click_empty()
            msg = ("右鍵選單沒有「開始自動構圖」。Insta360 Studio 6.0.0 起官方已移除這個功能，"
                   "要用得裝 5.x 舊版。")
            if mode == "require":
                raise RuntimeError(msg)
            log(msg + " 這一步跳過，直接輸出。")
            return
        log(f"{name}：點「開始自動構圖」（{hit[2]}）")
        sv.click(hit[0], hit[1])
        started += 1
        time.sleep(2)
        dismiss_popups(2)
    if not started:
        return

    def done():
        shot = sv.capture()
        busy = sv.find_text(shot, r"分析中|構圖中|處理中|\d{1,3}%")
        if busy:
            return False
        if os.path.exists(sv.template_path("auto_frame_done")):
            return sv.find_template(shot, "auto_frame_done") is not None
        return True
    sv.wait_until(done, timeout, 5, "自動構圖分析",
                  on_tick=lambda el: log(f"自動構圖分析中… {el / 60:.1f} 分") if int(el) % 60 < 5 else None)
    log("自動構圖完成")


# ---------------- 輸出完成判斷 ----------------
def wait_exports(out_dir, clips, t_start, timeout):
    stems = [os.path.splitext(os.path.basename(c))[0] for c in clips]
    last = {}

    def status():
        found = {}
        for f in os.listdir(out_dir):
            p = os.path.join(out_dir, f)
            if not f.lower().endswith((".mp4", ".mov")) or os.path.getmtime(p) < t_start - 5:
                continue
            for s in stems:
                if f.startswith(s):
                    found[s] = (f, os.path.getsize(p))
        return found

    def ok():
        found = status()
        stable = all(last.get(s) == found.get(s) for s in found)
        last.clear()
        last.update(found)
        if len(found) == len(stems) and stable and not dialog_open():
            return found
        return False

    def tick(el):
        if int(el) % 60 < 10:
            log(f"輸出中… 已完成 {len(last)}/{len(stems)} 支，經過 {el / 60:.1f} 分")
    return sv.wait_until(ok, timeout, 10, "輸出完成", on_tick=tick)


# ---------------- 指令 ----------------
def cmd_check(_):
    perm = sv.check_permissions()
    ver = subprocess.run(["defaults", "read", sv.APP_PATH + "/Contents/Info", "CFBundleShortVersionString"],
                         capture_output=True, text=True).stdout.strip()
    tpl = {n: os.path.exists(sv.template_path(n)) for n in TARGETS}
    info = dict(permissions=perm, studio_version=ver, studio_running=sv.is_running(),
                export_location=get_export_location(), templates=tpl,
                auto_frame_supported=not ver.startswith(("6", "7", "8")))
    print(json.dumps(info, ensure_ascii=False, indent=2))
    bad = [k for k, v in perm.items() if not v]
    if bad:
        print("\n缺少權限：" + "、".join(bad))
        print("到「系統設定 → 隱私權與安全性 → 輔助使用／螢幕與系統錄音」，"
              "把執行這個腳本的程式（Claude 或 終端機）打開，然後重開它。")
        subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])
        return 1
    if not info["auto_frame_supported"]:
        print("\n注意：Studio %s 沒有「自動構圖」（6.0.0 起官方移除），run 會自動跳過這一步。" % ver)
    return 0


PROBE_AS = r'''
on dump(el, depth, maxd)
  set s to ""
  tell application "System Events"
    set r to ""
    set t to ""
    set d to ""
    try
      set r to role of el
    end try
    try
      set t to title of el
      if t is missing value then set t to ""
    end try
    try
      set d to description of el
      if d is missing value then set d to ""
    end try
    set ind to ""
    repeat depth times
      set ind to ind & "  "
    end repeat
    set s to ind & r & " | " & t & " | " & d & linefeed
    if depth < maxd then
      try
        repeat with c in UI elements of el
          set s to s & my dump(c, depth + 1, maxd)
        end repeat
      end try
    end if
  end tell
  return s
end dump
set out to ""
tell application "System Events"
  set p to first process whose name is "studio-main"
  repeat with mb in menu bar items of menu bar 1 of p
    set out to out & "選單 [" & (name of mb as text) & "]: "
    try
      repeat with mi in menu items of menu 1 of mb
        set nm to name of mi
        if nm is missing value then set nm to "---"
        set out to out & nm & " | "
      end repeat
    end try
    set out to out & linefeed
  end repeat
  set ws to windows of p
end tell
repeat with w in ws
  set out to out & "視窗：" & linefeed & dump(w, 0, 4)
end repeat
return out
'''


def cmd_probe(_):
    sv.activate()
    out, err = sv.osa(PROBE_AS)
    print("=== 選單列與輔助使用樹（Accessibility）===")
    print(out or err)
    shot = sv.capture()
    print("=== 畫面文字（OCR）===  視窗", shot.win, "scale", round(shot.scale, 2))
    for text, conf, (px, py, pw, ph) in sv.ocr(shot):
        print(f"{conf:.1f}  ({int(px)},{int(py)})  {text}")
    print("截圖：", shot.save("probe.png"))
    return 0


def cmd_calibrate(a):
    os.makedirs(sv.TEMPLATE_DIR, exist_ok=True)
    if a.test:
        sv.activate(place=False)
        shot = sv.capture()
        for n in a.test:
            hit = sv.find_template(shot, n, threshold=0.5)
            print(n, "→", f"找到 ({hit[0]:.0f},{hit[1]:.0f}) 相似度 {hit[2]:.2f}" if hit else "找不到")
        return 0
    names = a.names or list(TARGETS)
    for n in names:
        desc = TARGETS.get(n, (n, None))[0]
        print(f"\n【{n}】請先在 Insta360 Studio 把「{desc}」顯示在畫面上。")
        input("準備好就按 Enter，接著用滑鼠框選它（按 Esc 跳過）… ")
        p = sv.template_path(n)
        subprocess.run(["screencapture", "-i", "-x", "-r", p])
        if not os.path.exists(p):
            print("跳過", n)
            continue
        import Quartz
        scale = Quartz.CGDisplayPixelsWide(Quartz.CGMainDisplayID()) / Quartz.CGDisplayBounds(
            Quartz.CGMainDisplayID()).size.width
        open(p[:-4] + ".scale", "w").write(str(scale))
        print("存好了：", p)
    return 0


def cmd_run(a):
    folder = os.path.abspath(os.path.expanduser(a.folder))
    out_dir = os.path.abspath(os.path.expanduser(a.out or os.path.join(folder, "export")))
    clips = list_clips(folder)
    if not clips:
        log("資料夾裡沒有 .insv 檔：" + folder)
        return 2
    names = [display_name(c).upper() for c in clips]
    if len(set(names)) != len(names):
        log("警告：有檔案在 Studio 裡顯示的短名稱重複，選取可能會選錯：" + ", ".join(names))
    log(f"找到 {len(clips)} 支：" + ", ".join(os.path.basename(c) for c in clips))

    perm = sv.check_permissions()
    if not all(perm.values()):
        log(f"權限不足 {perm}，先跑 check")
        return 1

    # 1. 輸出路徑：Studio 關著時改 startup.ini
    os.makedirs(out_dir, exist_ok=True)
    if get_export_location() != out_dir:
        if sv.is_running():
            log("要改輸出路徑，先關掉 Studio（它會自動存檔）")
            if not sv.quit_studio():
                log("Studio 關不掉，請手動關掉再跑一次")
                return 1
        set_export_location(out_dir)
        log("輸出路徑設成：" + out_dir)

    # 2. 開 Studio、匯入（把檔案丟給 Studio 開，等同拖放）
    sv.activate()
    subprocess.run(["open", "-a", sv.APP_PATH] + clips, check=True)
    time.sleep(4)
    sv.activate()
    dismiss_popups()
    wait_labels(names, a.import_timeout)
    log("全部匯入完成")

    # 3. 找每支縮圖的位置（必要時往下捲）
    pos = {}
    for _ in range(15):
        shot = sv.capture()
        for n, xy in media_labels(shot).items():
            if n in names and n not in pos:
                pos[n] = thumb_point(shot, xy)
        if len(pos) == len(names):
            break
        scroll_media(-5)
    miss = [n for n in names if n not in pos]
    if miss:
        log("媒體庫找不到：" + ", ".join(miss))
        return 3

    # 4. 自動構圖
    auto_frame(pos, a.auto_frame, a.auto_frame_timeout)

    # 5. 選取這批素材（第一支一般點，其他 Cmd+點）
    first = True
    for n in names:
        x, y = pos[n]
        if first:
            sv.click(x, y)
            first = False
        else:
            cmd_click(x, y)
        time.sleep(0.4)
    log(f"已選取 {len(names)} 支")

    # 6. 開輸出視窗、設定
    sv.menu("檔案", "導出")
    sv.wait_until(dialog_open, 20, 1, "輸出視窗")
    configure_export(len(clips) == 1, a.codec, a.width, a.quality, a.ratio)

    if a.dry_run:
        log("dry-run：設定好了，不按輸出，關掉視窗結束")
        close_dialog()
        return 0

    # 7. 按輸出、等完成
    hit = sv.locate("export_button", TARGETS["export_button"][1])
    if not hit:
        raise RuntimeError("找不到黃色「輸出」按鈕，請跑 calibrate export_button")
    t_start = time.time()
    sv.click(hit[0], hit[1])
    log("開始輸出（" + hit[2] + "）")
    time.sleep(3)
    dismiss_popups(2)
    found = wait_exports(out_dir, clips, t_start, a.export_timeout)
    log(f"全部輸出完成，花了 {(time.time() - t_start) / 60:.1f} 分：")
    for s, (f, size) in found.items():
        print(f"  {os.path.join(out_dir, f)}  {size / 1e6:.0f} MB")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("probe")
    c = sub.add_parser("calibrate")
    c.add_argument("names", nargs="*", help="要校準的目標：" + ", ".join(TARGETS))
    c.add_argument("--test", nargs="+", help="測試這些範本找不找得到")
    r = sub.add_parser("run")
    r.add_argument("folder")
    r.add_argument("--out", help="輸出資料夾（預設：素材資料夾/export）")
    r.add_argument("--codec", default="H.265", choices=["H.264", "H.265", "ProRes 422", "ProRes 422 LT"])
    r.add_argument("--width", type=int, default=3840, help="寬度（批次可任意；單支只有 1920/2560/3840）")
    r.add_argument("--quality", default="原始", choices=["建議", "原始"])
    r.add_argument("--ratio", default="16:9", choices=["16:9", "9:16", "4:3", "3:4", "1:1", "2.35:1"])
    r.add_argument("--auto-frame", default="skip", choices=["auto", "skip", "require"],
                   help="預設 skip（Studio 6.x 沒有自動構圖）；auto＝有就做、沒有就跳過；require＝沒有就停")
    r.add_argument("--dry-run", action="store_true", help="設定好輸出視窗就停，不真的輸出")
    r.add_argument("--import-timeout", type=float, default=300)
    r.add_argument("--auto-frame-timeout", type=float, default=3 * 3600)
    r.add_argument("--export-timeout", type=float, default=12 * 3600)
    a = ap.parse_args()
    fn = {"check": cmd_check, "probe": cmd_probe, "calibrate": cmd_calibrate, "run": cmd_run}[a.cmd]
    try:
        sys.exit(fn(a))
    except (RuntimeError, TimeoutError) as e:
        log("失敗：" + str(e))
        try:
            print("最後畫面：", sv.capture().save("last_error.png"))
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
