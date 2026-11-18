---
name: insta360-auto-editor
description: 自動操作 macOS 上的 Insta360 Studio，把一個資料夾裡的 Insta360（X5/X4/X3…）.insv 全景素材匯入，再批次輸出成平面 MP4（預設 H.265、3840x2160、原始碼率）。當使用者說「幫我把這個資料夾的 insv 輸出」「Insta360 批次匯出」「全景影片轉平面」「Insta360 Studio 自動化」或給一個裝 .insv 的資料夾要處理時使用。也用於校準按鈕範本（calibrate）與探測 Studio 介面（probe）。
---

# Insta360 Studio 自動剪輯

用 AppleScript（選單、視窗）＋ 只拍 Studio 視窗的截圖 ＋ macOS Vision 文字辨識 ＋ OpenCV 範本比對，操作 Insta360 Studio。

下面的 `R` 代表這個 skill 資料夾裡的 `run.sh`（例如 `~/.claude/skills/insta360-auto-editor/run.sh`）。

## 第一次使用

1. 沒有 `.venv` 就先跑 `setup.sh`（建立 Python 環境、裝 OpenCV 和 pyobjc）。
2. 跑 `R check`。權限不夠會打開系統設定，請使用者把「執行腳本的程式」（Claude 或 終端機）在「輔助使用」「螢幕與系統錄音」打勾，然後重開那個程式。
3. Studio 不在 `/Applications` 也找不到時，設定環境變數 `INSTA360_STUDIO_APP=/路徑/Insta360 Studio.app`。

## 標準流程

1. 先 dry-run（只設定、不輸出），確認能正確選片和設定：
   `R run "素材資料夾" --out "輸出資料夾" --dry-run`
2. 跟使用者回報找到幾支、輸出到哪、設定是什麼，確認後再正式跑。
3. 正式跑（在背景跑，可能很久）：`R run "素材資料夾" --out "輸出資料夾"`
4. 回報輸出檔案清單、大小、花費時間。

常用參數：`--codec H.265|H.264|ProRes 422`、`--width 3840`、`--quality 原始|建議`、`--ratio 16:9|9:16|1:1…`、`--auto-frame skip|auto|require`（預設 skip）。

## run 實際做的事

1. 列出資料夾的 `.insv`（雙鏡頭分檔 `_00_`／`_10_` 只送 `_00_`，Studio 會自動配對；`.lrv` 不送）。
2. 輸出路徑：Studio 的「更改」會開系統資料夾視窗，很難自動操作，所以改用 `~/Library/Application Support/Insta360/Insta360 Studio/startup.ini` 的 `export_location`。要改時會先關掉 Studio（它會自動存檔）、改完再開。第一次改會備份成 `startup.ini.bak-insta360-auto-editor`。
3. 匯入：`open -a Studio 檔案…`，等同拖放；等媒體庫出現每支的短名稱（`VID_20250101_101349_00_173.insv` 顯示成 `VID_173`）。
4. 自動構圖：**Studio 6.0.0 起官方已移除「自動構圖（Auto Frame）」**，所以預設跳過。`--auto-frame auto` 會試著右鍵找「開始自動構圖」，只有 5.x 舊版才有，這條路徑沒實測過。
5. 選片：第一支一般點，其他 Cmd+點。只選這批，不會選到媒體庫裡其他舊素材。
6. 檔案 → 導出，設定：
   - 多支（批次視窗）：比例選單、寬度數字欄位（高度自動算）、碼率品質、編碼格式。
   - 單支（單檔視窗）：解析度選單（最高 4K-3840x2160）、影格率（碼率）、編碼格式。
7. 按黃色「輸出」，每 10 秒檢查：輸出資料夾裡每支都出現 `.mp4`、大小不再變、輸出視窗已關，就算完成。

## 校準模式（換螢幕、換版本、找不到按鈕時）

文字辨識找不到按鈕時，用範本圖輔助。範本優先，找不到再用文字。

```
R calibrate                  # 依序校準全部目標
R calibrate export_button    # 只校準一個
R calibrate --test export_button
```

每個目標會先提示要把什麼顯示在畫面上，按 Enter 後用滑鼠框選那個按鈕（macOS 內建框選截圖，Esc 跳過）。範本記下當時螢幕的縮放倍率，比對時自動換算並試多種大小。這一步需要使用者本人操作滑鼠，請使用者在終端機自己跑。

目標：`export_button`（輸出視窗黃色「輸出」）、`auto_frame_menu`、`auto_frame_done`（後兩個只有 5.x 有）。

## 探測介面（Studio 改版後先跑）

`R probe` 印出選單列所有項目、輔助使用樹抓得到的按鈕、畫面上的文字和座標。

## 已知坑（6.0.8 實測）

- 程序名稱是 `studio-main`，不是 `Insta360 Studio`；bundle id `com.insta360.studio`。
- 輔助使用樹幾乎抓不到東西，所以靠截圖＋文字辨識。
- 非 Retina 螢幕字太小 Vision 會漏字，截圖會先放大到約 3 倍再辨識。
- 文字辨識常把「輸出」認成「翰出」、「編」認成「编」，比對用的 regex 已放寬。
- 右鍵選單、下拉選單是浮在視窗上的小視窗，`screencapture -l` 拍不到，改用 `-R` 只拍 Studio 視窗那一塊。
- 輸出視窗按 Esc 關不掉，要點左上紅點。
- 數字欄位不吃 Cmd+A，要先按 → 到最後再 Backspace 刪光。寬度超過 16000 會跳警告框。
- 每次會把 Studio 視窗擺到固定位置（左上 80,60、1440x932），點擊才準。
- 右鍵選單最下面是「刪除本機檔案」，腳本只點文字比對到的項目，不要改成用固定座標點右鍵選單。

## 安全規則

- 不刪任何素材或輸出檔；不點「刪除本機檔案」「從 Studio 中移除」。
- 只截 Studio 視窗的範圍，不截整個螢幕。
- 跑之前先 dry-run，並跟使用者確認輸出資料夾。
