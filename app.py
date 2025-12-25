import streamlit as st
import yfinance as yf
from prophet import Prophet
import plotly.graph_objects as go
import pandas as pd
from supabase import create_client, Client
import hashlib
from datetime import datetime
from deep_translator import GoogleTranslator

# --- Supabase 接続設定 ---
url: str = st.secrets["SUPABASE_URL"]
key: str = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(url, key)

def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def get_company_name(symbol):
    """銘柄コードから企業名を取得する"""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        return info.get('longName') or info.get('shortName') or symbol
    except:
        return symbol

def search_tickers(query):
    """企業名やキーワードから銘柄候補を取得する"""
    try:
        # キーワードを英語に翻訳
        english_query = translate_to_english(query)
        
        # 翻訳後のキーワードで検索
        search = yf.Search(english_query, max_results=5)
        results = []
        for quote in search.quotes:
            symbol = quote.get('symbol')
            name = quote.get('longname') or quote.get('shortname') or symbol
            exch = quote.get('exchDisp') or ""
            results.append({"label": f"{symbol}: {name} ({exch})", "symbol": symbol})
        return results
    except Exception as e:
        return []
    
def translate_to_english(text):
    """日本語を英語に翻訳する（英数字のみの場合はそのまま）"""
    try:
        # 入力が日本語（ひらがな、カタカナ、漢字）を含むかチェック
        if any(ord(char) > 255 for char in text):
            translated = GoogleTranslator(source='auto', target='en').translate(text)
            return translated
        return text
    except:
        return text
    
# --- データベース操作関数 ---
def create_user(username, password):
    data = {"username": username, "password": make_hashes(password)}
    supabase.table("users").insert(data).execute()

def login_user(username, password):
    response = supabase.table("users").select("*")\
        .eq("username", username)\
        .eq("password", make_hashes(password))\
        .execute()
    return response.data

def add_history(username, symbol):
    data = {"username": username, "symbol": symbol}
    supabase.table("history").insert(data).execute()

def get_history(username):
    response = supabase.table("history").select("symbol")\
        .eq("username", username)\
        .order("timestamp", desc=True)\
        .limit(5)\
        .execute()
    # 修正ポイント：文字列のリストを正しく返す
    return list(dict.fromkeys([item['symbol'] for item in response.data]))

def add_favorite(username, symbol):
    try:
        data = {"username": username, "symbol": symbol}
        supabase.table("favorites").insert(data).execute()
        return True
    except:
        return False

def remove_favorite(username, symbol):
    supabase.table("favorites").delete().eq("username", username).eq("symbol", symbol).execute()

def get_favorites(username):
    response = supabase.table("favorites").select("symbol").eq("username", username).execute()
    return [item['symbol'] for item in response.data]
    
def delete_account(username):
    """ユーザーに関連するすべてのデータを削除する"""
    try:
        # 1. 履歴を削除
        supabase.table("history").delete().eq("username", username).execute()
        # 2. お気に入りを削除
        supabase.table("favorites").delete().eq("username", username).execute()
        # 3. ユーザー本体を削除
        supabase.table("users").delete().eq("username", username).execute()
        return True
    except Exception as e:
        st.error(f"削除エラー: {e}")
        return False

# --- アプリのメイン制御 ---
def main():
    st.set_page_config(page_title="株価予測アプリ", layout="wide")

    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        st.session_state['username'] = ""

    if not st.session_state['logged_in']:
        menu = ["ログイン", "新規登録"]
        choice = st.sidebar.selectbox("メニュー", menu)
        if choice == "ログイン":
            st.subheader("ログイン画面")
            user = st.text_input("ユーザー名")
            raw_password = st.text_input("パスワード", type='password')
            if st.button("ログイン"):
                result = login_user(user, raw_password)
                if result:
                    st.session_state['logged_in'] = True
                    st.session_state['username'] = user
                    st.rerun()
                else:
                    st.error("ユーザー名かパスワードが違います")
        elif choice == "新規登録":
            st.subheader("アカウント作成")
            new_user = st.text_input("ユーザー名")
            new_password = st.text_input("パスワード", type='password')
            if st.button("登録"):
                try:
                    create_user(new_user, new_password)
                    st.success("アカウントを作成しました。ログインしてください。")
                except:
                    st.error("そのユーザー名は既に使用されています")
    else:
        st.sidebar.success(f"ログイン中: {st.session_state['username']}")
        
        # ログアウトボタン
        if st.sidebar.button("ログアウト"):
            st.session_state['logged_in'] = False
            st.rerun()

        # アカウント削除設定（サイドバーの最下部など）
        with st.sidebar.expander("⚙️ アカウント設定"):
            st.warning("一度削除したデータは復元できません。")
            confirm = st.checkbox("アカウントを完全に削除する")
            if st.button("実行する", type="primary", disabled=not confirm):
                if delete_account(st.session_state['username']):
                    st.success("アカウントを削除しました")
                    st.session_state['logged_in'] = False
                    st.session_state['username'] = ""
                    st.rerun()

        # --- サイドバー：お気に入り銘柄 ---
        st.sidebar.markdown("---")
        st.sidebar.subheader("⭐ お気に入り銘柄")
        favs = get_favorites(st.session_state['username'])
        if favs:
            for f in favs:
                if st.sidebar.button(f"📊 {f}", key=f"side_fav_{f}"):
                    st.session_state['search_symbol'] = f
                    # 検索窓をリセット
                    if 'ticker_search_input' in st.session_state:
                        st.session_state['ticker_search_input'] = ""
                    st.rerun()

        # --- サイドバー：検索履歴 ---
        st.sidebar.markdown("---")
        st.sidebar.subheader("🕒 最近の検索")
        history = get_history(st.session_state['username'])
        if history:
            for h in history:
                if st.sidebar.button(f"🔎 {h}", key=f"side_hist_{h}"):
                    st.session_state['search_symbol'] = h
                    # 検索窓をリセット
                    if 'ticker_search_input' in st.session_state:
                        st.session_state['ticker_search_input'] = ""
                    st.rerun()

        show_stock_predict_ui()

def show_stock_predict_ui():
    # セッション状態の初期化
    if 'search_symbol' not in st.session_state:
        st.session_state['search_symbol'] = 'AAPL'

    st.title("📈 株価推移予測ダッシュボード")
    favs = get_favorites(st.session_state['username'])
   
    st.subheader("🔍 銘柄を検索・選択")
    # キーワード入力
    search_query = st.text_input("企業名を入力（例: トヨタ, Apple）", key="ticker_search_input")
    
    selected_symbol = None
    if search_query:
        search_results = search_tickers(search_query)
        if search_results:
            options = [item['label'] for item in search_results]
            selected_option = st.selectbox("検索結果から選択してください", options)
            selected_symbol = selected_option.split(":")[0]
        else:
            st.warning("候補が見つかりませんでした。")

    # 【修正点】検索結果があればそれを、なければセッションの銘柄（履歴など）を優先
    current_symbol = selected_symbol if selected_symbol else st.session_state['search_symbol']
    
    col_input, col_period = st.columns([2, 1])
    with col_input:
        symbol = st.text_input("銘柄コード（確定）", value=current_symbol).upper()        
    with col_period:
        period = st.selectbox("学習期間（年）", [1, 2, 3, 5], index=1)

    # ボタン配置
    btn_col1, btn_col2 = st.columns([1, 2])
    with btn_col1:
        execute_btn = st.button("🚀 予測を実行")
    with btn_col2:
        if symbol in favs:
            if st.button(f"✖ {symbol} をお気に入りから外す"):
                remove_favorite(st.session_state['username'], symbol)
                st.rerun()
        else:
            if st.button(f"⭐ {symbol} をお気に入りに追加"):
                if add_favorite(st.session_state['username'], symbol):
                    st.rerun()

    # 予測処理
    if execute_btn or st.session_state.get('last_searched') == symbol:
        st.session_state['search_symbol'] = symbol
        st.session_state['last_searched'] = symbol
        add_history(st.session_state['username'], symbol)
        
        try:
            # 予測実行の直前で企業名を確実に取得
            with st.spinner('最新データを取得中...'):
                data = yf.download(symbol, period=f"{period}y")
            
            if data.empty:
                st.error("データが見つかりませんでした。")
            else:
                # 取得した企業名を表示
                company_name = get_company_name(symbol) # ここで最新の銘柄名を取得
                st.subheader(f"🏢 企業名: {company_name}")
                
                # データ整形
                df_train = data.reset_index()
                if isinstance(df_train.columns, pd.MultiIndex):
                    df_train.columns = df_train.columns.get_level_values(0)
                
                df_train = df_train[['Date', 'Close']]
                df_train.columns = ['ds', 'y']
                df_train['ds'] = df_train['ds'].dt.tz_localize(None)

                # Prophetモデル
                with st.spinner('解析中...'):
                    # changepoint_prior_scaleを元の適切な値（0.05程度）に戻すことをお勧めします
                    model = Prophet(daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=True, changepoint_prior_scale=0.05)
                    model.fit(df_train)
                    future = model.make_future_dataframe(periods=10)
                    future['day_of_week'] = future['ds'].dt.dayofweek
                    future = future[future['day_of_week'] < 5] # 土日除外
                    forecast = model.predict(future)

                # Plotly可視化
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df_train['ds'], y=df_train['y'], name="実績値", line=dict(color='#1f77b4')))
                fig.add_trace(go.Scatter(x=forecast['ds'], y=forecast['yhat'], name="予測値", line=dict(color='#e377c2', dash='dash')))
                fig.add_trace(go.Scatter(
                    x=pd.concat([forecast['ds'], forecast['ds'][::-1]]),
                    y=pd.concat([forecast['yhat_upper'], forecast['yhat_lower'][::-1]]),
                    fill='toself', fillcolor='rgba(227,119,194,0.1)', line=dict(color='rgba(255,255,255,0)'),
                    name="予測範囲"
                ))
                start_date = df_train['ds'].iloc[-60] if len(df_train) > 60 else df_train['ds'].iloc[0]
                fig.update_layout(hovermode="x unified", xaxis_range=[start_date, forecast['ds'].iloc[-1]], template="plotly_white")
                st.plotly_chart(fig, use_container_width=True)

                # 数値表示
                st.write("### 予測価格の詳細")
                res_df = forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].tail(7)
                res_df.columns = ['日付', '予測価格', '最低予想', '最高予想']
                st.dataframe(res_df.style.format({"予測価格": "{:.2f}", "最低予想": "{:.2f}", "最高予想": "{:.2f}"}))
                st.write("###### ※このチャートは推移傾向の目安のため、実際の変動とは異なる場合があります")

        except Exception as e:
            st.error(f"エラーが発生しました: {e}")

if __name__ == '__main__':
    main()