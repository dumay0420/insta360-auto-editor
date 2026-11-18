# insta360-auto-editor

一個 [Claude Code](https://claude.com/claude-code) Skill（也可以單獨當指令列工具用）。給它一個裝 Insta360 `.insv` 全景素材的資料夾，它會自動操作 macOS 上的 **Insta360 Studio**：匯入素材、設定輸出參數、批次輸出成平面 MP4，等全部輸出完再回報。

> English summary: A Claude Code skill / CLI that drives Insta360 Studio on macOS (via AppleScript, window-only screenshots, Apple Vision OCR and OpenCV template matching) to import a folder of `.insv` 360° clips and batch-export them as flat MP4 (default H.265, 3840×2160, original bitrate). Tested on Insta360 Studio 6.0.8 with the Traditional Chinese UI. Contributions welcome — especially support for other UI languages.

## 能做什麼

- 一次匯入整個資料夾的 `.insv`（雙鏡頭分檔 `_00_`／`_10_` 會自動只送 `_00_`，`.lrv` 不送）
- 只選這一批素材，不會動到媒體庫裡其他舊素材
- 自動設定輸出：編碼（H.265／H.264／ProRes）、解析度、碼率、畫面比例
- 自動設定輸出資料夾
- 按下輸出後持續檢查，全部檔案寫完、大小不再變才算完成
- 失敗時留下最後一張畫面截圖，方便查原因

## 實測效果

環境：Mac mini、macOS 27、Insta360 Studio 6.0.8（繁體中文介面）、3440×1440 非 Retina 螢幕，素材是 Insta360 X4 拍的 `.insv`。

| 測試 | 結果 |
|---|---|
| 單支、只設定不輸出（dry-run） | 正確設成 4K 3840×2160、原始碼率、H.265 |
| 兩支批次、只設定不輸出 | 正確設成 16:9、3840×2160、原始碼率、H.265 |
| 兩支批次實際輸出（52 秒＋3 分 52 秒，1080p） | 1.2 分鐘完成，兩支都是 HEVC 1920×1080、長度完整 |

全程不需要動滑鼠；從匯入到開始輸出大約 30 秒。

## 限制（請先看）

- **只支援 macOS**。
- **沒有自動構圖（Auto Frame）**：Insta360 官方從 Studio **6.0.0** 起移除了這個功能。6.x 只能用預設視角輸出。腳本裡留有 5.x 的自動構圖流程（`--auto-frame auto`），但沒有實測過。
- **目前只在繁體中文介面測過**。其他語言的按鈕文字不同，需要改 `scripts/insta360_auto.py` 裡的文字比對規則，或用校準模式補範本圖（很歡迎幫忙加其他語言）。
- 執行時會接管滑鼠和鍵盤，跑的時候不要碰電腦。
- 為了讓點擊位置穩定，會把 Studio 視窗移到螢幕左上角（80,60），大小設成 1440×932。
- 為了設定輸出資料夾，會關掉 Studio、改它的設定檔 `startup.ini` 再重開（第一次會備份）。

## 安裝

需要：macOS、Python 3.10 以上、Insta360 Studio。

```bash
git clone https://github.com/dumay0420/insta360-auto-editor.git ~/.claude/skills/insta360-auto-editor
```

```bash
~/.claude/skills/insta360-auto-editor/setup.sh
```

`setup.sh` 會在 skill 資料夾裡建立 `.venv`，安裝 OpenCV 和 pyobjc（約 120MB）。

### 權限

執行腳本的程式（Claude Code 所在的 App，或你的終端機）需要兩個權限：

- 系統設定 → 隱私權與安全性 → **輔助使用**
- 系統設定 → 隱私權與安全性 → **螢幕與系統錄音**

打勾後要重開那個程式。可以用 `run.sh check` 確認。

Studio 不在 `/Applications`、Spotlight 也找不到時，設定環境變數：

```bash
export INSTA360_STUDIO_APP="/你的路徑/Insta360 Studio.app"
```

## 使用方法

### 在 Claude Code 裡（推薦）

裝好後直接用講的：

> 幫我把 `/Volumes/SD/DCIM/Camera01` 的 insv 輸出到 `~/Movies/insta360-out`

Claude 會先 dry-run 給你看找到幾支、輸出設定是什麼，你確認後才真的輸出。

### 直接用指令

```bash
cd ~/.claude/skills/insta360-auto-editor
```

檢查權限、Studio 版本、範本：

```bash
./run.sh check
```

先試跑（只設定好輸出視窗，不真的輸出）：

```bash
./run.sh run "/素材資料夾" --out "/輸出資料夾" --dry-run
```

正式輸出：

```bash
./run.sh run "/素材資料夾" --out "/輸出資料夾"
```

常用參數：

| 參數 | 預設 | 說明 |
|---|---|---|
| `--codec` | `H.265` | `H.264`、`H.265`、`ProRes 422`、`ProRes 422 LT` |
| `--width` | `3840` | 寬度，高度依比例自動算。單支輸出只有 1920／2560／3840 |
| `--quality` | `原始` | `原始` 或 `建議`（碼率） |
| `--ratio` | `16:9` | `16:9`、`9:16`、`4:3`、`3:4`、`1:1`、`2.35:1` |
| `--auto-frame` | `skip` | `skip` 跳過；`auto` 有就做；`require` 沒有就停（只有 Studio 5.x 有） |
| `--dry-run` | | 設定好就停，不輸出 |
| `--export-timeout` | 12 小時 | 等輸出完成的上限（秒） |

### 校準模式

按鈕用文字辨識找不到時（例如不同語言介面、Studio 改版），可以手動框選按鈕存成範本圖：

```bash
./run.sh calibrate export_button
```

照提示先把按鈕顯示在畫面上，按 Enter，再用滑鼠框住按鈕。範本會記下當時螢幕的縮放倍率，換解析度也找得到。測試：

```bash
./run.sh calibrate --test export_button
```

### 探測介面

Studio 改版後先跑這個，看選單、按鈕、畫面文字有沒有變：

```bash
./run.sh probe
```

## 運作原理

Insta360 Studio 是 Qt／QML 自己畫的介面，macOS 的輔助使用功能幾乎抓不到按鈕，所以混合四種方法：

1. **AppleScript（System Events）**：點選單列（例如「檔案 → 導出」）、切換視窗、按鍵。
2. **只拍 Studio 視窗的截圖**（`screencapture -R`，不拍整個螢幕）。
3. **macOS Vision 文字辨識**：在截圖裡找按鈕文字的位置。小字會先放大再辨識。
4. **OpenCV 範本比對**：校準過的按鈕優先用範本找，多種大小比對。

輸出資料夾不靠 GUI 設定，而是改 Studio 的 `~/Library/Application Support/Insta360/Insta360 Studio/startup.ini` 裡的 `export_location`。

檔案結構：

```
SKILL.md                 Claude Code 讀的說明
run.sh / setup.sh        執行、安裝
scripts/insta360_auto.py 主程式（check / probe / calibrate / run）
scripts/studio_vision.py 截圖、文字辨識、範本比對、點擊
templates/               校準範本（各自產生，不進 git）
```

## 安全設計

- 不刪任何素材或輸出檔。
- 右鍵選單裡有「刪除本機檔案」，所以腳本只點文字比對到的項目，不用固定座標點選單。
- 只截 Studio 視窗的範圍。

## 歡迎一起改

這是一個自己用的小工具，一定還有很多不足。很歡迎開 issue 或發 PR，特別是：

- 其他介面語言（英文、簡中、日文…）的文字比對規則
- 其他 Studio 版本的實測結果（尤其 5.x 的自動構圖流程）
- Retina 螢幕、多螢幕的實測
- 更穩的輸出進度判斷

改之前可以先跑 `./run.sh probe` 把你的介面狀況貼在 issue 裡，方便對照。

## 授權

MIT License。本專案和 Insta360 官方無關，Insta360 是 Arashi Vision Inc. 的商標。
