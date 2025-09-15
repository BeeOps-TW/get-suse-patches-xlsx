# SUSE Patches Collector

## 簡介
用 Python 從 **SUSE Customer Center (SCC)** 前端 API 取得 **important / critical** 修補資訊，依 `issued_at` 由新到舊排序，支援以 `--since` 篩選時間，並輸出為 **Excel (.xlsx)**。同時會為每筆修補再取詳細資訊（`ibs_id` 與 `description`），分別輸出為 **Patch Detail** 與 **CVE or Issues Fixed** 欄位。`Release` 欄位只顯示日期（格式 `YYYY/MM/DD`）。

---

## 參數介紹

| 參數 | 是否必填 | 說明 | 預設值 | 範例 |
|---|:--:|---|---|---|
| `--product-names` | 否 | 產品名稱 | `SUSE Linux Enterprise Server LTSS` | `"SUSE Linux Enterprise Server"` |
| `--product-versions` | 否 | 產品版本 | `12 SP5` | `"15 SP5"` |
| `--product-architectures` | 否 | CPU 架構 | `x86_64` | `aarch64` |
| `--since` | 否 | 只保留此時間（含）之後的資料；接受 `YYYY-MM-DD`、`YYYY/MM/DD` 或 ISO8601（如 `2025-09-10T00:00:00Z`）；以 **UTC** 比對 | 無 | `2025-06-01` |
| `-o`, `--output` | 否 | 輸出檔名（Excel） | `suse_patches.xlsx` | `sles15sp5_patches.xlsx` |

> 備註：腳本會固定抓取 `severity=important` 與 `severity=critical` 兩種等級。

---

## 使用方法

安裝套件：
```bash
pip install requests pandas openpyxl
```

基本用法（使用預設產品與版本）：
```bash
python main.py
```

指定產品與版本：
```bash
python main.py   --product-names "SUSE Linux Enterprise Server"   --product-versions "15 SP5"   --product-architectures x86_64   -o sles15sp5_patches.xlsx
```

只取特定時間（含）之後的資料（UTC 比對）：
```bash
# 以日期為準（當日 00:00:00Z 之後）
python main.py --since 2025-01-01

# 指定完整時間（UTC）
python main.py --since 2025-09-10T00:00:00Z
```
