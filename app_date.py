import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from bs4 import BeautifulSoup
import urllib.request

# --- 1. 基本設定 ---
st.set_page_config(page_title="配置馬券 データ収集システム", layout="wide")

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

# --- 2. データ読み込み（「場所」列に特化） ---
@st.cache_data
def load_data(file):
    try:
        if file.name.endswith('.xlsx'):
            df = pd.read_excel(file, engine='openpyxl')
        else:
            try: df = pd.read_csv(file, encoding='utf-8')
            except: df = pd.read_csv(file, encoding='cp932')
        
        # ヘッダー位置の自動調整（10行目までスキャンして項目名を探す）
        found_header = False
        if not any(col in str(df.columns) for col in ['場所', '馬', '番', 'R']):
            for i in range(min(len(df), 10)):
                row_values = [str(x) for x in df.iloc[i].values]
                if any('場所' in x or '番' in x or 'R' in x for x in row_values):
                    df.columns = df.iloc[i]
                    df = df.iloc[i+1:].reset_index(drop=True)
                    found_header = True
                    break

        df.columns = df.columns.astype(str).str.strip()
        
        # 列名の名寄せ（「場所」を「場名」として内部統一）
        name_map = {
            '場所': '場名', '競馬場': '場名', '開催': '場名',
            'レース': 'R', 'Ｒ': 'R', '番': '正番', '馬番': '正番',
            '単オッズ': '単ｵｯｽﾞ', '単勝オッズ': '単ｵｯｽﾞ', 'オッズ': '単ｵｯｽﾞ',
            '着': '着順'
        }
        df = df.rename(columns=name_map)
        
        # 必須カラムのチェックと作成
        ensure_cols = ['R', '場名', '馬名', '正番', '騎手', '厩舎', '馬主', '単ｵｯｽﾞ', '着順']
        for col in ensure_cols:
            if col not in df.columns:
                df[col] = np.nan

        # 型変換
        df['R'] = pd.to_numeric(df['R'].apply(to_half_width), errors='coerce')
        df['正番'] = pd.to_numeric(df['正番'].apply(to_half_width), errors='coerce')
        df = df.dropna(subset=['R', '正番'])
        df['R'] = df['R'].astype(int); df['正番'] = df['正番'].astype(int)
        
        for col in ['騎手', '厩舎', '馬主', '馬名', '場名']:
            df[col] = df[col].astype(str).apply(normalize_name)
            
        df['単ｵｯｽﾞ'] = pd.to_numeric(df['単ｵｯｽﾞ'].apply(to_half_width), errors='coerce')
        return df.copy(), "success"
    except Exception as e:
        return pd.DataFrame(), str(e)

# --- 3. ネット競馬自動取得 ---
def fetch_netkeiba_result(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            'Referer': 'https://race.netkeiba.com/'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'EUC-JP'
        if response.status_code != 200: return None, f"アクセス拒否(Error {response.status_code})"

        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table')
        target_table = None
        for t in tables:
            t_text = t.get_text()
            if '着順' in t_text and '馬番' in t_text:
                target_table = t
                break
        
        if not target_table: return None, "着順表が見つかりません"

        result_map = {}
        rows = target_table.find_all('tr')
        header_cols = [th.get_text(strip=True) for th in rows[0].find_all(['th', 'td'])]
        
        try:
            idx_rank = [i for i, c in enumerate(header_cols) if '着順' in c][0]
            idx_umaban = [i for i, c in enumerate(header_cols) if '馬番' in c][0]
        except: return None, "列の特定に失敗しました"

        for row in rows[1:]:
            cols = row.find_all('td')
            if len(cols) <= max(idx_rank, idx_umaban): continue
            r_txt = cols[idx_rank].get_text(strip=True)
            u_txt = cols[idx_umaban].get_text(strip=True)
            r_m = re.search(r'\d+', r_txt)
            u_m = re.search(r'\d+', u_txt)
            if r_m and u_m: result_map[int(u_m.group())] = int(r_m.group())
            elif u_m: result_map[int(u_m.group())] = 99
        
        return result_map, "success"
    except Exception as e: return None, str(e)

# --- 4. UI 画面表示 ---
st.title("🏇 配置馬券 データ収集システム")

with st.sidebar:
    st.header("📂 読み込み")
    up_curr = st.file_uploader("当日データ(Excel/CSV)", type=['xlsx', 'csv'], key="curr")
    
    if 'analyzed_df' in st.session_state:
        st.divider()
        st.header("💾 保存")
        csv = st.session_state['analyzed_df'].to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 着順入りCSVを保存", csv, "horse_data_with_results.csv")
        if st.button("🗑️ データをリセット"):
            del st.session_state['analyzed_df']
            st.rerun()

if up_curr:
    df_raw, status = load_data(up_curr)
    
    if status == "success" and not df_raw.empty:
        # 初回読み込み時のセッション登録
        if 'analyzed_df' not in st.session_state:
            st.session_state['analyzed_df'] = df_raw
        
        df_work = st.session_state['analyzed_df']
        
        # 会場（場所）リストを作成
        places = [p for p in df_work['場名'].unique().tolist() if str(p) != 'nan' and p != '']
        
        if places:
            st.subheader("📝 レース結果の自動取得")
            p_tabs = st.tabs(places)
            for p_tab, place in zip(p_tabs, places):
                with p_tab:
                    p_df = df_work[df_work['場名'] == place]
                    r_nums = sorted([int(r) for r in p_df['R'].unique() if not pd.isna(r)])
                    
                    if r_nums:
                        r_num = st.selectbox(f"レースを選択 ({place})", r_nums, key=f"sel_{place}")
                        
                        with st.form(key=f"form_{place}_{r_num}"):
                            url = st.text_input("ネット競馬結果URL", placeholder="https://race.netkeiba.com/race/result.html?race_id=...")
                            btn = st.form_submit_button("🌐 結果を自動取得")
                            
                            if btn and url:
                                res, msg = fetch_netkeiba_result(url)
                                if msg == "success":
                                    st.success(f"{len(res)}頭の結果を取得しました！")
                                    for u, r in res.items():
                                        st.session_state['analyzed_df'].loc[
                                            (st.session_state['analyzed_df']['場名'] == place) & 
                                            (st.session_state['analyzed_df']['R'] == r_num) & 
                                            (st.session_state['analyzed_df']['正番'] == u), '着順'
                                        ] = r
                                else:
                                    st.error(f"取得失敗: {msg}")
                        
                        st.write(f"📊 {place}{r_num}R の現在のデータ:")
                        current_race_data = st.session_state['analyzed_df'][
                            (st.session_state['analyzed_df']['場名'] == place) & 
                            (st.session_state['analyzed_df']['R'] == r_num)
                        ].sort_values('正番')
                        
                        edited_data = st.data_editor(
                            current_race_data[['正番', '馬名', '着順', '単ｵｯｽﾞ']],
                            hide_index=True, use_container_width=True, key=f"ed_{place}_{r_num}"
                        )
                        
                        if st.button(f"✅ {place}{r_num}R の手動入力を保存", key=f"save_{place}_{r_num}"):
                            for _, row in edited_data.iterrows():
                                st.session_state['analyzed_df'].loc[
                                    (st.session_state['analyzed_df']['場名'] == place) & 
                                    (st.session_state['analyzed_df']['R'] == r_num) & 
                                    (st.session_state['analyzed_df']['正番'] == row['正番']), '着順'
                                ] = row['着順']
                            st.rerun()
            
            st.divider()
            st.info("💡 取得が終わったら、左メニューの「📥 着順入りCSVを保存」からダウンロードしてください。")

        else:
            st.error("❌ 会場名（場所）を特定できませんでした。")
            st.write("ファイル内に「場所」という列があるか確認してください。")
            st.write("読み込んだ列名:", df_raw.columns.tolist())
            st.dataframe(df_raw.head())
    else:
        if up_curr:
            st.error(f"読み込み失敗: {status}")
