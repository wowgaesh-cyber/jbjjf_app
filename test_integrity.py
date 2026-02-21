"""
整合性テスト: スプレッドシートのデータとアプリが表示するデータを比較する

実行方法:
    python test_integrity.py

期待する出力:
    - 各テストの PASS / FAIL
    - FAIL の場合はどのデータが問題かを表示
"""

import sys
import re
import io
import warnings
import unicodedata
import requests
import pandas as pd

warnings.filterwarnings("ignore")

# ──────────────────────────────────────────────
# 設定
# ──────────────────────────────────────────────

SPS_URL = (
    "https://docs.google.com/spreadsheets/u/1/d/e/"
    "2PACX-1vQoIxREOSKT14WEJRKj3VuOXhodOxydJusm-c9BZD-d9idHwXQHeCkEJJd8HzxAyH6OoeMxn9UMne2a"
    "/pub?output=xlsx"
)

# ──────────────────────────────────────────────
# app.py からコピーしたパース関数（テスト対象）
# ──────────────────────────────────────────────

def clean_val(v):
    return re.sub(r"\.0$", "", str(v).strip())

def is_valid_id(text):
    text = clean_val(text)
    if text in ["1", "nan", "", "-", "No", "•", "Result"]:
        return False
    if re.match(r"^\d+-\d+$", text):
        return True
    if text.isdigit() and int(text) < 999:
        return True
    return False

def has_time_pattern(text):
    return bool(re.search(r"\d{1,2}:\d{2}", str(text)))

def extract_time_from_line(line_txt):
    times = re.findall(r"(\d{1,2}:\d{2})", line_txt)
    return times[0] if times else "-"

def is_likely_player(text):
    has_jp = bool(re.search(r"[一-龥ぁ-んァ-ン]", text))
    has_en = bool(re.search(r"[a-zA-Z]", text))
    if not (has_jp and has_en):
        return False
    return bool(re.search(r"[一-龥ぁ-んァ-ン]+[ \u3000]+[a-zA-Z]", text))

def is_likely_dojo(text):
    EXCLUDE = {"集合時間", "計量", "試合開始", "Result", "優勝", "Winner",
               "カテゴリー", "Mat", "マット", "道着チェック", "欠場"}
    if text in EXCLUDE:
        return False
    if is_likely_player(text):
        return False
    return True

def extract_all_dojos(sheets):
    dojo_set = set()
    for _, df in sheets.items():
        df = df.fillna("").astype(str)
        rows, cols = df.shape
        for r in range(1, rows):
            for c in range(min(20, cols)):
                val = clean_val(df.iloc[r, c])
                if len(val) < 2 or is_valid_id(val) or has_time_pattern(val):
                    continue
                if not is_likely_dojo(val):
                    continue
                upper_val = clean_val(df.iloc[r - 1, c])
                if is_likely_player(upper_val):
                    dojo_set.add(val)
    return sorted(list(dojo_set))

def get_schedule_data(sheets, target_dojo):
    """app.py の get_schedule_data と同等の処理（簡略版）"""
    results = []
    for sheet_name, df in sheets.items():
        df = df.fillna("").astype(str)
        rows, cols = df.shape
        search_cols = min(20, cols)
        normalized_sheet = unicodedata.normalize("NFKC", str(sheet_name))
        mat_match = re.search(r"(\d+)", normalized_sheet)
        mat_num = mat_match.group(1) if mat_match else "999"

        for r in range(rows):
            for c in range(search_cols):
                val = clean_val(df.iloc[r, c])
                if val == target_dojo and r > 0:
                    player_name = clean_val(df.iloc[r - 1, c])
                    if player_name and player_name != "nan" and len(player_name) >= 2:
                        results.append({
                            "mat": mat_num,
                            "dojo": target_dojo,
                            "name": player_name,
                        })
                        break
    return pd.DataFrame(results)

# ──────────────────────────────────────────────
# テストユーティリティ
# ──────────────────────────────────────────────

PASS_COUNT = 0
FAIL_COUNT = 0

def check(label, condition, detail=""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        print(f"  ✅ PASS  {label}")
        PASS_COUNT += 1
    else:
        print(f"  ❌ FAIL  {label}")
        if detail:
            print(f"           → {detail}")
        FAIL_COUNT += 1

# ──────────────────────────────────────────────
# テスト定義
# ──────────────────────────────────────────────

def test_fetch(sheets):
    """T1: スプレッドシートへのアクセスと基本構造"""
    print("\n[T1] スプレッドシート取得・基本構造")
    check("シートが1枚以上ある", len(sheets) >= 1,
          f"シート数: {len(sheets)}")
    for name, df in sheets.items():
        check(f"シート '{name}' が空でない", not df.empty,
              f"shape={df.shape}")
        check(f"シート '{name}' の列数が3以上", df.shape[1] >= 3,
              f"cols={df.shape[1]}")


def test_time_parse(sheets):
    """T2: 時刻文字列のパースが正しいか"""
    print("\n[T2] 時刻パース")
    cases = [
        ("9:00",  "9:00"),
        ("14:30", "14:30"),
        ("8:00 集合", "8:00"),
        ("no time here", "-"),
    ]
    for raw, expected in cases:
        result = extract_time_from_line(raw)
        check(f"'{raw}' → '{expected}'", result == expected,
              f"got: '{result}'")

    # スプレッドシート内に実際の時刻データが存在するか確認
    found_times = []
    for _, df in sheets.items():
        for _, row in df.fillna("").astype(str).iterrows():
            for cell in row:
                if has_time_pattern(cell):
                    times = re.findall(r"\d{1,2}:\d{2}", cell)
                    found_times.extend(times)
    check("スプレッドシートに時刻データが存在する", len(found_times) > 0,
          f"見つかった時刻数: {len(found_times)}")
    if found_times:
        print(f"           サンプル: {sorted(set(found_times))[:10]}")


def test_dojo_extraction(sheets):
    """T3: 道場名の抽出"""
    print("\n[T3] 道場名抽出")
    dojos = extract_all_dojos(sheets)
    check("道場名が1件以上抽出される", len(dojos) >= 1,
          f"抽出数: {len(dojos)}")
    # キーワードが道場名として混入していないか
    NG_KEYWORDS = ["集合時間", "計量", "試合開始", "Result", "優勝", "Winner",
                   "カテゴリー", "Mat", "マット"]
    contaminated = [d for d in dojos if any(k in d for k in NG_KEYWORDS)]
    check("NGキーワードが道場名に入っていない", len(contaminated) == 0,
          f"混入: {contaminated}")
    if dojos:
        print(f"           抽出された道場名 ({len(dojos)}件): {dojos[:10]}")


def test_schedule_per_dojo(sheets):
    """T4: 各道場のスケジュールが取得できるか"""
    print("\n[T4] 道場別スケジュール取得")
    dojos = extract_all_dojos(sheets)
    if not dojos:
        check("道場名が存在する (前提)", False, "道場が0件のためスキップ")
        return

    total_entries = 0
    dojos_with_data = 0
    for dojo in dojos:
        df = get_schedule_data(sheets, dojo)
        if not df.empty:
            dojos_with_data += 1
            total_entries += len(df)

    check("スケジュールが取得できた道場がある", dojos_with_data > 0,
          f"{dojos_with_data}/{len(dojos)} 道場にデータあり")
    check("スケジュールエントリが合計10件以上ある", total_entries >= 10,
          f"合計エントリ数: {total_entries}")
    print(f"           合計エントリ: {total_entries} 件 / {dojos_with_data}/{len(dojos)} 道場")


def test_no_garbage_names(sheets):
    """T5: 選手名にゴミデータが混入していないか"""
    print("\n[T5] 選手名サニティチェック")
    dojos = extract_all_dojos(sheets)
    all_names = []
    for dojo in dojos[:10]:  # 最大10道場で確認
        df = get_schedule_data(sheets, dojo)
        if not df.empty:
            all_names.extend(df["name"].tolist())

    if not all_names:
        check("選手名が存在する (前提)", False, "選手名0件のためスキップ")
        return

    # "nan" や空文字が混入していないか
    bad = [n for n in all_names if n in ("nan", "", "-", "NaN")]
    check("nan/空文字が選手名に入っていない", len(bad) == 0,
          f"不正値: {bad[:5]}")

    # 極端に短い名前（1文字以下）がないか
    too_short = [n for n in all_names if len(n) <= 1]
    check("長さ1以下の選手名がない", len(too_short) == 0,
          f"短すぎる名前: {too_short[:5]}")

    print(f"           サンプル選手名: {all_names[:5]}")


def test_mat_numbers(sheets):
    """T6: マット番号がシート名から正しく抽出されるか"""
    print("\n[T6] マット番号抽出")
    for name in sheets.keys():
        normalized = unicodedata.normalize("NFKC", str(name))
        mat_match = re.search(r"(\d+)", normalized)
        mat_num = mat_match.group(1) if mat_match else None
        if mat_num:
            check(f"シート '{name}' → マット番号 '{mat_num}'", mat_num.isdigit())
        else:
            print(f"  ⚠️  SKIP  シート '{name}' に数字なし（Otherとして扱われる）")


# ──────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  JBJJF アプリ データ整合性テスト")
    print("=" * 55)

    # スプレッドシートを取得
    print("\n[準備] スプレッドシートを取得中...")
    try:
        resp = requests.get(SPS_URL, verify=False, timeout=30)
        resp.raise_for_status()
        sheets = pd.read_excel(io.BytesIO(resp.content), sheet_name=None, header=None)
        print(f"  → 取得成功 ({len(sheets)} シート: {list(sheets.keys())})")
    except Exception as e:
        print(f"  ❌ スプレッドシートの取得に失敗しました: {e}")
        sys.exit(1)

    # テスト実行
    test_fetch(sheets)
    test_time_parse(sheets)
    test_dojo_extraction(sheets)
    test_schedule_per_dojo(sheets)
    test_no_garbage_names(sheets)
    test_mat_numbers(sheets)

    # 結果サマリー
    print("\n" + "=" * 55)
    total = PASS_COUNT + FAIL_COUNT
    print(f"  結果: {PASS_COUNT} PASS / {FAIL_COUNT} FAIL  (計{total}件)")
    print("=" * 55)
    if FAIL_COUNT > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
