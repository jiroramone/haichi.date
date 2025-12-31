import streamlit as st
import pandas as pd
import numpy as np
import re
import plotly.express as px
import urllib.request
from bs4 import BeautifulSoup

# --- 1. 基本設定 ---
st.set_page_config(page_title="配置馬券術 データ収集システム", layout="wide")

# 半角変換ヘルパー
def to_half_width(text):
    if pd.isna(text): return text
    text = str(text)
    table = str.maketrans('０１２３４５６７８９．', '0123456789.')
    return re.sub(r'[^\d\.]', '', text.translate(table))

# 名前正規化
def normalize_name(x):
    if pd.isna(x): return ''
    s = str(x).strip().replace('　', '').replace(' ', '')
    s = re.split(r'[,(（/]', s)[0]
    return re.sub(r'[★☆▲△◇$*]', '', s)

# --- 2. データ読み込み ---
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
                    df.columns = df.iloc[i]
                    df = df.iloc[i+1:].reset_index(drop=True)
                    break

        df.columns = df.columns.astype(str).str.strip()
        name_map = {
            '場所': '場名', '開催': '場名', '競馬場': '場名',
            '調教師': '厩舎', '調教師名': '厩舎', '厩舎名': '厩舎',
            '騎手名': '騎手', 'レース': 'R', 'Ｒ': 'R', '番': '正番', '馬番': '正番',
            '単オッズ': '単ｵｯｽﾞ', '単勝オッズ': '単ｵｯｽﾞ', 'オッズ': '単ｵｯｽﾞ',
            '正循': '正循環', '逆循': '逆循環', '着': '着順'
        }
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

# --- 3. 配置計算エンジン ---
def analyze_haichi(df_curr, df_prev=None):
    df = df_curr.copy()
    if 'タイプ' in df.columns and df['タイプ'].notna().any(): return df
    max_umaban = df.groupby(['場名', 'R'])['正番'].transform('max')
    df['頭数'] = max_umaban.fillna(16).astype(int)
    df['逆番'] = (df['頭数'] + 1) - df['正番']
    df['正循環'] = df['頭数'] + df['正番']
    df['逆循環'] = df['頭数'] + df['逆番']
    for c in ['正番', '逆番', '正循環', '逆循環']:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype(int)
    df['タイプ_list'] = [[] for _ in range(len(df))]
    df['属性_list'] = [[] for _ in range(len(df))]
    df['パターン_list'] = [[] for _ in range(len(df))]
    df['スコア'] = 0.0
    idx_map = {(row['場名'], row['R'], row['正番']): idx for idx, row in df.iterrows()}
    blue_info = []
    for col in ['騎手', '厩舎', '馬主']:
        g_keys = ['場名', col] if col == '騎手' else [col]
        for name, group in df.groupby(g_keys):
            if len(group) < 2 or not name: continue
            all_sets = [{r['正番'], r['逆番'], r['正循環'], r['逆循環']} for _, r in group.iterrows()]
            common = set.intersection(*all_sets)
            if common:
                for _, row in group.iterrows():
                    idx = idx_map.get((row['場名'], row['R'], row['正番']))
                    if idx is not None:
                        df.at[idx, 'タイプ_list'].append(f'★{col}青塗'); df.at[idx, '属性_list'].append(f'{col}:{name}')
                        df.at[idx, 'パターン_list'].append('青塗'); df.at[idx, 'スコア'] += 9.0 + (1.0 if col == '騎手' else 0.2)
                        blue_info.append({'場名':row['場名'], 'R':row['R'], '正番':row['正番'], '属性':f"{col}:{name}"})
    for b in blue_info:
        for t_num in [b['正番']-1, b['正番']+1]:
            key = (b['場名'], b['R'], t_num)
            if key in idx_map:
                idx = idx_map[key]
                if not any('青塗隣' in str(x) for x in df.at[idx, 'タイプ_list']):
                    df.at[idx, 'タイプ_list'].append('△青塗隣'); df.at[idx, '属性_list'].append(f'隣:{b["属性"]}'); df.at[idx, 'パターン_list'].append('青隣'); df.at[idx, 'スコア'] += 9.0
    pair_labels = list("ABCDEFGHIJKLMNOP")
    for col in ['騎手', '厩舎', '馬主']:
        for name, group in df.groupby(['場名', col] if col=='騎手' else col):
            if len(group) < 2 or not name: continue
            rows = group.sort_values('R').to_dict('records')
            for i in range(len(rows)-1):
                r1, r2 = rows[i], rows[i+1]
                v1, v2 = [r1[c] for c in ['正番','逆番','正循環','逆循環']], [r2[c] for c in ['正番','逆番','正循環','逆循環']]
                pats = [pair_labels[x*4+y] for x in range(4) for y in range(4) if v1[x]==v2[y] and v1[x]!=0]
                if pats:
                    is_c = any(x in pats for x in ['C','D','G','H'])
                    for r_data in [r1, r2]:
                        idx = idx_map.get((r_data['場名'], r_data['R'], r_data['正番']))
                        if idx is not None:
                            df.at[idx, 'タイプ_list'].append('◎チャンス' if is_c else '○狙い目')
                            df.at[idx, '属性_list'].append(f'{col}:{name}'); df.at[idx, 'パターン_list'].append("".join(pats))
                            df.at[idx, 'スコア'] += 4.0 if is_c else 3.0
    if df_prev is not None and not df_prev.empty:
        for idx, row in df.iterrows():
            prev_match = df_prev[(df_prev['場名'] == row['場名']) & (df_prev['R'] == row['R']) & (df_prev['騎手'] == row['騎手'])]
            for _, p_row in prev_match.iterrows():
                if {row['正番'],row['逆番'],row['正循環'],row['逆循環']}.intersection({p_row['正番'],p_row['逆番'],p_row['正循環'],p_row['逆循環']}):
                    df.at[idx, 'タイプ_list'].append('★前日同配置'); df.at[idx, '属性_list'].append(f'前日:騎手:{row["騎手"]}'); df.at[idx, 'パターン_list'].append('前日'); df.at[idx, 'スコア'] += 8.3
    df['タイプ'] = df['タイプ_list'].apply(lambda x: ' / '.join(x) if isinstance(x, list) else x)
    df['属性'] = df['属性_list'].apply(lambda x: ' / '.join(list(set(x))) if isinstance(x, list) else x)
    df['パターン'] = df['パターン_list'].apply(lambda x: ','.join(x) if isinstance(x, list) else x)
    return df

# --- 4. 判定ロジック ---
def apply_ranking_logic(df_in):
    if df_in.empty: return df_in
    df = df_in.copy()
    df['着順'] = pd.to_numeric(df['着順'], errors='coerce')
    hit_results = df[df['着順'] <= 3]
    hit_attrs = set([a.replace('隣:', '').replace('前日:', '') for _, row in hit_results.iterrows() for a in str(row.get('属性', '')).split(' / ')])
    hit_pats = set([p for pats in hit_results['パターン'].dropna() for p in str(pats).split(',') if p])
    def get_metrics(row):
        score = row.get('スコア', 0); p_list = str(row.get('パターン', '')).split(',')
        bonus = 4.0 if any(p in hit_pats and len(p)==1 for p in p_list) else 0.0
        reasons = []
        for ra in str(row.get('属性', '')).split(' / '):
            is_neighbor = ra.startswith('隣:'); cra = ra.replace('隣:', '').replace('前日:', '')
            if cra in hit_attrs: reasons.append("本体好走" if is_neighbor else f"{cra.split(':')[0] if ':' in cra else '本人'}好走")
        penalty = -3.0 if reasons else 0.0
        total = score + bonus + penalty + (-30.0 if pd.to_numeric(row.get('単ｵｯｽﾞ'), errors='coerce') > 49.9 else 0.0)
        rec = "👑 盤石の軸" if total >= 15 else "✨ 推奨軸" if total >= 12 else "🔥 激熱相手" if total >= 10 else "▲ 配置注目" if score > 0 else ""
        return pd.Series([total, f"⚠️{','.join(set(reasons))}(-3)" if reasons else "", rec])
    df[['総合スコア', 'エネルギー状態', '推奨買い目']] = df.apply(get_metrics, axis=1)
    return df

# --- 5. ネット競馬自動取得 (BeautifulSoup版) ---
def fetch_netkeiba_result(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('euc-jp', errors='replace')
        
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table', id='All_Result_Table')
        
        if not table:
            return None, "着順テーブル(All_Result_Table)が見つかりませんでした"

        result_map = {}
        rows = table.find_all('tr', class_='HorseList')
        
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 3: continue
            try:
                rank_text = cols[0].get_text(strip=True)
                umaban_text = cols[2].get_text(strip=True)
                rank_match = re.search(r'\d+', rank_text)
                umaban_match = re.search(r'\d+', umaban_text)
                if rank_match and umaban_match:
                    result_map[int(umaban_match.group())] = int(rank_match.group())
                elif umaban_match:
                    result_map[int(umaban_match.group())] = 99 # 数字以外は着外扱い
            except: continue
                
        return result_map, "success"
    except Exception as e:
        return None, str(e)

# --- 6. UI ---
st.title("🏇 配置馬券術 分析システム（データ収集用）")
with st.sidebar:
    st.header("📂 読み込み")
    up_curr = st.file_uploader("当日データ", type=['xlsx', 'csv'], key="curr")
    up_prev = st.file_uploader("前日データ", type=['xlsx', 'csv'], key="prev")
    if up_curr:
        pure_name = up_curr.name.replace('progress_', '').replace('.csv', '').replace('.xlsx', '')
        if "current_pure_name" not in st.session_state: st.session_state["current_pure_name"] = pure_name
        elif st.session_state["current_pure_name"] != pure_name:
            st.session_state["current_pure_name"] = pure_name
            if "analyzed_df" in st.session_state: del st.session_state["analyzed_df"]; st.rerun()
    st.divider()
    if 'analyzed_df' in st.session_state:
        csv = st.session_state['analyzed_df'].to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 着順入りCSVを保存", csv, f"progress_{up_curr.name if up_curr else 'data'}.csv")

if up_curr:
    df_raw, status = load_data(up_curr)
    df_p_raw, _ = load_data(up_prev) if up_prev else (None, None)
    if status == "success":
        if 'analyzed_df' not in st.session_state: st.session_state['analyzed_df'] = apply_ranking_logic(analyze_haichi(df_raw, df_p_raw))
        
        # 内部データの更新用に関数化
        def update_ranks(fetched_ranks):
            df = st.session_state['analyzed_df'].copy()
            for u, r in fetched_ranks.items():
                # 場名とR、正番が一致する行を更新
                # (URLが1レースごとなので、全レース一括更新はUI側のループで処理)
                pass

        full_df = st.session_state['analyzed_df']
        st.subheader("📝 結果入力")
        
        # 結果入力フォーム
        with st.form("result_form"):
            places = sorted(full_df['場名'].unique())
            p_tabs = st.tabs(places); edited_dfs = []
            for p_tab, place in zip(p_tabs, places):
                with p_tab:
                    p_df = full_df[full_df['場名'] == place]
                    r_nums = sorted(p_df['R'].unique())
                    r_tabs = st.tabs([f"{r}R" for r in r_nums])
                    for r_tab, r_num in zip(r_tabs, r_nums):
                        with r_tab:
                            race_full = p_df[p_df['R'] == r_num].sort_values('正番')
                            
                            # 自動取得エリア
                            c1, c2 = st.columns([3, 1])
                            with c1: nk_url = st.text_input(f"ネット競馬URL ({place}{r_num}R)", key=f"url_{place}_{r_num}")
                            with c2: 
                                # 各レースごとの自動取得ボタン
                                auto_btn = st.form_submit_button(f"🌐 自動取得", key=f"btn_{place}_{r_num}")
                            
                            if auto_btn and nk_url:
                                res, msg = fetch_netkeiba_result(nk_url)
                                if msg == "success":
                                    st.success(f"{len(res)}頭の着順を取得しました！")
                                    for u, r in res.items():
                                        race_full.loc[race_full['正番'] == u, '着順'] = r
                                else: st.error(f"取得失敗: {msg}")
                            
                            # データ表示・編集
                            ed = st.data_editor(
                                race_full[['正番','馬名','着順','単ｵｯｽﾞ','属性','エネルギー状態','総合スコア']], 
                                hide_index=True, use_container_width=True, key=f"ed_{place}_{r_num}"
                            )
                            # 編集結果を収集
                            updated = race_full.copy()
                            for _, row in ed.iterrows():
                                updated.loc[updated['正番'] == row['正番'], '着順'] = row['着順']
                            edited_dfs.append(updated)
            
            # 全体確定ボタン
            if st.form_submit_button("🔄 入力を確定して全体を更新"):
                st.session_state['analyzed_df'] = apply_ranking_logic(pd.concat(edited_dfs, ignore_index=True))
                st.rerun()

        # 推奨馬表示
        st.divider(); st.subheader("👑 特選推奨馬")
        future_df = full_df[(full_df['着順'].isna()) & (full_df['総合スコア'] >= 10)]
        if not future_df.empty:
            for pl in sorted(future_df['場名'].unique()):
                st.write(f"### {pl}")
                st.dataframe(future_df[future_df['場名'] == pl][['R','正番','馬名','単ｵｯｽﾞ','属性','エネルギー状態','総合スコア']], use_container_width=True, hide_index=True)
