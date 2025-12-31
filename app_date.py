import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from bs4 import BeautifulSoup
import time

st.set_page_config(page_title="データ収集システム（エラー修正版）", layout="wide")

# --- 1. ヘルパー関数 ---
def to_half_width(text):
    if pd.isna(text): return text
    table = str.maketrans('０１２３４５６７８９．', '0123456789.')
    return re.sub(r'[^\d\.]', '', str(text).translate(table))

def normalize_name(x):
    if pd.isna(x): return ''
    s = str(x).strip().replace('　', '').replace(' ', '')
    return re.split(r'[,(（/]', s)[0]

JYO_MAP = {'01':'札幌','02':'函館','03':'福島','04':'新潟','05':'東京','06':'中山','07':'中京','08':'京都','09':'阪神','10':'小倉'}

# --- 2. データ読み込み（重複回避機能付き） ---
def load_data(file):
    try:
        if file.name.endswith('.xlsx'):
            df = pd.read_excel(file, engine='openpyxl')
        else:
            try: df = pd.read_csv(file, encoding='utf-8')
            except: df = pd.read_csv(file, encoding='cp932')
        
        # 1. 読み込み直後の列名の重複を強制回避
        cols = pd.Series(df.columns)
        for d in cols[cols.duplicated()].unique():
            cols[cols == d] = [f"{d}_{i}" if i != 0 else d for i in range(len(cols[cols == d]))]
        df.columns = cols

        # 2. 項目名を探す（20行目までスキャン）
        for i in range(min(len(df), 20)):
            row_vals = [str(x) for x in df.iloc[i].values]
            if any('場所' in x or 'R' in x or '馬名' in x for x in row_vals):
                df.columns = df.iloc[i]
                df = df.iloc[i+1:].reset_index(drop=True)
                break
        
        # 3. 列名の正規化（ここでも重複が起きないように制御）
        df.columns = [str(c).strip() for c in df.columns]
        name_map = {'場所':'場名','R':'R','Ｒ':'R','番':'正番','馬番':'正番','着順':'着順','着':'着順','単勝オッズ':'単ｵｯｽﾞ','オッズ':'単ｵｯｽﾞ'}
        
        new_columns = []
        used_names = set()
        for c in df.columns:
            target_name = c
            for k, v in name_map.items():
                if k == c: # 完全一致を優先
                    target_name = v
                    break
            
            # もし書き換え後の名前が既に使われていたら番号をつける
            base_name = target_name
            counter = 1
            while target_name in used_names:
                target_name = f"{base_name}_{counter}"
                counter += 1
            
            new_columns.append(target_name)
            used_names.add(target_name)
        
        df.columns = new_columns

        # 最低限の列を確保
        for col in ['場名', 'R', '正番', '着順']:
            if col not in df.columns: df[col] = np.nan
        
        return df, "success"
    except Exception as e:
        return pd.DataFrame(), str(e)

# --- 3. ネット競馬取得 ---
def fetch_netkeiba_result(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'EUC-JP'
        
        rid_match = re.search(r'race_id=(\d{12})', url)
        info = {"place": JYO_MAP.get(rid_match.group(1)[4:6], "") if rid_match else "", "r": int(rid_match.group(1)[10:12]) if rid_match else 0}

        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table', id='All_Result_Table') or soup.find('table', class_=lambda x: x and 'ResultRefund' in x)
        if not table: return None, info, "表なし"

        result_map = {}
        rows = table.find_all('tr', class_=lambda x: x and 'HorseList' in x)
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 3: continue
            r_m = re.search(r'\d+', cols[0].get_text(strip=True))
            u_m = re.search(r'\d+', cols[2].get_text(strip=True))
            if u_m: result_map[int(u_m.group())] = int(r_m.group()) if r_m else 99
        return result_map, info, "success"
    except Exception as e: return None, None, str(e)

# --- 4. UI 画面 ---
st.title("🏇 データ収集システム（重複エラー対策版）")

up_curr = st.sidebar.file_uploader("ファイルを選択", type=['xlsx', 'csv'])

if up_curr:
    if 'df' not in st.session_state:
        df, status = load_data(up_curr)
        st.session_state['df'] = df

    st.success("✅ ファイルを読み込みました")
    
    # URL一括貼り付けセクション
    st.header("🔗 URL一括貼り付け")
    urls_input = st.text_area("ネット競馬の結果URLを1行ずつ貼り付けてください", height=200)
    
    if st.button("🚀 一括取得開始"):
        if urls_input:
            urls = [u.strip() for u in urls_input.split('\n') if u.strip()]
            progress = st.progress(0)
            for i, url in enumerate(urls):
                res, info, msg = fetch_netkeiba_result(url)
                if msg == "success":
                    for u, r in res.items():
                        # インデックスを特定して着順を更新
                        st.session_state['df'].loc[(st.session_state['df']['場名']==info['place']) & (st.session_state['df']['R']==info['r']) & (st.session_state['df']['正番']==u), '着順'] = r
                    st.write(f"✅ 取得成功: {info['place']}{info['r']}R")
                else:
                    st.error(f"❌ 失敗: {url[-12:]} ({msg})")
                progress.progress((i+1)/len(urls))
                time.sleep(1)
            st.rerun()

    st.divider()
    st.subheader("📊 現在のデータプレビュー")
    # 重複回避したdfを表示
    st.dataframe(st.session_state['df'], use_container_width=True)
    
    csv = st.session_state['df'].to_csv(index=False).encode('utf-8-sig')
    st.sidebar.download_button("📥 着順入りCSVを保存", csv, "horse_results.csv")
    if st.sidebar.button("🗑️ クリア"):
        del st.session_state['df']; st.rerun()

else:
    st.info("👈 左のサイドバーからファイルをアップロードしてください。")
