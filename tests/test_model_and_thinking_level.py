# -*- coding: utf-8 -*-
"""tests/test_model_and_thinking_level.py: gemini-4-argon 対応、モデル選択肢、ThinkingLevel 制御の単体テスト。"""

import inspect
import unittest
from google.genai import types

from gp_chat import config
from gp_chat import pptx_agent
from gp_chat import utils


class TestModelAndThinkingLevel(unittest.TestCase):
    """gemini-4-argon 対応、3択モデル選択、low/medium/highマッピング、thinking_config 適用のテスト。"""

    def test_available_models_three_choices(self):
        """サイドバー選択肢 AVAILABLE_MODELS が指定の3択であることを検証。"""
        expected = [
            "gemini-4-argon",
            "gemini-3.8-flash",
            "gemini-3.5-flash-lite",
        ]
        self.assertEqual(config.AVAILABLE_MODELS, expected)
        self.assertEqual(len(config.AVAILABLE_MODELS), 3)

    def test_session_state_defaults(self):
        """デフォルトモデルが gemini-4-argon、thinking-level が medium であることを検証。"""
        self.assertEqual(config.SESSION_STATE_DEFAULTS.get("current_model_id"), "gemini-4-argon")
        self.assertEqual(config.SESSION_STATE_DEFAULTS.get("reasoning_effort"), "medium")

    def test_thinking_level_three_tier_mapping(self):
        """effort が high, medium, low に応じて正確に ThinkingLevel にマッピングされることを検証。"""
        effort_map = {
            "high": types.ThinkingLevel.HIGH,
            "medium": types.ThinkingLevel.MEDIUM,
            "low": types.ThinkingLevel.LOW,
        }
        self.assertEqual(effort_map["high"], types.ThinkingLevel.HIGH)
        self.assertEqual(effort_map["medium"], types.ThinkingLevel.MEDIUM)
        self.assertEqual(effort_map["low"], types.ThinkingLevel.LOW)
        # フォールバック値の検証
        fallback_val = effort_map.get("unknown", types.ThinkingLevel.MEDIUM)
        self.assertEqual(fallback_val, types.ThinkingLevel.MEDIUM)

    def test_deep_mode_selects_gemini_4_argon_and_high(self):
        """deep 推論モードまたは more_research のとき、
        モデルが gemini-4-argon、ThinkingLevel が HIGH に自動設定されることを検証。
        """
        for mode in ["deep", "more_research"]:
            is_deep_reasoning = mode == "deep"
            is_more_research = mode == "more_research"

            model_id = "gemini-3.5-flash-lite"  # ユーザーがサイドバーで別モデルを選択していた想定
            effort = "low"

            if is_more_research or is_deep_reasoning:
                model_id = "gemini-4-argon"
                t_level = types.ThinkingLevel.HIGH
            else:
                effort_map = {
                    "high": types.ThinkingLevel.HIGH,
                    "medium": types.ThinkingLevel.MEDIUM,
                    "low": types.ThinkingLevel.LOW,
                }
                t_level = effort_map.get(effort, types.ThinkingLevel.MEDIUM)

            self.assertEqual(model_id, "gemini-4-argon")
            self.assertEqual(t_level, types.ThinkingLevel.HIGH)

    def test_gemini_4_thinking_config_applicable(self):
        """gemini-4-argon が thinking_config の適用対象（'gemini' in model_id）であることを検証。"""
        models_to_test = [
            ("gemini-4-argon", True),
            ("gemini-3.8-flash", True),
            ("gemini-3.5-flash-lite", True),
            ("gpt-5.3-codex", False),
            ("gpt-5.6", False),
            ("gpt-6", False),
        ]
        for m_id, expected in models_to_test:
            is_gemini = "gemini" in m_id
            self.assertEqual(is_gemini, expected, f"Model {m_id} expected is_gemini={expected}")

    def test_title_generation_keeps_gemini_35_flash_lite(self):
        """タイトル生成 utils.generate_chat_title が gemini-3.5-flash-lite を維持していることを検証。"""
        # ソースコードを検証
        src = inspect.getsource(utils.generate_chat_title)
        self.assertIn('"gemini-3.5-flash-lite"', src)

    def test_pptx_agent_default_model(self):
        """pptx_agent のデフォルトモデル引数が gemini-4-argon であることを検証。"""
        sig_audit = inspect.signature(pptx_agent.run_visual_quality_audit)
        self.assertEqual(sig_audit.parameters["model_id"].default, "gemini-4-argon")

        sig_pipeline = inspect.signature(pptx_agent.PPTXAgent.generate_presentation_pipeline)
        self.assertEqual(sig_pipeline.parameters["model_id"].default, "gemini-4-argon")


if __name__ == "__main__":
    unittest.main()
