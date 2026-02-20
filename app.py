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
SPS_URL = "https://docs.google.com/spreadsheets/u/1/d/e/2PACX-1vSXX7C31vhQh9qBPo_Qs6pKE8QfRiPiAD9HYgWQWLVHwGxesIFr2417ieMHLqMtouZJyImsUmuKLUeK/pub?output=xlsx"

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
    
    def has_japanese(text):
        return bool(re.search(r'[一-龥ぁ-んァ-ン]', text))
    
    def has_alpha(text):
        return bool(re.search(r'[a-zA-Z]', text))
        
    def is_likely_player(text):
        # JBJJF players usually have both Japanese and English names, e.g. "松本将樹 Masaki Matsumoto"
        # Must have both scripts
        if not (has_japanese(text) and has_alpha(text)): return False
        # Must match pattern: Japanese + Space + Alpha (e.g. "古川雄大 Yudai Furukawa")
        # \u3000 is full-width space
        return bool(re.search(r'[一-龥ぁ-んァ-ン]+[ \u3000]+[a-zA-Z]', text))

    def is_likely_dojo(text):
        # Dojos are usually either all Alpha (SCORPION GYM) or all Japanese (ねわざワールド)
        # They rarely mix scripts in the same way, or at least we can assume if it's NOT a player format, it might be a dojo.
        # Also exclude common keywords
        if text in ["集合時間", "計量", "試合開始", "Result", "優勝", "Winner", "カテゴリー", "Mat", "マット", "道着チェック", "欠場"]: return False
        
        # Exclude if it looks like a player name (Japanese Space English)
        if is_likely_player(text): return False
        return True

    for _, df in sheets.items():
        df = df.fillna("").astype(str)
        rows, cols = df.shape
        # Search more columns to ensure we catch dojos in later columns (e.g. col 5)
        search_cols = min(20, cols)
        
        for r in range(1, rows):
            for c in range(search_cols):
                val = clean_val(df.iloc[r, c])
                
                # Basic validation
                if len(val) < 2 or is_valid_id(val) or has_time_pattern(val): continue
                if not is_likely_dojo(val): continue
                
                # Context check: Look at the row above (r-1)
                upper_val = clean_val(df.iloc[r-1, c])
                
                # Heuristic: If row above is a Player, this row is likely a Dojo
                if is_likely_player(upper_val):
                     dojo_set.add(val)

    if not dojo_set:
        # Fallback: if strict logic finds nothing, try looser logic (e.g. just row-1 is not category)
        # But for now, returning empty is better than garbage.
        # Let's add at least one check to avoid complete empty if possible.
        pass

    return sorted(list(dojo_set))

def get_schedule_data(sheets, target_dojo):
    results = []
    for sheet_name, df in sheets.items():
        df = df.fillna("").astype(str)
        rows, cols = df.shape
        search_cols = min(20, cols) # Increase search width here too
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
                            # プレイヤー行に「計量」「集合」が含まれている場合は、試合行ではなくスケジュール行なのでスキップ
                            player_row_str = " ".join([clean_val(x) for x in df.iloc[r-1, :].tolist()])
                            if "計量" in player_row_str or "集合" in player_row_str:
                                continue

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
    df_res = pd.DataFrame(results)
    if not df_res.empty:
        # 重複削除 (念のため mat, match_no, name, start_time で判定)
        df_res = df_res.drop_duplicates(subset=['mat', 'match_no', 'name', 'start_time'])
    return df_res

# --- HTML生成 ---
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
    CARD_HEIGHT = 42 # カードの高さを圧縮
    
    # デザイン定義
    css = f"""
    <style>
    /* 全体のフォントと背景 */
    body {{
        font-family: "Helvetica Neue", Arial, "Hiragino Kaku Gothic ProN", "Hiragino Sans", Meiryo, sans-serif;
        margin: 0;
        padding: 0;
        background-color: #0e1117; 
        color: #fafafa;
    }}

    /* タイムテーブル全体のラッパー */
    .timetable-wrapper {{
        display: flex;
        flex-direction: row;
        padding: 0;
        background-color: #0e1117;
        position: relative;
        height: calc(100vh - 70px); /* ヘッダー分を引く */
        overflow: auto;
    }}

    /* 左側の時間軸 */
    .time-axis {{
        width: 60px; /* 少し広げる */
        flex-shrink: 0;
        position: relative;
        /* border-right: 1px solid #e0e0e0; */ /* 二重線になるので削除 */
        margin-right: 0;
        background: #0e1117;
        z-index: 5;
        margin-top: 40px; 
    }}
    .time-label {{
        position: absolute;
        width: 100%;
        text-align: right;
        padding-right: 4px; /* 右の罫線との間にスペース (4px指定) */
        font-size: 10px; /* 文字サイズ調整 */
        color: #a0a0a0;
        /* border-top: 1px solid #eee; */ /* 軸側の線は消す */
        line-height: 1;
        transform: translateY(-50%); 
    }}

    /* マットごとの列 */
    .mat-column {{
        width: 260px;
        min-width: 260px;
        flex-shrink: 0;
        margin-right: 0; 
        position: relative;
        background-color: transparent;
        display: flex;
        flex-direction: column;
        /* border-right: 1px solid #e0e0e0; */ /* ヘッダーの縦線削除のため削除 */
    }}

    /* マットヘッダー (スティッキー) */
    .mat-header {{
        text-align: center;
        font-weight: bold;
        padding: 0;
        background-color: #0e1117; 
        color: #fafafa;
        position: sticky;
        top: 0;
        z-index: 40;
        height: 40px;
        line-height: 40px;
        font-size: 14px;
        /* box-shadow: 0 2px 4px rgba(0,0,0,0.1); シャドウ削除 */
        border-bottom: 1px solid #414144; /* これが「緑の箇所の罫線」 */
    }}

    /* マット本体 (カード配置領域) */
    .mat-body {{
        position: relative;
        background-color: #0e1117; 
        margin-top: 0;
        border-right: 1px solid #414144; /* ここに縦線を追加 */
        flex-grow: 1;
        /* グリッド線はdivで描画するため背景画像の指定は削除 */
        background-image: none;
    }}

    /* グリッド線 */
    .grid-line {{
        position: absolute;
        left: 0;
        right: 0;
        z-index: 1;
        pointer-events: none;
    }}
    .grid-line-solid {{
        border-top: 1px solid #414144;
    }}
    .grid-line-dashed {{
        border-top: 1px dashed #414144;
    }}

    /* 試合カード */
    .match-card {{
        position: absolute;
        background-color: #262730; /* ダークグレー */
        border-radius: 2px; 
        padding: 2px 6px;
        box-shadow: none; /* シャドウなし */
        overflow: hidden;
        line-height: 1.1;
        z-index: 10;
        display: flex;
        flex-direction: column;
        justify-content: center;
        border-left-width: 4px;
        border-left-style: solid;
        box-sizing: border-box;
        transition: transform 0.1s ease;
        /* 枠線はつけないか、薄くつける */
        /* border: 1px solid #eee; */
    }}
    .match-card:hover {{
        transform: translateY(-1px);
        z-index: 30;
        background-color: #363945;
    }}

    /* カード内のテキスト */
    .card-time {{
        color: #a0a0a0;
        font-size: 10px; /* 小さく */
        margin-bottom: 1px;
    }}
    .card-player {{
        font-weight: bold;
        font-size: 11px; /* 小さく */
        color: #fafafa;
        margin-bottom: 0px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}

    /* 現在時刻ライン */
    .current-time-line {{
        position: absolute;
        left: 0;
        right: 0;
        border-top: 2px solid #ff4b4b; /* 少し太く */
        z-index: 999;
        pointer-events: none;
    }}
    .current-time-badge {{
        position: absolute;
        left: 0;
        background-color: #ff4b4b;
        color: white;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: bold;
        z-index: 1000;
        transform: translate(-10%, -50%); /* 左端に配置し、上下中央揃え */
    }}
    
    /* Ensure clickability */
    html, body {{
        height: 100%;
        margin: 0;
        padding: 0;
        background-color: transparent; /* Or match background */
    }}
    .timetable-wrapper {{
        min-height: 100%;
    }}
    </style>
    """

    html_parts = [css, '<div class="timetable-wrapper">']
    
    jst_now = datetime.now(timezone.utc) + timedelta(hours=9)
    current_min = jst_now.hour * 60 + jst_now.minute
    
    HEADER_HEIGHT = 40
    if min_t <= current_min <= max_t:
        line_top = (current_min - min_t) * PX_PER_MIN + HEADER_HEIGHT
        time_str = jst_now.strftime('%H:%M')
        html_parts.append(
            f'<div class="current-time-line" style="top: {line_top}px;">'
            f'<div class="current-time-badge">{time_str}</div>'
            f'</div>'
        )
    
    html_parts.append(f'<div class="time-axis" style="height: {(max_t - min_t) * PX_PER_MIN}px;">')
    current_t = min_t - (min_t % 30)
    while current_t <= max_t:
        top_px = (current_t - min_t) * PX_PER_MIN
        if top_px >= 0:
            h = current_t // 60; m = current_t % 60
            # xx:00 のみ表示
            if m == 0:
                label_html = f'<div class="time-label" style="top: {top_px}px;">{h:02d}:{m:02d}</div>'
                html_parts.append(label_html)
        current_t += 30
    html_parts.append('</div>')
    
    df_valid['mat_int'] = pd.to_numeric(df_valid['mat'], errors='coerce').fillna(999).astype(int)
    mats = sorted(df_valid['mat_int'].unique())
    
    # グリッド線の位置とスタイルを計算
    grid_lines_html = []
    g_t = min_t - (min_t % 30)
    while g_t <= max_t:
        top_px = (g_t - min_t) * PX_PER_MIN
        if top_px >= 0:
            m = g_t % 60
            style_class = "grid-line-solid" if m == 0 else "grid-line-dashed"
            grid_lines_html.append(f'<div class="grid-line {style_class}" style="top: {top_px}px;"></div>')
        g_t += 30
    grid_lines_str = "".join(grid_lines_html)

    for i, m in enumerate(mats):
        mat_label = f"マット{m}" if m != 999 else "Other"
        df_mat = df_valid[df_valid['mat_int'] == m].sort_values('min_time')
        
        # mat-column自体のボーダーは削除
        html_parts.append(f'<div class="mat-column">')
        
        html_parts.append(f'<div class="mat-header">{mat_label}</div>')
        
        # 最初のカラムだけ左ボーダーを mat-body に追加
        extra_style = "border-left: 1px solid #e0e0e0;" if i == 0 else ""
        html_parts.append(f'<div class="mat-body" style="min-height: {(max_t - min_t) * PX_PER_MIN}px; {extra_style}">')
        
        # グリッド線を追加
        html_parts.append(grid_lines_str)
        
        # 重なり判定用のカラム終了位置 (pixel) を保持するリスト
        # indexがカラム位置(0=左端, 1=一段右, 2=二段右...)、値はそのカラムの埋まっている最後尾(bottom_px)
        col_ends = [] 
        
        for _, row in df_mat.iterrows():
            start_min = row['min_time']
            top_px = (start_min - min_t) * PX_PER_MIN
            height_px = CARD_HEIGHT
            bottom_px = top_px + height_px
            
            # 配置可能なカラムを探す
            target_col = -1
            for col_idx, end_px in enumerate(col_ends):
                # 既存のカラムで、top_px が end_px より下なら配置可能
                # 少し遊びを持たせるなら top_px >= end_px - tolerance
                if top_px >= end_px:
                    target_col = col_idx
                    col_ends[col_idx] = bottom_px
                    break
            
            # 空きがなければ新しいカラムを追加
            if target_col == -1:
                target_col = len(col_ends)
                col_ends.append(bottom_px)
            
            # スタイル決定 (階層が深くなるほど右にずらす)
            # 1階層あたり20%ずらす
            indent_pct = target_col * 20
            left_pct = 2 + indent_pct
            
            # 幅は画面からはみ出さないように調整、かつ狭くなりすぎないように
            # 右端をある程度揃えたいが、後ろのカラムが見えなくなるので
            # widthは 96 - indent_pct とする（右端揃え）
            # あるいは少し残す？
            width_pct = 96 - indent_pct
            
            if width_pct < 20: width_pct = 20 # 最低幅保証
            
            z_index = 10 + target_col # 後ろのカラム（右側）ほど手前に表示
            
            display_no = str(row['match_no']).split()[0]
            cat_text = str(row["category"])
            belt_color = get_belt_color(cat_text)
            
            card_html = (
                f'<div class="match-card" style="top: {top_px}px; height: {height_px}px; left: {left_pct}%; width: {width_pct}%; z-index: {z_index}; border-left-color: {belt_color};" >'
                f'<div class="card-time">{row["start_time"]}</div>'
                f'<div class="card-player">#{display_no} {row["name"]}</div>'
                f'</div>'
            )
            html_parts.append(card_html)
        html_parts.append('</div></div>')
    html_parts.append('</div>')
    
    html_parts.append('</div>')
    
    # iframe内でのクリックを検知してサイドバーを閉じるスクリプトを追加
    html_parts.append("""
    <script>
    function notifyParentToClose(e) {
        console.log("Timetable clicked/touched", e.type);
        if (window.parent && window.parent.closeStreamlitSidebar) {
            console.log("Calling window.parent.closeStreamlitSidebar");
            window.parent.closeStreamlitSidebar();
        } else {
            console.log("window.parent.closeStreamlitSidebar not found");
        }
    }

    // Use capture phase to ensure we catch events
    window.addEventListener('click', notifyParentToClose, true);
    window.addEventListener('touchstart', notifyParentToClose, {passive: true, capture: true});
    </script>
    """)
    
    return "".join(html_parts)

# ページ設定 (タイトルとアイコンのみ)
# st.set_page_config(...) # 冒頭へ移動

# --- セッションステート ---
# selected_dojo の初期化はデータ読み込み後に行うためここでは削除

# --- データ読み込み ---
with st.spinner("Loading..."):
    data, tournament_title = load_data_and_title()

# --- OGP / SNS共有用メタタグ ---
_ogp_title = f"🥋 {tournament_title}" if tournament_title else "🥋 JBJJF タイムテーブル"
_ogp_desc  = f"{tournament_title} の団体別タイムテーブル。出場選手の試合スケジュールを確認できます。" if tournament_title else "JBJJF 出場選手の試合スケジュールを団体別に確認できます。"

# ホスト名を動的に取得してOGP画像の絶対URLを構築
try:
    _host = st.context.headers.get("host", "")
    _base_url = f"http://{_host}" if _host else ""
except Exception:
    _base_url = ""
_ogp_image = f"{_base_url}/app/static/ogp.png" if _base_url else "/app/static/ogp.png"

st.markdown(f"""
<meta property="og:type"        content="website">
<meta property="og:title"       content="{_ogp_title}">
<meta property="og:description" content="{_ogp_desc}">
<meta property="og:image"       content="{_ogp_image}">
<meta property="og:image:width"  content="1200">
<meta property="og:image:height" content="630">
<meta name="description"        content="{_ogp_desc}">
<meta name="twitter:card"       content="summary_large_image">
<meta name="twitter:title"      content="{_ogp_title}">
<meta name="twitter:description" content="{_ogp_desc}">
<meta name="twitter:image"      content="{_ogp_image}">
""", unsafe_allow_html=True)


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
    footer {visibility: hidden;}
    
    /* Streamlit標準ヘッダーの調整: 透明にしてイベントを無効化 */
    header[data-testid="stHeader"] {
        background-color: transparent !important;
        pointer-events: none;
        z-index: 100000 !important;
    }
    
    /* サイドバー開閉ボタン(左上)のスタイルと有効化 */
    header[data-testid="stHeader"] button[data-testid="stSidebarCollapseButton"],
    header[data-testid="stHeader"] button[data-testid="stSidebarCollapsedControl"],
    header[data-testid="stHeader"] button[data-testid="stExpandSidebarButton"] {
        pointer-events: auto !important;
        color: #fafafa !important;
        display: block !important;
        visibility: visible !important;
        z-index: 100001 !important;
        background-color: transparent !important;
    }
    header[data-testid="stHeader"] button[data-testid="stSidebarCollapseButton"] svg,
    header[data-testid="stHeader"] button[data-testid="stSidebarCollapsedControl"] svg,
    header[data-testid="stHeader"] button[data-testid="stExpandSidebarButton"] svg {
        fill: #fafafa !important;
        stroke: #fafafa !important;
    }
    
    /* 互換性のため古いセレクタも残す - 上記に統合 */

    /* ツールバー(右上のDeployボタンやメニュー)を非表示 (レイアウト崩れ防止のためvisibilityを使用) */
    [data-testid="stToolbar"] {
        visibility: hidden !important;
    }
    .stDeployButton, 
    [data-testid="stAppDeployButton"] {
        visibility: hidden !important;
        display: none !important; /* Deployボタンは消しても大丈夫そうだが念のため */
    }
    [data-testid="stMainMenu"] {
        visibility: hidden !important;
    }
    [data-testid="stDecoration"] {
        visibility: hidden !important;
    }
    [data-testid="stStatusWidget"] {
        visibility: hidden !important;
    }
    
    .custom-header {
        background-color: #0e1117;
        color: #fafafa;
        height: 44px;
        line-height: 44px;
        padding: 0 20px 0 60px; /* 左はトグルボタン分空ける */
        font-size: 16px;
        font-weight: bold;
        position: sticky;
        top: 0;
        z-index: 999; 
        border-bottom: 1px solid #414144;
        text-align: left;
        display: flex;
        align-items: center;
        justify-content: space-between; /* 子要素を両端に配置 */
    }
    
    .header-title {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        flex-grow: 1;
        margin-right: 10px;
        min-width: 0; /* フレックスアイテムが縮小できるようにする重要な指定 */
    }
    
    .share-button {
        cursor: pointer;
        padding: 4px 8px;
        border-radius: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background-color 0.2s;
    }
    .share-button:hover {
        background-color: #262730;
    }
    .share-icon {
        width: 20px;
        height: 20px;
        fill: #fafafa;
    }
    
    /* Snackbar */
    .snackbar {
        visibility: hidden;
        min-width: 250px;
        background-color: #333;
        color: #fff;
        text-align: center;
        border-radius: 4px;
        padding: 12px;
        position: fixed;
        z-index: 100002;
        left: 50%;
        bottom: 30px;
        transform: translateX(-50%);
        font-size: 14px;
        opacity: 0;
        transition: opacity 0.3s, bottom 0.3s;
    }
    
    .snackbar.show {
        visibility: visible;
        opacity: 1;
        bottom: 50px;
    }

    /* Sidebar Customization */
    section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label > div:first-child {
        display: None;
    }
    section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label {
        padding: 5px 10px;
        border-radius: 5px;
        margin-bottom: 2px;
        transition: background-color 0.1s;
    }
    section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:hover {
        background-color: #262730;
    }
    /* Selected state using :has selector */
    section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:has(input:checked) {
        background-color: #262730;
    }
    
    /* Sticky Sidebar Close Button & Header */
    section[data-testid="stSidebar"] > div > div:first-child {
        position: -webkit-sticky;
        position: sticky;
        top: 0;
        z-index: 99999;
        background-color: #262730; /* サイドバー背景色(デフォルト暗色) */
        padding-top: 1rem;
        padding-bottom: 0.5rem;
    }
    section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:has(input:checked) {
        background-color: #414144;
        font-weight: bold;
        color: #fafafa;
    }
    
    .sidebar-dojo-header {
        font-size: 16px;
        font-weight: bold;
        margin-bottom: 10px;
        color: #fafafa;
    }
    
    /* サイドバーのラジオボタンを選択しやすくする（横幅いっぱいにする） */
    section[data-testid="stSidebar"] [data-testid="stRadio"] label {
        width: 100% !important;
        display: flex !important;
        align-items: center !important;
        cursor: pointer !important;
    }
    
    /* タイムテーブルのiframeを強制的に広げる */
    iframe[title="st.iframe"] {
        height: 85vh !important;
    }
</style>
""", unsafe_allow_html=True)

# --- メイン画面 ---
if data:
    all_dojos = extract_all_dojos(data)

    # --- URLクエリパラメータから団体を復元 ---
    _qp_dojo = st.query_params.get('dojo', '')

    # selected_dojo が未設定 or 無効の場合は初期化
    if 'selected_dojo' not in st.session_state or st.session_state['selected_dojo'] not in all_dojos:
        if all_dojos:
            # クエリパラメータが有効な団体名なら優先して使用
            if _qp_dojo in all_dojos:
                st.session_state['selected_dojo'] = _qp_dojo
            else:
                st.session_state['selected_dojo'] = all_dojos[0]
    elif _qp_dojo in all_dojos and _qp_dojo != st.session_state['selected_dojo']:
        # URLが手動で変更された場合にも対応
        st.session_state['selected_dojo'] = _qp_dojo

    # 現在の選択をURLに反映（常に最新を保持）
    st.query_params['dojo'] = st.session_state['selected_dojo']

    # サイドバー: 団体選択
    # st.sidebar.markdown("---") # 削除
    
    # 見出し (16px)
    st.sidebar.markdown(f'<div class="sidebar-dojo-header">団体 ({len(all_dojos)})</div>', unsafe_allow_html=True)
    
    # 現在の選択を初期値として設定
    initial_index = 0
    if st.session_state['selected_dojo'] in all_dojos:
        initial_index = all_dojos.index(st.session_state['selected_dojo'])
    
    selected_dojo = st.sidebar.radio(
        label="団体選択",
        options=all_dojos,
        label_visibility="collapsed",
        index=initial_index,
        format_func=lambda x: x
    )

    if selected_dojo != st.session_state['selected_dojo']:
        st.session_state['selected_dojo'] = selected_dojo
        st.query_params['dojo'] = selected_dojo  # URLに反映
        st.rerun()

    # 1. ヘッダー (Shareボタン機能修正: Event Delegation + レイアウト調整)
    share_icon_svg = """<svg class="share-icon" viewBox="0 0 24 24"><path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92 1.61 0 2.92-1.31 2.92-2.92s-1.31-2.92-2.92-2.92z"/></svg>"""
    
    st.markdown(f"""
<div class="custom-header">
  <div class="header-title">🥋 {tournament_title}</div>
  <div class="share-button" id="share-btn">
    {share_icon_svg}
  </div>
</div>
<div id="snackbar" class="snackbar">URLをコピーしました</div>
""", unsafe_allow_html=True)

    # 2. タイムテーブル
    target = st.session_state['selected_dojo']
    df_res = get_schedule_data(data, target)
    
    if not df_res.empty:
        html_code = generate_full_html(df_res)
        components.html(html_code, height=1300, scrolling=False)
    else:
        st.info(f"「{target}」の試合は見つかりませんでした。")
        
    # --- モバイル用クリップボード共有スクリプト ---
    components.html("""
    <script>
    (function() {
        const doc = window.parent.document;
        const STORAGE_KEY = 'streamlit_mobile_sidebar_trigger';
        
        // --- Clipboard Logic ---
        const copyToClipboard = () => {
             const url = window.parent.location.href;
             const showSnack = () => {
                 const x = doc.getElementById("snackbar");
                 if (x) {
                     x.className = "snackbar show";
                     setTimeout(() => { x.className = x.className.replace("snackbar show", "snackbar"); }, 2000);
                 }
             };
             if (navigator && navigator.clipboard) {
                 navigator.clipboard.writeText(url).then(showSnack).catch(() => fallbackCopy(url, showSnack));
             } else {
                 fallbackCopy(url, showSnack);
             }
        };

        const fallbackCopy = (url, cb) => {
            const ta = doc.createElement("textarea");
            ta.value = url;
            ta.setAttribute("readonly", "");
            ta.style.cssText = "position:absolute;left:-9999px";
            doc.body.appendChild(ta);
            ta.select();
            ta.setSelectionRange(0, 99999);
            try { if (doc.execCommand('copy')) cb(); } catch(e) {}
            doc.body.removeChild(ta);
        };

        // --- Close Sidebar ---
        const closeSidebar = () => {
            // Try collapse button first
            const btns = doc.querySelectorAll(
                'button[data-testid="stSidebarCollapseButton"], button[data-testid="stSidebarCollapsedControl"]'
            );
            for (const btn of btns) {
                // Find visible button
                const r = btn.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    btn.click();
                    return;
                }
            }
            // Fallback: Escape key
            doc.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'Escape', code: 'Escape', keyCode: 27, which: 27,
                bubbles: true, cancelable: true, view: window.parent
            }));
        };

        // --- Check if sidebar is open ---
        const isSidebarOpen = () => {
            const sb = doc.querySelector('section[data-testid="stSidebar"]');
            if (!sb) return false;
            return sb.getBoundingClientRect().width > 50;
        };

        // --- Handle touch/click on parent document ---
        const handleInteraction = (e) => {
            // Share button
            if (e.target.closest && (e.target.closest('#share-btn') || e.target.closest('.share-button'))) {
                copyToClipboard();
                return;
            }

            // Only on mobile
            const vw = window.parent.innerWidth || doc.documentElement.clientWidth;
            if (vw > 992) return;
            if (!isSidebarOpen()) return;

            const sidebar = doc.querySelector('section[data-testid="stSidebar"]');
            if (!sidebar) return;

            const insideSidebar = sidebar.contains(e.target);

            if (insideSidebar) {
                // Dojo selection: close sidebar when radio label is tapped
                const label = e.target.closest && e.target.closest('label');
                if (label && label.querySelector('input[type="radio"]')) {
                    sessionStorage.setItem(STORAGE_KEY, Date.now().toString());
                    // Slight delay so Streamlit registers the selection first
                    setTimeout(closeSidebar, 50);
                }
            } else {
                // Outside sidebar: close it
                // But ignore the toggle button itself
                const toggle = e.target.closest && (
                    e.target.closest('button[data-testid="stSidebarCollapseButton"]') ||
                    e.target.closest('button[data-testid="stSidebarCollapsedControl"]')
                );
                if (!toggle) {
                    closeSidebar();
                }
            }
        };

        // --- After-reload: ensure sidebar stays closed ---
        const checkAndCloseOnLoad = () => {
            const trigger = sessionStorage.getItem(STORAGE_KEY);
            if (trigger && (Date.now() - parseInt(trigger) < 8000)) {
                const vw = window.parent.innerWidth || doc.documentElement.clientWidth;
                if (vw <= 992) {
                    let tries = 0;
                    const iv = setInterval(() => {
                        if (isSidebarOpen()) closeSidebar();
                        tries++;
                        if (!isSidebarOpen() || tries > 15) {
                            clearInterval(iv);
                            sessionStorage.removeItem(STORAGE_KEY);
                        }
                    }, 200);
                } else {
                    sessionStorage.removeItem(STORAGE_KEY);
                }
            }
        };

        // --- Attach listeners (once) ---
        const attach = () => {
            if (doc.body.dataset.sidebarListenerAttached === '1') return;
            doc.body.dataset.sidebarListenerAttached = '1';

            // touchstart for mobile immediacy, click for desktop fallback
            doc.addEventListener('touchstart', handleInteraction, { capture: true, passive: true });
            doc.addEventListener('click', handleInteraction, { capture: true });
        };

        // Run
        checkAndCloseOnLoad();
        if (doc.body) {
            attach();
        } else {
            doc.addEventListener('DOMContentLoaded', attach);
        }

        // Re-attach after Streamlit re-renders
        const obs = new MutationObserver(attach);
        obs.observe(doc.body || doc.documentElement, { childList: true, subtree: false });

    })();
    </script>
    """, height=0, width=0)



else:
    st.error("データ読み込みエラー")