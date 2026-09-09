import os
import sys

# =========================================================
# 【最優先】プロキシ設定の環境依存処理
# ※他のサードパーティ製ライブラリを import する前に実行します
# =========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(BASE_DIR, "credentials.json")

# ローカル環境（credentials.json が存在する）場合のみプロキシを設定
if os.path.exists(CREDENTIALS_PATH):
    PROXY_URL = "http://nw-proxy.fihes.local:8080"
    os.environ["http_proxy"] = PROXY_URL
    os.environ["https_proxy"] = PROXY_URL
    os.environ["HTTP_PROXY"] = PROXY_URL
    os.environ["HTTPS_PROXY"] = PROXY_URL
else:
    # Streamlit Cloud（credentials.json が存在しない）では環境変数を完全に削除
    for key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"]:
        os.environ.pop(key, None)

# =========================================================
# 以下、通常のライブラリの import 処理
# =========================================================
import io
import datetime
import re
import pandas as pd
import plotly.express as px
import streamlit as st
import httplib2
import google_auth_httplib2
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# --- 設定項目 ---
# Google DriveのフォルダID 
FOLDER_ID = '1-S6ZZdfM0_7H7y_5DlDg0yMtYgUJ_fYj' 
DEVICES = ["26150486", "26150487", "26150488"]

# --- プロキシ設定（ローカル環境のみ適用） ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(BASE_DIR, "credentials.json")

# ローカル環境（credentials.json が存在する）場合のみプロキシを設定
if os.path.exists(CREDENTIALS_PATH):
    #PROXY_URL ="http://nw-proxy.fihes.pref.fukuoka.jp:8080"
    PROXY_URL = "http://nw-proxy.fihes.local:8080"
    os.environ["http_proxy"] = PROXY_URL
    os.environ["https_proxy"] = PROXY_URL
else:
    # クラウド環境ではプロキシ環境変数を消去（直接通信）
    os.environ.pop("http_proxy", None)
    os.environ.pop("https_proxy", None)

# --- Google Drive API 接続準備 ---
#@st.cache_resource
#def get_drive_service():
#    if not os.path.exists(CREDENTIALS_PATH):
#        st.error(f"認証ファイルが見つかりません: {CREDENTIALS_PATH}")
#        st.stop()
#
#    creds = service_account.Credentials.from_service_account_file(
#        CREDENTIALS_PATH,
#        scopes=['https://www.googleapis.com/auth/drive.readonly']
#    )
#
#    http_client = httplib2.Http()
#    authorized_http = google_auth_httplib2.AuthorizedHttp(creds, http=http_client)
#    return build('drive', 'v3', http=authorized_http)
# --- Google Drive API 接続準備 ---
@st.cache_resource
def get_drive_service():
    # 1. ローカル環境（credentials.json が存在する場合）
    if os.path.exists(CREDENTIALS_PATH):
        creds = service_account.Credentials.from_service_account_file(
            CREDENTIALS_PATH,
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
    # 2. クラウド環境（st.secrets に認証情報が設定されている場合）
    elif "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
    else:
        st.error("認証情報 (credentials.json または st.secrets) が見つかりません。")
        st.stop()

    http_client = httplib2.Http()
    authorized_http = google_auth_httplib2.AuthorizedHttp(creds, http=http_client)
    return build('drive', 'v3', http=authorized_http)

# --- CSVファイルの取得関数 ---
def load_data_from_drive():
    debug_logs = []

    service = get_drive_service()

    query = f"'{FOLDER_ID}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])

    debug_logs.append(f"📁 フォルダ内で検出された総ファイル数: {len(files)} 件")

    now = datetime.datetime.now()
    #-mod-#one_week_ago = now - datetime.timedelta(days=7)
    one_week_ago = now - datetime.timedelta(days=14)
    debug_logs.append(f"🕒 現在日時 (now): {now.strftime('%Y-%m-%d %H:%M:%S')}")
    debug_logs.append(f"📅 抽出対象期間の基準 (one_week_ago): {one_week_ago.strftime('%Y-%m-%d %H:%M:%S')}")

    all_dfs = []

    for dev in DEVICES:
        dev_files = []
        for f in files:
            m = re.match(r"WBGT_" + dev + r"_(\d{6})\.[cC][sS][vV]", f['name'])
            if m:
                yymmdd_str = m.group(1)
                try:
                    file_date = datetime.datetime.strptime("20" + yymmdd_str, "%Y%m%d")
                    dev_files.append({
                        'id': f['id'],
                        'name': f['name'],
                        'date': file_date
                    })
                except ValueError as ve:
                    debug_logs.append(f"⚠️ 日付パース失敗 ({f['name']}): {ve}")

        debug_logs.append(f"🔍 機器 {dev} にマッチしたファイル数: {len(dev_files)} 件")

        # 新しい日付順にソート
        dev_files.sort(key=lambda x: x['date'], reverse=True)

        for file_info in dev_files:
            debug_logs.append(f"  └ 処理中: {file_info['name']} (判定日付: {file_info['date'].strftime('%Y-%m-%d')})")

            # ファイル日付の判定（1週間前より古ければ中断）
            if file_info['date'] < (one_week_ago - datetime.timedelta(days=1)):
                #-mod-#debug_logs.append(f"    └ 判定日付が 1週間前より古いためスキップ (以降の過去ファイルもスキップ)")
                debug_logs.append(f"    └ 判定日付が 2週間前より古いためスキップ (以降の過去ファイルもスキップ)")
                break

            request = service.files().get_media(fileId=file_info['id'])
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

            fh.seek(0)
            try:
                df = pd.read_csv(fh)
                df.columns = df.columns.str.strip()

                if 'DATE' in df.columns:
                    sample_date_raw = df['DATE'].dropna().iloc[0] if not df['DATE'].dropna().empty else "なし"
                    debug_logs.append(f"    └ DATE列のサンプル (変換前): {sample_date_raw}")

                    # YY/MM/DD HH:MM 形式（例: 26/08/05 09:24）を明確に指定してパース
                    df['DATE'] = pd.to_datetime(df['DATE'], format='%y/%m/%d %H:%M', errors='coerce')

                    # 秒が含まれる形式などが混在している場合のフォールバック処理
                    if df['DATE'].isna().sum() > 0:
                        df['DATE'] = df['DATE'].fillna(
                            pd.to_datetime(df['DATE'], format='mixed', yearfirst=True, errors='coerce')
                        )

                    if isinstance(df['DATE'].dtype, pd.DatetimeTZDtype):
                        df['DATE'] = df['DATE'].dt.tz_localize(None)

                    valid_dates = df['DATE'].dropna()
                    if not valid_dates.empty:
                        debug_logs.append(f"    └ DATEパース完了: 最小 {valid_dates.min()} 〜 最大 {valid_dates.max()}")
                    else:
                        debug_logs.append(f"    ⚠️ DATEパース結果がすべて NaT (無効) になりました")

                    df = df.dropna(subset=['DATE'])
                    df['Device'] = dev
                    all_dfs.append(df)
                else:
                    debug_logs.append(f"    ⚠️ 'DATE' 列が存在しません")

            except Exception as e:
                debug_logs.append(f"    ❌ ファイル読み込みエラー ({file_info['name']}): {e}")

    if not all_dfs:
        debug_logs.append("❌ 有効なデータフレームが1つも読み込めませんでした")
        return pd.DataFrame(), pd.DataFrame(), debug_logs

    combined_df = pd.concat(all_dfs, ignore_index=True)
    debug_logs.append(f"📊 結合後総データ数 (フィルタ前): {len(combined_df)} 行")

    #-mod-## 過去1週間（one_week_ago 以降）のデータに絞り込み
    #-mod-#filtered_df = combined_df[combined_df['DATE'] >= one_week_ago]
    #-mod-#debug_logs.append(f"📊 過去1週間フィルタ後データ数 ({one_week_ago} 以降): {len(filtered_df)} 行")

    # 結合済みのデータフレーム (df) に対して、現在時刻から正確に過去1週間分のデータを抽出
    now = datetime.datetime.now()
    data_threshold_time = now - datetime.timedelta(days=7)

    # 日時列が datetime 型であることを前提としてフィルタリング
    filtered_df = combined_df[combined_df['DATE'] >= data_threshold_time]
    debug_logs.append(f"📊 過去1週間フィルタ後データ数 ({one_week_ago} 以降): {len(filtered_df)} 行")

    filtered_df = filtered_df.sort_values('DATE')

    # エラー抽出
    if 'Err' in filtered_df.columns:
        err_df = filtered_df[
            filtered_df['Err'].notna() &
            (filtered_df['Err'].astype(str).str.strip() != '') &
            (filtered_df['Err'].astype(str).str.strip() != 'nan') &
            (filtered_df['Err'].astype(str).str.strip() != '0')
        ]
    else:
        err_df = pd.DataFrame()

    return filtered_df, err_df, debug_logs

# --- メイン画面描画 ---
st.set_page_config(page_title="WBGT実測データ リアルタイム監視", layout="wide")

#--add
# --- 右上のヘッダーメニュー（GitHubアイコン・鉛筆マーク等）やフッターを非表示化 ---
hide_streamlit_style = """
<style>
/* 右上のツールバー・アイコン群を非表示 */
[data-testid="stToolbar"] {visibility: hidden !important;}
div[data-testid="stToolbar"] {display: none !important;}

/* 画面右下の「Made with Streamlit」などのフッターを非表示 */
footer {visibility: hidden !important;}

/* ヘッダー自体の余白調整（必要に応じて） */
header {visibility: hidden !important;}
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

st.title("🌡️ WBGT実測データ モニタリング")

with st.spinner("Googleドライブから最新データを取得中..."):
    df, err_df, logs = load_data_from_drive()

# --- デバッグ情報の表示 (Expander) ---
with st.expander("🔍 デバッグ情報"):
    for log in logs:
        st.text(log)

if df.empty:
    st.error("過去1週間分のデータが見つかりませんでした。上記の「🔍 デバッグ情報」を展開して原因を確認してください。")
else:
    # --- エラーメッセージ表示 ---
    st.subheader("⚠️ エラーログ")
    if not err_df.empty:
        st.error(f"過去1週間で {len(err_df)} 件のエラーが検出されました。")
        st.dataframe(err_df[['DATE', 'Device', 'Err', 'WBGT', 'Ta', 'RH', 'Tg']], use_container_width=True)
    else:
        st.success("過去1週間以内に検出された機器エラーはありません。")

    # --- グラフ表示 ---
    st.subheader("📈 時系列グラフ (過去1週間)")

    variables = {
        'WBGT': 'WBGT [-]',
        'Ta': '気温 [℃]',
        'RH': '湿度 [%]',
        'Tg': '黒球温度 [℃]'
    }

    # ① 機器IDの昇順リストを作成
    sorted_devices = sorted(DEVICES)

    for var, label in variables.items():
        if var in df.columns:
            fig = px.line(
                df,
                x='DATE',
                y=var,
                color='Device',
                title=f"【 {label} 】",
                labels={'DATE': '日時', var: label, 'Device': '機器ID'},
                markers=True,
                # 凡例の並び順を昇順に指定
                category_orders={'Device': sorted_devices}
            )
            fig.update_traces(connectgaps=False)

            # ②〜④ スタイル・軸・目盛り・文字色の調整
            fig.update_layout(
                hovermode="x unified",
                height=420,
                # ③ 全テキスト文字色を黒に設定
                font=dict(color="black"),
                title=dict(font=dict(color="black", size=16)),
                legend=dict(
                    font=dict(color="black"),
                    title=dict(font=dict(color="black"))
                ),
                # 横軸（X軸）のレイアウト設定
                xaxis=dict(
                    showline=True,
                    linecolor='black',
                    linewidth=1,
                    ticks='outside',
                    tickcolor='black',
                    tickfont=dict(color='black'),
                    title=dict(font=dict(color='black')),
                    gridcolor='rgba(200, 200, 200, 0.5)',
                    # ④ 6時間間隔（6時間 × 3600秒 × 1000ミリ秒）
                    #dtick=6 * 3600 * 1000,
                    dtick=12 * 3600 * 1000,
                    # ④ フォーマットを「08/03」のMM/DD形式指定（改行して時刻を表示）
                    tickformat="%m/%d\n%H:%M",
                    #tickformat="%m/%d%H:%M",
                    hoverformat="%Y/%m/%d %H:%M"
                ),
                # 縦軸（Y軸）のレイアウト設定
                yaxis=dict(
                    showline=True,
                    linecolor='black',
                    linewidth=1,
                    ticks='outside',
                    tickcolor='black',
                    tickfont=dict(color='black'),
                    title=dict(font=dict(color='black')),
                    gridcolor='rgba(200, 200, 200, 0.5)'
                )
            )

            st.plotly_chart(fig, use_container_width=True)
