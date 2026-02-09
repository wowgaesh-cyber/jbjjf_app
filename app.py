import streamlit as st
import pandas as pd
import requests
import io
import warnings
import re
import unicodedata  # これが抜けていました！
import urllib.parse
from datetime import datetime, timedelta, timezone
import streamlit.components.v1 as components

warnings.filterwarnings('ignore')

# ページ設定 (タイトルとアイコンのみ)
st.set_page_config(
    page_title="JBJJF Timetable",
    page_icon="🥋",
    layout="wide"
)

# --- 帯色判定ロジック ---
def get_belt_color(category_text):
    text = str(category_text)
    if "白帯" in text or "White" in text:
        return "#e0e0e0" # 白
    elif "青帯" in text or "Blue" in text:
        return "#0055af" # 青
    elif "紫帯" in text or "Purple" in text:
        return "#6a0dad" # 紫
    elif "茶帯" in text or "Brown" in text:
        return "#654321" # 茶
    elif "黒帯" in text or "Black" in text:
        return "#333333" # 黒
    elif "灰" in text or "Gray" in text:
        return "#808080" # キッズ灰
    elif "黄" in text or "Yellow" in text:
        return "#ffd700" # キッズ黄
    elif "橙" in text or "Orange" in text:
        return "#ffa500" # キッズ橙
    elif "緑" in text or "Green" in text:
        return "#008000" # キッズ緑
    else:
        return "#ff4b4b" # デフォルト

# --- データ取得ロジック ---
SPS_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSXX7C31vhQh9qBPo_Qs6pKE8QfRiPiAD9HYgWQWLVHwGxesIFr2417ieMHLqMtouZJyImsUmuKLUeK/pub?output=xlsx"

@st.cache_data(ttl=60)
def load_data_and_title():
    try:
        resp = requests.get(SPS_URL, verify=False, timeout=30)
        
        extracted_title = "JBJJF Tournament"
        if "Content-Disposition" in resp.headers:
            cd = resp.headers["Content-Disposition"]
            matches = re.findall(r"filename\*=UTF-8''(.+)", cd)
            if matches:
                filename = urllib.parse.unquote(matches[0])
            else:
                matches_simple = re.findall(r'filename="(.+?)"', cd)
                filename = matches_simple[0] if matches_simple else "JBJJF Tournament"
            extracted_title = re.sub(r'\.xlsx$', '', filename, flags=re.IGNORECASE)

        dfs = pd.read_excel(io.BytesIO(resp.content), sheet_name=None, header=None)
        return dfs, extracted_title
    except:
        return None, "JBJJF Tournament"

def clean_val(v): return re.sub(r'\.0$', '', str(v).strip())

def is_valid_id(text):
    text = clean_val(text)
    if text in ["1", "nan", "", "-", "No", "•", "Result"]: return False
    if re.match(r'^\d+-\d+$', text): return True
    if text.isdigit() and int(text) < 999: return True
    return False

def extract_time_from_line(line_txt):
    times = re.findall(r'(\d{1,2}:\d{2})', line_txt)
    return times[0] if times else "-"

def has_time_pattern(text): return bool(re.search(r'\d{1,2}:\d{2}', str(text)))
def has_time_nearby(df, r, c, rows, cols):
    for dr in range(0, 4):
        curr_r = r + dr; 
        if curr_r >= rows: continue
        for dc in range(-1, 3):
            curr_c = c + dc; 
            if 0 <= curr_c < cols:
                val = str(df.iloc[curr_r, curr_c])
                if has_time_pattern(val) or "集合" in val: return True
    return False

def collect_times_vertical_strip(df, id_row, id_col):
    rows, cols = df.shape; found_times = []
    target_cols = [id_col - 1, id_col - 2]
    for c in target_cols:
        if c < 0: continue
        for r in range(id_row, min(rows, id_row + 4)):
            val = clean_val(df.iloc[r, c])
            times = re.findall(r'(\d{1,2}:\d{2})', val)
            for t in times: 
                if t not in found_times: found_times.append(t)
        if len(found_times) >= 1: break
    found_times.sort()
    t_s = found_times[0] if len(found_times) >= 1 else "-"
    t_k = found_times[1] if len(found_times) >= 2 else "-"
    t_b = found_times[2] if len(found_times) >= 3 else "-"
    return t_s, t_k, t_b

def extract_all_dojos(sheets):
    dojo_set = set()
    for _, df in sheets.items():
        df = df.fillna("").astype(str)
        rows, cols = df.shape
        search_cols = min(4, cols)
        for r in range(1, rows):
            for c in range(search_cols):
                val = clean_val(df.iloc[r, c])
                if len(val) < 2 or is_valid_id(val) or has_time_pattern(val): continue
                if val in ["集合時間", "計量", "試合開始", "Result", "優勝", "Winner", "カテゴリー", "Mat", "マット"]: continue
                player_val = clean_val(df.iloc[r-1, c])
                if len(player_val) > 1 and not has_time_pattern(player_val) and not is_valid_id(player_val):
                    dojo_set.add(val)
    return sorted(list(dojo_set))

def get_schedule_data(sheets, target_dojo):
    results = []
    for sheet_name, df in sheets.items():
        df = df.fillna("").astype(str)
        rows, cols = df.shape
        search_cols = min(4, cols)
        normalized_sheet = unicodedata.normalize('NFKC', str(sheet_name))
        mat_match = re.search(r'(\d+)', normalized_sheet)
        mat_num = mat_match.group(1) if mat_match else "999"

        for r in range(rows):
            for c in range(search_cols):
                val = clean_val(df.iloc[r, c])
                if val == target_dojo:
                    if r > 0:
                        player_name = clean_val(df.iloc[r-1, c])
                        if player_name and player_name != "nan" and target_dojo not in player_name and len(player_name) >= 2:
                            # Phase 1
                            scan_range_1 = range(-3, 3); max_search_col_1 = min(c + 10, cols)
                            barrier_col = -1; barrier_row = -1; found_time_signal = False
                            for offset in scan_range_1:
                                curr = r + offset
                                if 0 <= curr < rows:
                                    for check_c in range(c, max_search_col_1):
                                        cell_val = clean_val(df.iloc[curr, check_c])
                                        if "集合" in cell_val or has_time_pattern(cell_val):
                                            if barrier_col == -1 or check_c < barrier_col:
                                                barrier_col = check_c; barrier_row = curr
                                            found_time_signal = True
                            match_id = "-"; is_second_round = False; base_row_for_time = r
                            if found_time_signal:
                                found_ids = []
                                for offset in scan_range_1:
                                    curr = r + offset
                                    if 0 <= curr < rows:
                                        for sc in range(c + 1, max_search_col_1):
                                            if barrier_col != -1 and sc < barrier_col: continue
                                            v = df.iloc[curr, sc]
                                            if is_valid_id(v):
                                                dist_base = r if barrier_row == -1 else barrier_row
                                                dist = abs(curr - dist_base)
                                                found_ids.append((dist, clean_val(v), curr, sc))
                                if found_ids:
                                    found_ids.sort(key=lambda x: x[0])
                                    match_id = found_ids[0][1]
                                    base_row_for_time = barrier_row if barrier_row != -1 else found_ids[0][2]
                            t_s, t_k, t_b = "-", "-", "-"
                            if match_id != "-":
                                time_anchor = -1
                                for offset in range(-2, 3):
                                    curr = base_row_for_time + offset
                                    if 0 <= curr < rows:
                                        if "集合" in " ".join(df.iloc[curr].astype(str)):
                                            time_anchor = curr; break
                                target_r = time_anchor if time_anchor != -1 else base_row_for_time
                                if target_r < rows: t_s = extract_time_from_line(" ".join([clean_val(x) for x in df.iloc[target_r, :].tolist()]))
                                if target_r + 1 < rows: t_k = extract_time_from_line(" ".join([clean_val(x) for x in df.iloc[target_r + 1, :].tolist()]))
                                if target_r + 2 < rows: t_b = extract_time_from_line(" ".join([clean_val(x) for x in df.iloc[target_r + 2, :].tolist()]))
                            # Phase 2
                            if match_id == "-":
                                scan_range_2 = range(-8, 9); start_col_2 = c + 1; max_search_col_2 = min(c + 25, cols)
                                found_ids_2 = []
                                for offset in scan_range_2:
                                    curr = r + offset
                                    if 0 <= curr < rows:
                                        for sc in range(start_col_2, max_search_col_2):
                                            v = df.iloc[curr, sc]
                                            if is_valid_id(v):
                                                if has_time_nearby(df, curr, sc, rows, cols):
                                                    row_dist = abs(curr - r); col_dist = sc
                                                    score = (row_dist * 1000) + col_dist
                                                    found_ids_2.append((score, clean_val(v), curr, sc))
                                if found_ids_2:
                                    found_ids_2.sort(key=lambda x: x[0])
                                    match_id = found_ids_2[0][1]
                                    id_row = found_ids_2[0][2]; id_col = found_ids_2[0][3]
                                    is_second_round = True
                                    t_s, t_k, t_b = collect_times_vertical_strip(df, id_row, id_col)
                            category = "不明"
                            for up in range(1, 300):
                                if r - up < 0: break
                                line_vals = [str(v).strip() for v in df.iloc[r-up, :]]
                                if any(k in " ".join(line_vals) for k in ["帯", "Weight", "Category"]):
                                    cands = [v for v in line_vals if len(v)>4]; 
                                    if cands: category = cands[0]; break
                            results.append({
                                "mat": mat_num, "name": player_name, "match_no": match_id,
                                "is_seed": is_second_round, "start_time": t_b, "category": category
                            })
                            break
    return pd.DataFrame(results)

# --- HTML生成 ---
def generate_full_html(df):
    if df.empty:
        return "<div style='padding:20px; text-align:center;'>No matches found.</div>"
    
    def time_to_min(t_str):
        try: h, m = map(int, t_str.split(':')); return h * 60 + m
        except: return None
    df['min_time'] = df['start_time'].apply(time_to_min)
    df_valid = df.dropna(subset=['min_time']).copy()
    if df_valid.empty: return "<div style='padding:20px; text-align:center;'>No valid match times found.</div>"

    min_t = int(df_valid['min_time'].min()) - 30
    max_t = int(df_valid['min_time'].max()) + 60
    PX_PER_MIN = 2.2 
    
    # デザイン定義
    css = """
    <style>
    /* 全体のフォントと背景 */
    body {
        font-family: "Helvetica Neue", Arial, "Hiragino Kaku Gothic ProN", "Hiragino Sans", Meiryo, sans-serif;
        margin: 0;
        padding: 0;
        background-color: #f0f2f5; 
    }

    /* タイムテーブル全体のラッパー */
    .timetable-wrapper {
        display: flex;
        flex-direction: row;
        padding: 0;
        background-color: #f0f2f5;
        position: relative;
        height: 80vh;
        overflow: auto;
    }

    /* 左側の時間軸 */
    .time-axis {
        width: 50px;
        flex-shrink: 0;
        position: relative;
        border-right: 1px solid #e0e0e0;
        margin-right: 0;
        background: #fafafa;
        z-index: 5;
        margin-top: 40px; 
    }
    .time-label {
        position: absolute;
        width: 100%;
        text-align: right;
        padding-right: 8px;
        font-size: 11px;
        color: #888;
        border-top: 1px solid #eee;
        line-height: 1;
        transform: translateY(-50%); 
    }

    /* マットごとの列 */
    .mat-column {
        width: 260px;
        min-width: 260px;
        flex-shrink: 0;
        margin-right: 4px; 
        position: relative;
        background-color: transparent;
    }

    /* マットヘッダー (スティッキー) */
    .mat-header {
        text-align: center;
        font-weight: bold;
        padding: 0;
        background-color: #ffffff; 
        color: #333333;
        position: sticky;
        top: 0;
        z-index: 40;
        height: 40px;
        line-height: 40px;
        font-size: 14px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        border-bottom: 2px solid #ddd;
    }

    /* マット本体 (カード配置領域) */
    .mat-body {
        position: relative;
        background-color: #ffffff; 
        margin-top: 0;
        border-right: 1px solid #e0e0e0;
    }

    /* 試合カード */
    .match-card {
        position: absolute;
        width: 94%;
        left: 3%;
        background-color: white;
        border-radius: 6px; 
        padding: 8px 12px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1); 
        overflow: hidden;
        line-height: 1.3;
        z-index: 10;
        display: flex;
        flex-direction: column;
        justify-content: center;
        border-left-width: 6px;
        border-left-style: solid;
        box-sizing: border-box;
        transition: transform 0.1s ease, box-shadow 0.1s ease;
    }
    .match-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.15);
        z-index: 20;
    }

    /* カード内のテキスト */
    .card-time {
        font-weight: bold;
        color: #333;
        font-size: 12px;
        margin-bottom: 4px;
    }
    .card-player {
        font-weight: bold;
        font-size: 14px;
        color: #000;
        margin-bottom: 4px;
        line-height: 1.25;
    }
    .card-info {
        font-size: 11px;
        color: #666;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    /* 現在時刻ライン */
    .current-time-line {
        position: absolute;
        left: 0;
        right: 0;
        border-top: 2px solid #ff4b4b;
        z-index: 9;
        pointer-events: none;
    }
    .current-time-line::before {
        content: "";
        position: absolute;
        left: -5px;
        top: -6px;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background-color: #ff4b4b;
    }
    </style>
    """

    html_parts = [css, '<div class="timetable-wrapper">']
    
    jst_now = datetime.now(timezone.utc) + timedelta(hours=9)
    current_min = jst_now.hour * 60 + jst_now.minute
    if min_t <= current_min <= max_t:
        line_top = (current_min - min_t) * PX_PER_MIN
        html_parts.append(f'<div class="current-time-line" style="top: {line_top}px;"></div>')
    
    html_parts.append(f'<div class="time-axis" style="height: {(max_t - min_t) * PX_PER_MIN}px;">')
    current_t = min_t - (min_t % 30)
    while current_t <= max_t:
        top_px = (current_t - min_t) * PX_PER_MIN
        if top_px >= 0:
            h = current_t // 60; m = current_t % 60
            html_parts.append(f'<div class="time-label" style="top: {top_px}px;">{h:02d}:{m:02d}</div>')
        current_t += 30
    html_parts.append('</div>')
    
    df_valid['mat_int'] = pd.to_numeric(df_valid['mat'], errors='coerce').fillna(999).astype(int)
    mats = sorted(df_valid['mat_int'].unique())
    for m in mats:
        mat_label = f"マット{m}" if m != 999 else "Other"
        df_mat = df_valid[df_valid['mat_int'] == m]
        html_parts.append('<div class="mat-column">')
        html_parts.append(f'<div class="mat-header">{mat_label}</div>')
        html_parts.append(f'<div class="mat-body" style="height: {(max_t - min_t) * PX_PER_MIN}px;">')
        for _, row in df_mat.iterrows():
            start_min = row['min_time']
            top_px = (start_min - min_t) * PX_PER_MIN
            height_px = 60
            display_no = str(row['match_no']).split()[0]
            cat_text = str(row["category"])
            belt_color = get_belt_color(cat_text)
            
            card_html = (
                f'<div class="match-card" style="top: {top_px}px; height: {height_px}px; border-left-color: {belt_color};" >'
                f'<div class="card-time">{row["start_time"]}</div>'
                f'<div class="card-player">#{display_no} {row["name"]}</div>'
                f'<div class="card-info">{cat_text[:20]}</div>'
                f'</div>'
            )
            html_parts.append(card_html)
        html_parts.append('</div></div>')
    html_parts.append('</div>')
    
    return "".join(html_parts)

# --- セッションステート ---
if 'selected_dojo' not in st.session_state:
    st.session_state['selected_dojo'] = "SCORPION GYM"

# --- データ読み込み ---
with st.spinner("Loading..."):
    data, tournament_title = load_data_and_title()

# --- カスタムCSS ---
st.markdown("""
<style>
    .block-container {
        padding-top: 0rem !important;
        padding-bottom: 0rem !important;
        padding-left: 0rem !important;
        padding-right: 0rem !important;
        max-width: 100% !important;
    }
    header {visibility: hidden;}
    footer {visibility: hidden;}
    .custom-header {
        background-color: #ffffff;
        color: #333333;
        padding: 25px 20px;
        font-size: 24px;
        font-weight: bold;
        position: sticky;
        top: 0;
        z-index: 999;
        border-bottom: 1px solid #ddd;
        /* box-shadow: 0 2px 4px rgba(0,0,0,0.3); シャドウは画像ではあまり見えないので抑えめに、あるいはなしに */
    }
</style>
""", unsafe_allow_html=True)

# --- メイン画面 ---
if data:
    all_dojos = extract_all_dojos(data)

    # 1. ヘッダー
    st.markdown(f'<div class="custom-header">{tournament_title}</div>', unsafe_allow_html=True)

    # 2. 道場選択
    c1, c2 = st.columns([1, 4])
    with c1:
        st.markdown('<div style="padding-top: 15px; padding-left: 10px; font-weight:bold;">道場</div>', unsafe_allow_html=True)
    with c2:
        selected_dojo = st.selectbox(
            "道場選択", 
            all_dojos, 
            index=all_dojos.index(st.session_state['selected_dojo']) if st.session_state['selected_dojo'] in all_dojos else 0,
            label_visibility="collapsed"
        )
        if selected_dojo != st.session_state['selected_dojo']:
            st.session_state['selected_dojo'] = selected_dojo
            st.rerun()

    # 3. タイムテーブル
    target = st.session_state['selected_dojo']
    df_res = get_schedule_data(data, target)
    
    if not df_res.empty:
        html_code = generate_full_html(df_res)
        components.html(html_code, height=700, scrolling=False)
    else:
        st.info(f"「{target}」の試合は見つかりませんでした。")
else:
    st.error("データ読み込みエラー")