import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from bs4 import BeautifulSoup
import time

# --- 1. 基本設定 ---
st.set_page_config(page_title="配置馬券 データ収集（デバッグ版）", layout="wide")

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

# --- 2. データ読み込み（超強化版） ---
def load_data(file):
    try:
        if file.name.endswith('.xlsx'):
            df = pd.read_excel(file, engine='openpyxl')
        else:
            try: df = pd.read_csv(file, encoding='utf-8')
            except: df = pd.read_csv(file, encoding='cp932')
        
        # --- ヘッダー自動検索ロジック ---
        # どの行に「場所」や「R」などの重要ワードがあるか探す
        header_row_index = 0
        found = False
        for i in range(min(len(df), 20)):
            row_vals = [str(x) for x in df.iloc[i].values]
            # 「場所」か「馬名」があればそこがヘッダー
            if any('場所' in x or '馬名' in x or '騎手' in x for x in row_vals):
                df.columns = df.iloc[i]
                df = df.iloc[i+1:].reset_index(drop=True)
                found = True
                header_row_index = i
                break
        
        df.columns = df.columns.astype(str).str.strip()
        
        # 列名変換マップ
        name_map = {
            '場所': '場名', '場名': '場名', '競馬場': '場名', '開催': '場名',
            'R': 'R', 'Ｒ': 'R', 'レース': 'R',
            '番': '正番', '馬番': '正番', '正番': '正番',
            '着': '着順', '着順': '着順',
            '単オッズ': '単ｵｯｽﾞ', '単勝オッズ': '単ｵｯｽﾞ', 'オッズ': '単ｵｯｽﾞ'
        }
        # 既存の列名から部分一致で探して置換
        new_cols = {}
        for col in df.columns:
            for k, v in name_map.items():
                if k in col:
                    new_cols[col] = v
                    break
        df = df.rename(columns=new_cols)

        # デバッグ用に読み込んだ直後の状態を保持
        raw_cols = df.columns.tolist()

        # 必須列チェック（緩める）
        if 'R' not in df.columns or '場名' not in df.columns or '正番' not in df.columns:
            return df, f"必須項目が見つかりません。見つかった項目: {raw_cols}"

        # データのクリーニング
        df['R'] = pd.to_numeric(df['R'].apply(to_half_width), errors='coerce')
        df['正番'] = pd.to_numeric(df['正番'].apply(to_half_width), errors='coerce')
        df = df.dropna(subset=['R', '正番'])
        df['R'] = df['R'].astype(int)
        df['正番'] = df['正番'].astype(int)
        
        for col in ['騎手', '厩舎', '馬主', '馬名', '場名']:
            if col in df.columns:
                df[col] = df[col].astype(str).apply(normalize_name)
        
        if '着順' not in df.columns:
            df['着順'] = np.nan

        return df.copy(), "success"
    except Exception as e:
        return pd.DataFrame(), str(e)

# --- 3. ネット競馬取得 (変更なし) ---
def fetch_netkeiba_result(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'EUC-JP'
        if response.status_code != 200: return None, None, f"拒否({response.status_code})"

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
        idx_rank = [i for i, c in enumerate(header_cols) if '着順' in c][0]
        idx_umaban = [i for i, c in enumerate(header_cols) if '馬番' in c][0]

        for row in rows[1:]:
            cols = row.find_all('td')
            if len(cols) <= max(idx_rank, idx_umaban): continue
            r_m = re.search(r'\d+', cols[idx_rank].get_text(strip=True))
            u_m = re.search(r'\d+', cols[idx_umaban].get_text(strip=True))
            if r_m and u_m: result_map[int(u_m.group())] = int(r_m.group())
            elif u_m: result_map[int(u_m.group())] = 99
        return result_map, info, "success"
    except Exception as e: return None, None, str(e)

# --- 4. UI ---
st.title("🏇 データ収集デバッグ版")

up_curr = st.sidebar.file_uploader("ファイルアップロード", type=['xlsx', 'csv'])

if up_curr:
    df_raw, status = load_data(up_curr)
    
    if status == "success":
        st.success("✅ ファイル認識成功！")
        if 'analyzed_df' not in st.session_state:
            st.session_state['analyzed_df'] = df_raw
            
        # URL貼り付け欄
        st.header("🔗 URL一括貼り付け")
        urls_input = st.text_area("ここに1行ずつURLを貼り付け", height=200)
        if st.button("一括取得開始"):
            urls = [u.strip() for u in urls_input.split('\n') if u.strip()]
            for i, url in enumerate(urls):
                st.write(f"処理中: {url[-12:]}")
                res, info, msg = fetch_netkeiba_result(url)
                if msg == "success":
                    for u, r in res.items():
                        st.session_state['analyzed_df'].loc[
                            (st.session_state['analyzed_df']['場名'] == info["place"]) & 
                            (st.session_state['analyzed_df']['R'] == info["r"]) & 
                            (st.session_state['analyzed_df']['正番'] == u), '着順'] = r
                time.sleep(1)
            st.rerun()

        st.dataframe(st.session_state['analyzed_df'])
        
        csv = st.session_state['analyzed_df'].to_csv(index=False).encode('utf-8-sig')
        st.sidebar.download_button("📥 保存(CSV)", csv, "horse_results.csv")
        
    else:
        # 失敗した時の詳細表示
        st.error(f"❌ 読み込みエラー: {status}")
        st.write("### あなたのエクセルの状態:")
        st.write("プログラムは『場所』『R』『番』という名前の列を探していますが、見つかりません。")
        st.write("### 実際に読み取ったデータ（最初の数行）:")
        st.dataframe(df_raw.head(10)) # 生データを表示して確認させる

else:
    st.info("左側のサイドバーからファイルをアップロードしてください。")
