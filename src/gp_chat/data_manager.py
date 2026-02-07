# data_manager.py:
import os
import shutil
import uuid
import streamlit as st

WORKSPACE_ROOT = "temp_workspace"

class SessionDataManager:
    def __init__(self):
        """
        セッションごとに一意のワークスペースディレクトリを初期化します。
        """
        # セッションIDがなければ生成
        if "session_uuid" not in st.session_state:
            st.session_state["session_uuid"] = str(uuid.uuid4())
        
        self.session_id = st.session_state["session_uuid"]
        self.base_dir = os.path.join(WORKSPACE_ROOT, self.session_id)
        
        # ディレクトリが存在しない場合は作成
        os.makedirs(self.base_dir, exist_ok=True)

    def save_file(self, uploaded_file):
        """
        StreamlitのUploadedFileオブジェクトを受け取り、
        セッション固有の一時ディレクトリに保存します。
        
        Args:
            uploaded_file: StreamlitのUploadedFileオブジェクト
            
        Returns:
            tuple: (file_path, filename)
                - file_path: 保存されたファイルの絶対パス
                - filename: 保存されたファイル名
        """
        # 安全なファイル名を生成（ディレクトリトラバーサル防止などが必要だが、簡易的にbasenameを使用）
        filename = os.path.basename(uploaded_file.name)
        file_path = os.path.join(self.base_dir, filename)
        
        # 既存の読み取り処理に影響を与えないよう、ポインタ位置を保存
        # (VirtualUploadedFileなどの一部のオブジェクトはtell()を持たない場合があるためtry-except)
        try:
            current_pos = uploaded_file.tell()
            uploaded_file.seek(0)
        except Exception:
            current_pos = 0

        try:
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getvalue())
        except Exception as e:
            print(f"Error saving file {filename}: {e}")
            return None, None
        finally:
            # ポインタを元の位置に戻す（超重要：これが無いと既存のテキスト抽出処理が壊れる）
            try:
                uploaded_file.seek(current_pos)
            except Exception:
                pass
            
        return file_path, filename

    def get_file_path(self, filename):
        """指定されたファイル名のフルパスを返します"""
        return os.path.join(self.base_dir, filename)

    def list_files(self):
        """現在ワークスペースにあるファイル名のリストを返します"""
        if not os.path.exists(self.base_dir):
            return []
        return os.listdir(self.base_dir)

    def clear_session_files(self):
        """
        セッションディレクトリ内の全てのファイルを削除します。
        会話のリセット時などに呼び出します。
        """
        if os.path.exists(self.base_dir):
            try:
                shutil.rmtree(self.base_dir)
                os.makedirs(self.base_dir, exist_ok=True)
            except Exception as e:
                print(f"Error clearing session files: {e}")

    def cleanup(self):
        """ディレクトリそのものを削除します（セッション終了時など）"""
        if os.path.exists(self.base_dir):
            try:
                shutil.rmtree(self.base_dir)
            except Exception as e:
                print(f"Error cleaning up session dir: {e}")
                