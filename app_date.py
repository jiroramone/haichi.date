import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from bs4 import BeautifulSoup
import time

# --- 1. 基本設定 ---
st.set_page_config(page_title="配置馬券 データ収集（一括取得版）", layout="wide")

def to_half_width(text):
    if pd.isna(text): return text
    text = str(text)
    table = str.maketrans('０１２３４５６７８９．', '0123456789.')
    return re.sub(r'[^\d\.]', '', text.translate(table))

def normalize_name(x):
    if pd.isna(x): return ''
    s = str(x).strip().replace('　', '').replace(' ', '')
    s = re.split(r'[,(（/]', s)[0]
    return re.sub(r'[★☆▲△◇$*]', '', s)

JYO_MAP = {
    '01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
    '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'
}

# --- 2. データ読み込み（失敗時に詳細を出すように強化） ---
def load_data(file):
    try:
        if file.name.endswith('.xlsx'):
            df = pd.read_excel(file, engine='openpyxl')
        else:
            try: df = pd.read_csv(file, encoding='utf-8')
            except: df = pd.read_csv(file, encoding='cp932')
        
        # 項目名が見つからない場合、10行目までスキャン
        if not any(col in str(df.columns) for col in ['場所', '馬', '番', 'R']):
            for i in range(min(len(df), 10)):
                row_values = [str(x) for x in df.iloc[i].values]
                if any('場所' in x or '番' in x or 'R' in x for x in row_values):
                    df.columns = df.iloc[i]
                    df = df.iloc[i+1:].reset_index(drop=True)
                    break

        df.columns = df.columns.astype(str).str.strip()
        name_map = {'場所':'場名','競馬場':'場名','開催':'場名','番':'正番','馬番':'正番','単勝オッズ':'単ｵｯｽﾞ','オッズ':'単ｵｯｽﾞ','着':'着順'}
        df = df.rename(columns=name_map)
        
        # 必須列チェック
        missing = [c for c in ['R', '場名', '正番'] if c not in df.columns]
        if missing:
            return pd.DataFrame(), f"不足している列があります: {', '.join(missing)}"

        df['R'] = pd.to_numeric(df['R'].apply(to_half_width), errors='coerce')
        df['正番'] = pd.to_numeric(df['正番'].apply(to_half_width), errors='coerce')
        df = df.dropna(subset=['R', '正番'])
        df['R'] = df['R'].astype(int)
        df['正番'] = df['正番'].astype(int)
        for col in ['騎手', '厩舎', '馬主', '馬名', '場名']:
            if col in df.columns:
                df[col] = df[col].astype(str).apply(normalize_name)
        return df.copy(), "success"
    except Exception as e:
        return pd.DataFrame(), str(e)

# --- 3. ネット競馬データ取得 ---
def fetch_netkeiba_result(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'EUC-JP'
        if response.status_code != 200: return None, None, f"アクセス拒否({response.status_code})"

        race_id_match = re.search(r'race_id=(\d{12})', url)
        info = {"place": "", "r": 0}
        if race_id_match:
            rid = race_id_match.group(1)
            info["place"] = JYO_MAP.get(rid[4:6], "")
            info["r"] = int(rid[10:12])

        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table')
        target_table = None
        for t in tables:
            t_text = t.get_text()
            if '着順' in t_text and '馬番' in t_text:
                target_table = t; break
        
        if not target_table: return None, info, "結果表が見つかりません"

        result_map = {}
        rows = target_table.find_all('tr')
        header_cols = [th.get_text(strip=True) for th in rows[0].find_all(['th', 'td'])]
        try:
            idx_rank = [i for i, c in enumerate(header_cols) if '着順' in c][0]
            idx_umaban = [i for i, c in enumerate(header_cols) if '馬番' in c][0]
        except: return None, info, "列特定失敗"

        for row in rows[1:]:
            cols = row.find_all('td')
            if len(cols) <= max(idx_rank, idx_umaban): continue
            r_m = re.search(r'\d+', cols[idx_rank].get_text(strip=True))
            u_m = re.search(r'\d+', cols[idx_umaban].get_text(strip=True))
            if r_m and u_m: result_map[int(u_m.group())] = int(r_m.group())
            elif u_m: result_map[int(u_m.group())] = 99
        
        return result_map, info, "success"
    except Exception as e: return None, None, str(e)

# --- 4. UI 画面表示 ---
st.title("🏇 配置馬券術 データ一括収集")

with st.sidebar:
    st.header("📂 1. ファイル選択")
    up_curr = st.file_uploader("いつもの配置表(Excel/CSV)をアップ", type=['xlsx', 'csv'])
    
    if 'analyzed_df' in st.session_state:
        st.divider()
        st.header("💾 3. 保存")
        csv = st.session_state['analyzed_df'].to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 着順入りCSVを保存", csv, "horse_results.csv")
        if st.button("🗑️ 全データをクリア"):
            del st.session_state['analyzed_df']
            st.rerun()

# メイン画面の制御
if up_curr:
    df_raw, status = load_data(up_curr)
    
    if status == "success":
        if 'analyzed_df' not in st.session_state:
            st.session_state['analyzed_df'] = df_raw
        
        # --- URL入力画面を表示 ---
        st.success("✅ ファイルの読み込みに成功しました！")
        
        st.header("🔗 2. URLを貼り付けて着順を一括取得")
        st.info("ネット競馬のレース結果URL（...result.html?race_id=...）を下に貼り付けてください。")
        
        urls_input = st.text_area("ここにURLをまとめて貼り付け（1行に1つのURL）", height=250)
        
        if st.button("🚀 一括取得を開始する"):
            if not urls_input:
                st.error("URLが入力されていません。")
            else:
                urls = [u.strip() for u in urls_input.split('\n') if u.strip()]
                progress_bar = st.progress(0)
                status_box = st.empty()
                
                success_count = 0
                for i, url in enumerate(urls):
                    status_box.text(f"取得中 ({i+1}/{len(urls)}): {url[-12:]}")
                    res, info, msg = fetch_netkeiba_result(url)
                    
                    if msg == "success" and info["place"]:
                        # 該当するレースの着順を更新
                        st.session_state['analyzed_df'].loc[
                            (st.session_state['analyzed_df']['場名'] == info["place"]) & 
                            (st.session_state['analyzed_df']['R'] == info["r"]), '着順'
                        ] = np.nan # 一旦クリア
                        
                        for u, r in res.items():
                            st.session_state['analyzed_df'].loc[
                                (st.session_state['analyzed_df']['場名'] == info["place"]) & 
                                (st.session_state['analyzed_df']['R'] == info["r"]) & 
                                (st.session_state['analyzed_df']['正番'] == u), '着順'
                            ] = r
                        success_count += 1
                    else:
                        st.warning(f"取得失敗: {url[-12:]} ({msg})")
                    
                    progress_bar.progress((i + 1) / len(urls))
                    time.sleep(1.2) # ブロック防止
                
                status_box.success(f"完了！ {len(urls)}件中 {success_count}件の着順を反映しました。")
                st.balloons()

        # プレビュー表示
        st.divider()
        st.subheader("📊 現在のデータ状況")
        st.dataframe(st.session_state['analyzed_df'][['場名','R','正番','馬名','着順','単ｵｯｽﾞ']], height=400)

    else:
        # ファイル読み込みに失敗した場合の原因を表示
        st.error(f"❌ ファイルが正しく読み込めませんでした。\n原因: {status}")
        st.write("「場所」「R」「番」という項目が1行目にあるか確認してください。")
        st.write("読み込んだ生データ:")
        st.write(df_raw) # どこまで読み込めたか表示
else:
    # ファイルがまだアップロードされていない時
    st.info("👈 左のサイドバーから、いつもの配置表ファイルをアップロードしてください。")
    st.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/tutorials/file-uploader.png", width=300) # アップローダーの参考画像
