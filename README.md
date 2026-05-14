# 全國聯合考 PDF 轉 Anki 卡片工具

這個專案可以把放在 `input/` 資料夾裡的全國聯合考 PDF，轉成 Anki 可以匯入的 `.apkg` 牌組 。

產生的卡片形式是：

- 正面：題目圖片
- 背面：題目圖片 + 答案圖片

不需要會寫程式。照著下面步驟，一行一行複製指令即可。

## 你需要先安裝什麼

### 1. 安裝 Anki

Anki 是用來讀 `.apkg` flashcard 牌組的軟體。

1. 打開瀏覽器。
2. 到 Anki 官方網站：[https://apps.ankiweb.net](https://apps.ankiweb.net)
3. 下載 Windows 版本。
4. 安裝完成後，先不用打開也可以。

如果你的電腦已經有 Anki，可以跳過這一步。

### 2. 安裝 Windows Terminal

Windows Terminal 是比較好用的命令列視窗。你可以把它想成「輸入指令的 App」。

1. 在 Windows 桌面左下角按「開始」。
2. 搜尋 `Microsoft Store`，打開 Microsoft Store。
3. 在 Microsoft Store 搜尋 `Windows Terminal`。
4. 點選 Microsoft 出版的 Windows Terminal。
5. 按「取得」或「安裝」。

如果你的電腦已經有 Windows Terminal，也可以跳過這一步。

### 3. 安裝 PowerShell

PowerShell 是我們要在 Windows Terminal 裡使用的指令環境。

1. 打開 Microsoft Store。
2. 搜尋 `PowerShell`。
3. 點選 Microsoft 出版的 PowerShell。
4. 按「取得」或「安裝」。

如果你的電腦已經有 PowerShell，也可以跳過這一步。

### 4. 打開 Windows Terminal

1. 在 Windows 桌面左下角按「開始」。
2. 搜尋 `Terminal`。
3. 打開「Windows Terminal」。
4. 如果畫面上方顯示的是 `PowerShell`，就可以繼續。
5. 如果不是 PowerShell，按上方分頁旁邊的小箭頭，選 `PowerShell`。

### 5. 安裝 uv

`uv` 是這個專案用來自動安裝 Python 和需要套件的工具。

在 Windows Terminal 的 PowerShell 裡，複製下面這整行，貼上後按 Enter：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

安裝完成後，請關掉 Windows Terminal，再重新打開一次。

重新打開後，輸入：

```powershell
uv --version
```

如果有看到類似 `uv 0.x.x` 的文字，就代表成功。

## 第一次使用：準備專案

### 1. 下載這個專案

在這個專案的 GitHub 網頁上：

1. 點綠色的 `Code` 按鈕。
2. 點 `Download ZIP`。
3. 下載後解壓縮。
4. 建議把解壓縮後的資料夾放在桌面。

例如資料夾可能會長這樣：

```text
C:\Users\你的使用者名稱\Desktop\rad-test-main
```

實際名稱以你解壓縮後看到的資料夾名稱為準。

### 2. 進入專案資料夾

打開 Windows Terminal，確認目前是 PowerShell。

如果你的資料夾叫 `rad-test-main`，請輸入：

```powershell
cd "$HOME\Desktop\rad-test-main"
```

你可以用這個指令確認目前資料夾裡有沒有專案檔案：

```powershell
dir
```

如果有看到 `create_anki_deck.py`、`pyproject.toml`、`input`，就代表位置正確。

### 3. 安裝專案需要的東西

在專案資料夾裡輸入：

```powershell
uv sync
```

第一次會花一點時間，之後會快很多。

## 每次要轉 PDF 時怎麼做

### 1. 把 PDF 放進 input 資料夾

把全國聯合考的檔案轉成 PDF，複製到專案裡的 `input/` 資料夾。

例如：

```text
rad-test/
  input/
    你的測驗.pdf
```

### 2. 執行轉換

回到 Windows Terminal，確認你還**在專案資料夾裡 (非常重要)**，然後輸入：

```powershell
uv run create_anki_deck.py
```

如果成功，你會看到類似：

```text
找到 50 個問題和 50 個答案。
成功建立 50 張卡片。
```

### 3. 找到產生的 Anki 檔案

轉好的 `.apkg` 檔案會出現在專案裡的 `output/` 資料夾。

例如：

```text
rad-test/
  output/
    你的測驗.apkg
```

### 4. 匯入 Anki

1. 點擊 `.apkg` 檔案，就會直接匯入 Anki。

## 資料夾說明

```text
rad-test/
  create_anki_deck.py   主要程式
  input/                放要轉換的 PDF
  output/               放產生的 .apkg Anki 牌組
  tests/                程式測試，一般使用者不用管
  pyproject.toml        專案套件設定
  uv.lock               鎖定套件版本，讓環境比較穩定
```

## 常見問題

### Windows Terminal 找不到 uv

請先關掉 Windows Terminal，再重新打開一次，然後輸入：

```powershell
uv --version
```

如果還是不行，重新執行安裝 uv 的指令。

### Windows Terminal 說找不到 create_anki_deck.py

代表你目前不在專案資料夾裡。

請先用 `cd` 回到專案資料夾，例如：

```powershell
cd "$HOME\Desktop\rad-test-main"
```

再執行：

```powershell
uv run create_anki_deck.py
```

### 程式說 input 裡沒有 PDF

請確認你的 PDF 已經放進 `input/` 資料夾，而且副檔名是 `.pdf`。

### 產生的卡片不是 50 張

程式預期每份 PDF 有 50 張卡。如果不是 50 張，通常代表 PDF 裡的題目或答案標記沒有被正確辨識。

程式會列出缺少題目或缺少答案的編號，請回頭檢查原始 PDF。

### 要不要碰 tests 資料夾？

一般使用者不用碰。

`tests/` 是給維護程式的人用的，確保以後修改程式時，不會不小心改壞 Anki ID、背面模板或錯誤偵測。

## 給會開發的人

執行測試：

```powershell
uv run pytest
```

同步依賴：

```powershell
uv sync
```

新增一般套件：

```powershell
uv add 套件名稱
```

新增開發用套件：

```powershell
uv add --dev 套件名稱
```

注意：PDF 函式庫使用 `PyMuPDF` / `pymupdf`。不要安裝 PyPI 上另一個不相關的 `fitz` 套件。

## 官方參考連結

- Anki：[https://apps.ankiweb.net](https://apps.ankiweb.net)
- Windows Terminal：[Microsoft 官方文件](https://learn.microsoft.com/windows/terminal/install)
- PowerShell：[Microsoft 官方文件](https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows)
- uv：[官方安裝文件](https://github.com/astral-sh/uv/blob/main/docs/getting-started/installation.md)
