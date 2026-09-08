"""LaTeXデリミタ正規化関数の単体テスト"""
import unittest
from gp_chat.utils import format_latex_delimiters


class TestFormatLatexDelimiters(unittest.TestCase):
    """format_latex_delimiters のテストケース"""

    def test_empty_and_none(self):
        """空文字やNoneの入力テスト"""
        self.assertEqual(format_latex_delimiters(""), "")
        self.assertEqual(format_latex_delimiters(None), "")

    def test_inline_latex(self):
        """インライン数式 \\( ... \\) の $ ... $ への変換テスト"""
        text = "アインシュタインの公式は \\( E = mc^2 \\) です。"
        expected = "アインシュタインの公式は $E = mc^2$ です。"
        self.assertEqual(format_latex_delimiters(text), expected)

    def test_display_latex(self):
        """別行立て数式 \\[ ... \\] の $$ ... $$ への変換テスト"""
        text = "オイラーの等式:\n\\[ e^{i\\pi} + 1 = 0 \\]\n美しい公式です。"
        result = format_latex_delimiters(text)
        self.assertIn("$$\ne^{i\\pi} + 1 = 0\n$$", result)
        self.assertNotIn("\\[", result)
        self.assertNotIn("\\]", result)

    def test_code_block_protection(self):
        """コードブロック内の記号が保護され、変換されないことのテスト"""
        code = (
            "```python\n"
            "# This is a comment with \\( not math \\)\n"
            "print('Hello \\[world\\]')\n"
            "```"
        )
        text = f"以下はコードです:\n{code}\nそして数式は \\( x = 1 \\) です。"
        result = format_latex_delimiters(text)
        self.assertIn(code, result)
        self.assertIn("$x = 1$", result)

    def test_inline_code_protection(self):
        """インラインコード内の記号が保護されるテスト"""
        text = "コマンド `cat \\(file\\)` を実行。数式は \\( y = 2 \\) です。"
        result = format_latex_delimiters(text)
        self.assertIn("`cat \\(file\\)`", result)
        self.assertIn("$y = 2$", result)

    def test_inline_double_dollar_correction(self):
        """行中に埋め込まれた $$...$$ が独立行に整形されるテスト"""
        text = "数式 $$f(x) = x^2$$ を考えます。"
        result = format_latex_delimiters(text)
        self.assertIn("$$\nf(x) = x^2\n$$", result)

    def test_existing_valid_latex_preserved(self):
        """すでに正しい $...$ や独立行 $$...$$ が破壊されないテスト"""
        text = "インライン $a + b = c$ と\n\n$$\nx^2 + y^2 = r^2\n$$\nです。"
        result = format_latex_delimiters(text)
        self.assertIn("$a + b = c$", result)
        self.assertIn("$$\nx^2 + y^2 = r^2\n$$", result)

    def test_multiline_display_latex(self):
        """複数行にまたがる \\[ ... \\] の変換テスト"""
        text = "\\[\n\\begin{aligned}\nf(x) &= x^2 + 2x + 1 \\\\\n&= (x + 1)^2\n\\end{aligned}\n\\]"
        result = format_latex_delimiters(text)
        self.assertIn("$$\n\\begin{aligned}", result)
        self.assertIn("\\end{aligned}\n$$", result)

    def test_multiple_inline_formulas(self):
        """1行に複数のインライン数式がある場合のテスト"""
        text = "\\( a \\) と \\( b \\) を足すと \\( c \\) になる。"
        expected = "$a$ と $b$ を足すと $c$ になる。"
        self.assertEqual(format_latex_delimiters(text), expected)

    def test_currency_symbol_not_broken(self):
        """通貨記号 $100 や $50 が誤変換されないテスト"""
        text = "価格は $100 または $50 です。"
        result = format_latex_delimiters(text)
        self.assertEqual(result, text)


if __name__ == "__main__":
    unittest.main()
