import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from bs4 import BeautifulSoup
import time

# --- 1. 基本設定 ---
st.set_page_config(page_title="配置馬券 データ収集システム（エラー修正版）", layout="wide")

# 【重複回避用】列名が重なった場合に自動で番号を振る関数
def make_columns_unique(df):
    cols = []
    counts = {}
    for col in df.columns:
        col_str = str(col).strip()
        if col_str in counts:
            counts[col_str] += 1
            cols.append(f"{col_str}_{counts[col_str]}")
        else:
            counts[col_str] = 0
            cols.append(col_str)
    df.columns = cols
    return df

def to_half_width(text):
    if pd.isna(text): return text
    table = str.maketrans('０１２３４５６７８９．', '0123456789.')
    return re.sub(r'[^\d\.]', '', str(text).translate(table))

def normalize_name(x):
    if pd.isna(x): return ''
    s = str(x).strip().replace('　', '').replace(' ', '')
    return re.split(r'[,(（/]', s)[0]

JYO_MAP = {'01':'札幌','02':'函館','03':'福島','04':'新潟','05':'東京','06':'中山','07':'中京','08':'京都','09':'阪神','10':'小倉'}

# --- 2. データ読み込み（重複対策版） ---
def load_data(file):
    try:
        if file.name.endswith('.xlsx'):
            df = pd.read_excel(file, engine='openpyxl')
        else:
            try: df = pd.read_csv(file, encoding='utf-8')
            except: df = pd.read_csv(file, encoding='cp932')
        
        # 読み込み直後に重複を解消
        df = make_columns_unique(df)

        # 項目名を探す（20行目までスキャン）
        for i in range(min(len(df), 20)):
            row_vals = [str(x) for x in df.iloc[i].values]
            if any('場所' in x or 'R' in x or '馬名' in x for x in row_vals):
                df.columns = df.iloc[i]
                df = df.iloc[i+1:].reset_index(drop=True)
                # ヘッダー設定後にもう一度重複を解消
                df = make_columns_unique(df)
                break
        
        # 列名の名寄せ
        name_map = {'場所':'場名','R':'R','Ｒ':'R','番':'正番','馬番':'正番','着順':'着順','着':'着順','単勝オッズ':'単ｵｯｽﾞ','オッズ':'単ｵｯｽﾞ'}
        new_cols = []
        for c in df.columns:
            target = str(c).strip()
            for k, v in name_map.items():
                if k in target:
                    target = v
                    break
            new_cols.append(target)
        
        df.columns = new_cols
        # 名寄せ後（「場所」と「会場」が両方「場名」になった場合など）に再度重複を解消
        df = make_columns_unique(df)

        # 必須列の確保
        for col in ['場名', 'R', '正番', '着順']:
            if col not in df.columns: df[col] = np.nan
        
        return df, "success"
    except Exception as e:
        return pd.DataFrame(), str(e)

# --- 3. ネット競馬データ取得 ---
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

with st.sidebar:
    st.header("📂 1. ファイル選択")
    up_curr = st.file_uploader("当日配置表(Excel/CSV)", type=['xlsx', 'csv'])
    
    if 'df' in st.session_state:
        st.divider()
        st.header("💾 3. 保存")
        csv = st.session_state['df'].to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 CSVをダウンロード", csv, "horse_results.csv")
        if st.button("🗑️ データをクリア"):
            del st.session_state['df']
            st.rerun()

if up_curr:
    if 'df' not in st.session_state:
        df, status = load_data(up_curr)
        if status == "success":
            st.session_state['df'] = df
        else:
            st.error(f"読み込みエラー: {status}")

    if 'df' in st.session_state:
        st.success("✅ ファイルを正常に読み込みました")
        
        # URL貼り付けエリア
        st.header("🔗 2. URL一括貼り付け")
        urls_input = st.text_area("ネット競馬結果URL（1行に1つずつ）", height=200)
        
        if st.button("🚀 一括取得開始"):
            if urls_input:
                urls = [u.strip() for u in urls_input.split('\n') if u.strip()]
                progress = st.progress(0)
                status_box = st.empty()
                
                for i, url in enumerate(urls):
                    status_box.text(f"処理中 ({i+1}/{len(urls)}): {url[-12:]}")
                    res, info, msg = fetch_netkeiba_result(url)
                    if msg == "success":
                        for u, r in res.items():
                            st.session_state['df'].loc[
                                (st.session_state['df']['場名']==info['place']) & 
                                (st.session_state['df']['R']==info['r']) & 
                                (st.session_state['df']['正番']==u), '着順'
                            ] = r
                    progress.progress((i+1)/len(urls))
                    time.sleep(1)
                
                status_box.success("全ての取得が完了しました！")
                st.rerun()

        st.divider()
        st.subheader("📊 現在のデータ状況")
        # 表示直前に念のため列名の重複がないか再度クリーンアップ
        final_df = make_columns_unique(st.session_state['df'].copy())
        st.dataframe(final_df, use_container_width=True)

else:
    st.info("👈 左側のメニューからファイルを読み込ませてください。")
