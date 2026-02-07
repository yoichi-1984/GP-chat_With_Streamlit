# execution_engine.py:
import pandas as pd
import numpy as np # Explicit import required
import matplotlib
# GUIバックエンドを使わない設定（サーバーでのクラッシュ防止）
# 必ず pyplot をインポートする前に設定する必要があります
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
import io
import contextlib
import traceback
import sys
import platform
import os

def setup_japanese_font():
    """
    OSに応じた日本語フォントを設定し、グラフの文字化けを防ぎます。
    実行のたびに呼び出されますが、負荷は軽微です。
    """
    os_name = platform.system()
    font_name = "sans-serif" # デフォルト

    if os_name == "Windows":
        # Windowsの代表的なフォント
        # 優先順位: Meiryo -> Yu Gothic -> MS Gothic
        candidates = ["Meiryo", "Yu Gothic", "MS Gothic"]
        for f in candidates:
            try:
                matplotlib.font_manager.findfont(f, fallback_to_default=False)
                font_name = f
                break
            except:
                continue
    elif os_name == "Darwin": # macOS
        font_name = "Hiragino Sans"
    else: # Linux / Streamlit Cloud / Docker
        # Linux環境 (IPAフォントやNoto Sans CJKなど)
        candidates = ["Noto Sans CJK JP", "IPAexGothic", "IPAGothic", "VL Gothic"]
        for f in candidates:
             try:
                matplotlib.font_manager.findfont(f, fallback_to_default=False)
                font_name = f
                break
             except:
                continue

    matplotlib.rcParams['font.family'] = font_name
    # マイナス記号が文字化けするのを防ぐ
    matplotlib.rcParams['axes.unicode_minus'] = False

def execute_user_code(code: str, file_paths: dict, canvases: list):
    """
    AIが生成したPythonコードを実行し、標準出力とグラフ画像(io.BytesIO)を返します。
    
    Args:
        code (str): 実行するPythonコード
        file_paths (dict): {"filename.csv": "/path/to/real/file.csv"} 形式の辞書
        canvases (list): エディタ上のテキストデータのリスト
        
    Returns:
        tuple: (stdout_str, figures_list)
            - stdout_str: print出力やエラーメッセージを含む文字列
            - figures_list: 生成されたグラフの画像データ(io.BytesIO)のリスト
    """
    # フォント設定
    setup_japanese_font()
    
    # 実行結果格納用バッファ
    buffer = io.StringIO()
    figures = []
    
    # 実行スコープ（Local Scope）の準備
    local_scope = {
        "pd": pd,
        "plt": plt,
        "io": io,
        "np": np,
    }
    
    # ファイルパス変数の注入
    local_scope['files'] = file_paths
    
    # Canvasデータの注入
    for i, content in enumerate(canvases):
        local_scope[f"canvas_{i+1}"] = content

    try:
        # 以前の実行による図が残らないようにクリア
        plt.close('all')
        
        # 標準出力と標準エラー出力をキャプチャ
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            # コード実行
            exec(code, {}, local_scope)
            
            # 生成された図の確認と回収
            fig_nums = plt.get_fignums()
            if fig_nums:
                print(f"[System] {len(fig_nums)} charts generated.") # 生成数をログに出す
                for i in fig_nums:
                    fig = plt.figure(i)
                    img_buf = io.BytesIO()
                    # bbox_inches='tight' で余白を自動調整
                    fig.savefig(img_buf, format='png', bbox_inches='tight')
                    img_buf.seek(0)
                    figures.append(img_buf)
            else:
                print("[System] No charts generated (plt.show() or plot commands not detected).")

    except Exception:
        # エラーが発生した場合はスタックトレースをバッファに書き込む
        traceback.print_exc(file=buffer)
    
    return buffer.getvalue(), figures
