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

# 競馬場名の変換マップ（URL内のIDから判定用）
JYO_MAP = {
    '01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
    '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'
}

# --- 2. データ読み込み ---
@st.cache_data
def load_data(file):
    try:
        if file.name.endswith('.xlsx'):
            df = pd.read_excel(file, engine='openpyxl')
        else:
            try: df = pd.read_csv(file, encoding='utf-8')
            except: df = pd.read_csv(file, encoding='cp932')
        
        # ヘッダー探索
        if not any(col in str(df.columns) for col in ['場所', '馬', '番', 'R']):
            for i in range(min(len(df), 10)):
                row_values = [str(x) for x in df.iloc[i].values]
                if any('場所' in x or '番' in x or 'R' in x for x in row_values):
                    df.columns = df.iloc[i]; df = df.iloc[i+1:].reset_index(drop=True); break

        df.columns = df.columns.astype(str).str.strip()
        name_map = {'場所':'場名','競馬場':'場名','開催':'場名','番':'正番','馬番':'正番','単勝オッズ':'単ｵｯｽﾞ','オッズ':'単ｵｯｽﾞ','着':'着順'}
        df = df.rename(columns=name_map)
        
        ensure_cols = ['R', '場名', '馬名', '正番', '騎手', '厩舎', '馬主', '単ｵｯｽﾞ', '着順']
        for col in ensure_cols:
            if col not in df.columns: df[col] = np.nan

        df['R'] = pd.to_numeric(df['R'].apply(to_half_width), errors='coerce')
        df['正番'] = pd.to_numeric(df['正番'].apply(to_half_width), errors='coerce')
        df = df.dropna(subset=['R', '正番'])
        df['R'] = df['R'].astype(int); df['正番'] = df['正番'].astype(int)
        for col in ['騎手', '厩舎', '馬主', '馬名', '場名']:
            df[col] = df[col].astype(str).apply(normalize_name)
        df['単ｵｯｽﾞ'] = pd.to_numeric(df['単ｵｯｽﾞ'].apply(to_half_width), errors='coerce')
        return df.copy(), "success"
    except Exception as e: return pd.DataFrame(), str(e)

# --- 3. ネット競馬データ取得コア機能 ---
def fetch_netkeiba_result(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'EUC-JP'
        if response.status_code != 200: return None, None, f"拒否({response.status_code})"

        # URLから場名とRを解析 (例: race_id=2025 07 0506 01)
        # 07=中京, 01=1R
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
        
        if not target_table: return None, info, "表なし"

        result_map = {}
        rows = target_table.find_all('tr')
        header_cols = [th.get_text(strip=True) for th in rows[0].find_all(['th', 'td'])]
        try:
            idx_rank = [i for i, c in enumerate(header_cols) if '着順' in c][0]
            idx_umaban = [i for i, c in enumerate(header_cols) if '馬番' in c][0]
        except: return None, info, "列不明"

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
st.title("🏇 配置馬券術 データ収集システム（一括版）")

with st.sidebar:
    st.header("📂 1. データ読み込み")
    up_curr = st.file_uploader("当日データ(Excel/CSV)", type=['xlsx', 'csv'], key="curr")
    
    if 'analyzed_df' in st.session_state:
        st.divider()
        st.header("💾 3. 保存")
        csv = st.session_state['analyzed_df'].to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 着順入りCSVを保存", csv, "horse_results.csv")
        if st.sidebar.button("🗑️ データをクリア"):
            del st.session_state['analyzed_df']; st.rerun()

if up_curr:
    df_raw, status = load_data(up_curr)
    if status == "success" and not df_raw.empty:
        if 'analyzed_df' not in st.session_state:
            st.session_state['analyzed_df'] = df_raw
        
        df_work = st.session_state['analyzed_df']

        # --- 一括取得セクション ---
        st.header("🔗 2. 結果の一括取得")
        with st.expander("ここをクリックしてURLをまとめて貼り付け", expanded=True):
            urls_input = st.text_area("ネット競馬の結果URL（1行に1つずつ貼り付けてください）", height=200, help="結果ページのURLをまとめてコピー＆ペーストしてください")
            col1, col2 = st.columns([1, 4])
            with col1:
                bulk_btn = st.button("🚀 一括取得開始")
            with col2:
                st.caption("※取得には1レース数秒かかります。途中でブラウザを閉じないでください。")

            if bulk_btn and urls_input:
                urls = [u.strip() for u in urls_input.split('\n') if u.strip()]
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                success_count = 0
                for i, url in enumerate(urls):
                    status_text.text(f"取得中 ({i+1}/{len(urls)}): {url[:50]}...")
                    res, info, msg = fetch_netkeiba_result(url)
                    
                    if msg == "success" and info["place"]:
                        for u, r in res.items():
                            st.session_state['analyzed_df'].loc[
                                (st.session_state['analyzed_df']['場名'] == info["place"]) & 
                                (st.session_state['analyzed_df']['R'] == info["r"]) & 
                                (st.session_state['analyzed_df']['正番'] == u), '着順'
                            ] = r
                        success_count += 1
                    else:
                        st.warning(f"スキップ: {info['place'] if info else ''}{info['r'] if info else ''}R ({msg})")
                    
                    # 進行状況更新
                    progress_bar.progress((i + 1) / len(urls))
                    time.sleep(1.5) # サーバーへの負荷軽減のための待機
                
                status_text.success(f"完了！ {len(urls)}件中 {success_count}件のレースを反映しました。")
                st.rerun()

        # --- 個別確認・修正セクション ---
        st.divider()
        places = [p for p in df_work['場名'].unique().tolist() if str(p) != 'nan' and p != '']
        if places:
            st.subheader("📊 データの確認・個別修正")
            p_tabs = st.tabs(places)
            for p_tab, place in zip(p_tabs, places):
                with p_tab:
                    p_df = df_work[df_work['場名'] == place]
                    r_nums = sorted([int(r) for r in p_df['R'].unique() if not pd.isna(r)])
                    r_num = st.selectbox(f"レース選択 ({place})", r_nums, key=f"sel_{place}")
                    
                    current_race = st.session_state['analyzed_df'][
                        (st.session_state['analyzed_df']['場名'] == place) & 
                        (st.session_state['analyzed_df']['R'] == r_num)
                    ].sort_values('正番')
                    
                    edited = st.data_editor(
                        current_race[['正番', '馬名', '着順', '単ｵｯｽﾞ', '騎手']],
                        hide_index=True, use_container_width=True, key=f"ed_{place}_{r_num}"
                    )
                    
                    if st.button(f"✅ {place}{r_num}R の変更を保存", key=f"save_{place}_{r_num}"):
                        for _, row in edited.iterrows():
                            st.session_state['analyzed_df'].loc[
                                (st.session_state['analyzed_df']['場名'] == place) & 
                                (st.session_state['analyzed_df']['R'] == r_num) & 
                                (st.session_state['analyzed_df']['正番'] == row['正番']), '着順'
                            ] = row['着順']
                        st.success("保存しました")
    else:
        st.info("左側のメニューから当日のデータをアップロードしてください。")
