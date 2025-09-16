#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import argparse
from typing import Dict, List, Optional
import requests
import pandas as pd
from datetime import datetime, timezone

BASE_URL = "https://scc.suse.com/api/frontend/patch_finder/search/perform.json"
DETAIL_URL = "https://scc.suse.com/api/frontend/patch_finder/patches/{id}"

SEVERITIES = ["important", "critical"]

HEADERS = {
    "User-Agent": "patch-collector/1.3 (+https://example.local)"
}

OUTPUT_XLSX = "suse_patches.xlsx"


def parse_issued_at(s: str) -> datetime:
    """將 API 的 ISO8601 issued_at 轉成 timezone-aware datetime（UTC）。空值回傳 datetime.min (naive)。"""
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        # 常見格式為 '...Z'，轉為 +00:00 供 fromisoformat 使用
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        # 若無 tzinfo，視為 UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def parse_user_datetime(s: Optional[str]) -> Optional[datetime]:
    """
    解析使用者輸入的 --since 值：
      - 'YYYY-MM-DD' 或 'YYYY/MM/DD' -> 視為 UTC 當天 00:00:00
      - 完整 ISO8601（可含 Z 或偏移） -> 轉成 UTC
    回傳 timezone-aware datetime（UTC）或 None。
    """
    if not s:
        return None
    s = s.strip()
    # 日期型 (無時間)
    if len(s) == 10 and (s[4] in "-/" and s[7] in "-/"):
        y, m, d = s.replace("/", "-").split("-")
        dt = datetime(int(y), int(m), int(d), 0, 0, 0, tzinfo=timezone.utc)
        return dt
    # 其他視為 ISO 8601
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        raise ValueError("無法解析 --since，請使用 YYYY-MM-DD / YYYY/MM/DD 或 ISO8601（如 2025-09-10T12:00:00Z）。")


def format_release_date_iso_to_ymd(s: str) -> str:
    """將 'YYYY-MM-DD...' 轉成 'YYYY/MM/DD'（只取日期部分，避免時區換日影響顯示）。"""
    if not s or len(s) < 10:
        return ""
    y, m, d = s[:10].split("-")
    return f"{y}/{m}/{d}"


def fetch_all_pages_for_severity(
    severity: str,
    common_params: Dict[str, str],
    sleep_between_pages: float = 0.15,
    retries: int = 3,
    timeout: int = 30,
) -> List[Dict]:
    """抓取指定 severity 的所有分頁 hits，移除 special_product_names 並加上 severity。"""
    all_hits: List[Dict] = []

    def _request_with_retry(url: str, params: Dict = None):
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_err = e
                time.sleep(0.5 * attempt)
        raise last_err

    # 第 1 頁
    params = {**common_params, "severity": severity, "page": 1}
    data = _request_with_retry(BASE_URL, params=params)
    total_pages = int(data.get("meta", {}).get("total_pages", 1))

    def _consume(data_obj):
        hits = data_obj.get("hits", []) or []
        for item in hits:
            item.pop("special_product_names", None)
            item["severity"] = severity
        return hits

    all_hits.extend(_consume(data))

    # 其餘頁
    for page in range(2, total_pages + 1):
        params["page"] = page
        data = _request_with_retry(BASE_URL, params=params)
        all_hits.extend(_consume(data))
        time.sleep(sleep_between_pages)

    return all_hits


def fetch_detail_fields(patch_id: str, retries: int = 3, timeout: int = 30) -> Dict[str, str]:
    """從詳細 API 取得 ibs_id 與 description。"""
    url = DETAIL_URL.format(id=patch_id)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return {
                "ibs_id": str(data.get("ibs_id", "") if data.get("ibs_id", "") is not None else ""),
                "description": data.get("description", ""),
            }
        except Exception as e:
            last_err = e
            time.sleep(0.5 * attempt)
    print(f"取得 {patch_id} 詳細資訊失敗：{last_err}")
    return {"ibs_id": "", "description": ""}


def main():
    ap = argparse.ArgumentParser(description="Collect SUSE patches and export to XLSX.")
    ap.add_argument("--product-names", default="SUSE Linux Enterprise Server LTSS",
                    help="產品名稱（例：'SUSE Linux Enterprise Server LTSS'）")
    ap.add_argument("--product-versions", default="12 SP5",
                    help="產品版本（例：'12 SP5'）")
    ap.add_argument("--product-architectures", default="x86_64",
                    help="架構（預設 x86_64）")
    ap.add_argument("--since",
                    help="只保留此時間(含)之後的資料。接受 YYYY-MM-DD / YYYY/MM/DD 或 ISO8601（如 2025-09-10T12:00:00Z）")
    ap.add_argument("-o", "--output", default=OUTPUT_XLSX, help="輸出的 XLSX 檔名")
    args = ap.parse_args()

    common_params = {
        "product_architectures": args.product_architectures,
        "product_names": args.product_names,
        "product_versions": args.product_versions,
    }

    since_dt = parse_user_datetime(args.since) if args.since else None
    if since_dt:
        print(f"篩選條件：issued_at >= {since_dt.isoformat()} (UTC)")

    combined: List[Dict] = []

    # 收集 important + critical
    for sev in SEVERITIES:
        hits = fetch_all_pages_for_severity(sev, common_params=common_params)
        print(f"[{sev}] 收到 {len(hits)} 筆")
        combined.extend(hits)

    # 先依 issued_at 由新到舊排序
    combined.sort(key=lambda x: parse_issued_at(x.get("issued_at")), reverse=True)
    print(f"合併後總計 {len(combined)} 筆")

    # 先過濾，再打細節 API（效能較佳）
    if since_dt:
        before = len(combined)
        combined = [it for it in combined if parse_issued_at(it.get("issued_at")) >= since_dt]
        print(f"篩選後剩 {len(combined)} 筆（原 {before} 筆）")

    # 逐筆補上 ibs_id 與 description（Patch Detail / CVE or Issues Fixed）
    for item in combined:
        pid = item.get("id")
        det = fetch_detail_fields(str(pid)) if pid else {"ibs_id": "", "description": ""}
        item["_detail_ibs_id"] = det.get("ibs_id", "")
        item["_detail_description"] = det.get("description", "")

    # 準備輸出欄位（依指定順序與命名）
    rows = []
    for it in combined:
        prods = it.get("product_friendly_names", [])
        prods_str = "; ".join(map(str, prods)) if isinstance(prods, list) else (str(prods) if prods is not None else "")
        archs = it.get("product_architectures", [])
        archs_str = "; ".join(map(str, archs)) if isinstance(archs, list) else (str(archs) if archs is not None else "")

        row = {
            "Severity": it.get("severity", ""),
            "Patch name": it.get("title", ""),
            "Patch Detail": it.get("_detail_ibs_id", ""),                # 來自詳細 API 的 ibs_id
            "Product(s)": prods_str,
            "Arch": archs_str,
            "Release": format_release_date_iso_to_ymd(it.get("issued_at", "")),
            "CVE or Issues Fixed": it.get("_detail_description", ""),    # 來自詳細 API 的 description
        }
        rows.append(row)

    # 輸出成 Excel
    df = pd.DataFrame(rows, columns=[
        "Severity",
        "Patch name",
        "Patch Detail",
        "Product(s)",
        "Arch",
        "Release",
        "CVE or Issues Fixed",
    ])
    df.to_excel(args.output, index=False)
    print(f"已輸出：{args.output}")


if __name__ == "__main__":
    main()
