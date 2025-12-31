import streamlit as st
import pandas as pd
import numpy as np
import re
import plotly.express as px
import requests
from bs4 import BeautifulSoup

# --- 1. 基本設定 ---
st.set_page_config(page_title="配置馬券術 データ収集システム", layout="wide")

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

# --- 2. データ読み込み (既存のまま) ---
@st.cache_data
def load_data(file):
    try:
        if file.name.endswith('.xlsx'):
            df = pd.read_excel(file, engine='openpyxl')
        else:
            try: df = pd.read_csv(file, encoding='utf-8')
            except: df = pd.read_csv(file, encoding='cp932')
        
        if not any(col in str(df.columns) for col in ['馬', '番', 'R', '騎']):
            for i in range(min(len(df), 10)):
                if any(x in str(df.iloc[i].values) for x in ['馬', '番', 'R']):
                    df.columns = df.iloc[i]; df = df.iloc[i+1:].reset_index(drop=True); break
        df.columns = df.columns.astype(str).str.strip()
        name_map = {'場所':'場名','開催':'場名','競馬場':'場名','調教師':'厩舎','レース':'R','番':'正番','馬番':'正番','単勝オッズ':'単ｵｯｽﾞ','オッズ':'単ｵｯｽﾞ','着':'着順'}
        df = df.rename(columns=name_map)
        ensure_cols = ['R', '場名', '馬名', '正番', '騎手', '厩舎', '馬主', '単ｵｯｽﾞ', '着順']
        for col in ensure_cols:
            if col not in df.columns: df[col] = np.nan
        df['R'] = pd.to_numeric(df['R'].apply(to_half_width), errors='coerce')
        df['正番'] = pd.to_numeric(df['正番'].apply(to_half_width), errors='coerce')
        df = df.dropna(subset=['R', '正番'])
        df['R'] = df['R'].astype(int); df['正番'] = df['正番'].astype(int)
        for col in ['騎手', '厩舎', '馬主', '馬名', '場名']:
            df[col] = df[col].apply(normalize_name)
        df['単ｵｯｽﾞ'] = pd.to_numeric(df['単ｵｯｽﾞ'].apply(to_half_width), errors='coerce')
        return df.copy(), "success"
    except Exception as e: return pd.DataFrame(), str(e)

# --- 3. 配置計算 (既存のまま) ---
def analyze_haichi(df_curr, df_prev=None):
    # (中略：以前のロジックと同じため省略。実際にはここに配置計算コードが入ります)
    return df_curr # 実際には計算済みdfを返す

# --- 4. 判定ロジック (既存のまま) ---
def apply_ranking_logic(df_in):
    # (中略：以前のロジックと同じ)
    return df_in

# --- 5. ネット競馬自動取得 (究極の回避版) ---
def fetch_netkeiba_result(url):
    try:
        # 1. 通信設定 (より本物のブラウザに偽装)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            'Referer': 'https://race.netkeiba.com/'
        }
        
        # 2. ページ取得
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'EUC-JP' # ネット競馬の文字コードを明示
        
        if response.status_code != 200:
            return None, f"アクセス拒否されました(Error {response.status_code})"

        # 3. 解析 (BeautifulSoup)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # すべてのテーブルを取得して、着順表っぽいものを探す
        tables = soup.find_all('table')
        target_table = None
        for t in tables:
            t_text = t.get_text()
            if '着順' in t_text and '馬番' in t_text and '単勝オッズ' in t_text:
                target_table = t
                break
        
        if not target_table:
            return None, "着順表が見つかりません。レースが終了しているか確認してください。"

        # 4. データの抽出
        result_map = {}
        rows = target_table.find_all('tr')
        
        # ヘッダーから列のインデックス（何番目か）を特定する
        header_cols = [th.get_text(strip=True) for th in rows[0].find_all(['th', 'td'])]
        try:
            idx_rank = [i for i, c in enumerate(header_cols) if '着順' in c][0]
            idx_umaban = [i for i, c in enumerate(header_cols) if '馬番' in c][0]
        except IndexError:
            return None, "表の列名が正しく認識できませんでした。"

        # 各行から馬番と着順を抜く
        for row in rows[1:]:
            cols = row.find_all('td')
            if len(cols) <= max(idx_rank, idx_umaban): continue
            
            rank_txt = cols[idx_rank].get_text(strip=True)
            umaban_txt = cols[idx_umaban].get_text(strip=True)
            
            # 数字のみ抽出
            r_match = re.search(r'\d+', rank_txt)
            u_match = re.search(r'\d+', umaban_txt)
            
            if r_match and u_match:
                result_map[int(u_match.group())] = int(r_match.group())
            elif u_match:
                result_map[int(u_match.group())] = 99 # 取消などは99

        return result_map, "success"
        
    except Exception as e:
        return None, f"例外エラー: {str(e)}"

# --- 6. UI (画面表示) ---
st.title("🏇 配置馬券術 データ収集システム")

with st.sidebar:
    st.header("📂 読み込み")
    up_curr = st.file_uploader("当日データ", type=['xlsx', 'csv'], key="curr")
    if 'analyzed_df' in st.session_state:
        csv = st.session_state['analyzed_df'].to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 着順入りCSVをダウンロード", csv, f"progress_data.csv")

if up_curr:
    df_raw, status = load_data(up_curr)
    if status == "success":
        if 'analyzed_df' not in st.session_state:
            st.session_state['analyzed_df'] = df_raw # 簡易化のため
        
        st.subheader("📝 結果の自動取得")
        
        places = sorted(st.session_state['analyzed_df']['場名'].unique())
        p_tabs = st.tabs(places)
        
        for p_tab, place in zip(p_tabs, places):
            with p_tab:
                p_df = st.session_state['analyzed_df'][st.session_state['analyzed_df']['場名'] == place]
                r_num = st.selectbox(f"レースを選択 ({place})", sorted(p_df['R'].unique()), key=f"sel_{place}")
                
                race_full = p_df[p_df['R'] == r_num].sort_values('正番')
                
                # 自動取得フォーム
                with st.form(key=f"form_{place}_{r_num}"):
                    nk_url = st.text_input("ネット競馬結果URL", placeholder="https://race.netkeiba.com/race/result.html?race_id=...")
                    btn = st.form_submit_button("🌐 このレースの結果を取得")
                    
                    if btn and nk_url:
                        res, msg = fetch_netkeiba_result(nk_url)
                        if msg == "success":
                            st.success(f"{len(res)}頭の着順を反映しました。下のボタンで確定させてください。")
                            for u, r in res.items():
                                st.session_state['analyzed_df'].loc[
                                    (st.session_state['analyzed_df']['場名'] == place) & 
                                    (st.session_state['analyzed_df']['R'] == r_num) & 
                                    (st.session_state['analyzed_df']['正番'] == u), '着順'] = r
                        else:
                            st.error(msg)
                
                # 現在の確認用
                st.write(f"現在の {place}{r_num}R データ:")
                st.dataframe(st.session_state['analyzed_df'][
                    (st.session_state['analyzed_df']['場名'] == place) & 
                    (st.session_state['analyzed_df']['R'] == r_num)
                ][['正番','馬名','着順','単ｵｯｽﾞ']], hide_index=True)

        if st.button("🔄 全体の入力を確定して保存準備"):
            st.success("確定しました。左メニューからCSVをダウンロードしてください。")
