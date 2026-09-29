"""字体本地化：前端构建不得依赖 fonts.googleapis.com。

为什么值得有：`next/font/google` 会让 `next build` 在**构建期**去下载字体
（Noto Sans SC 是 CJK 字体，按 unicode-range 切成上百个子集文件）。网络受限时构建会
以 `An error occurred in next/font` 失败，而且报错完全看不出是网络问题——排查方向会
被带偏。改成系统字体栈后构建离线可完成。

断言分两半（缺一不可）：

  · `app/layout.tsx` 不得再 import `next/font`（否则构建期又会联网）；
  · `app/globals.css` 必须定义 `--font-inter` / `--font-noto-sans-sc`（否则去掉
    next/font 后这两个变量没人赋值，`--font-sans` 里的 var() 解析为空，字体
    回退链断掉——界面会悄悄变成浏览器默认字体）。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_LAYOUT = _ROOT / 'web' / 'app' / 'layout.tsx'
_CSS = _ROOT / 'web' / 'app' / 'globals.css'


def _strip_comments(src: str) -> str:
    """剥掉注释：源码里正解释着「为什么不要 next/font」，搜全文会误判。"""
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    src = re.sub(r'\{/\*.*?\*/\}', '', src, flags=re.S)
    return re.sub(r'//[^\n]*', '', src)


class LocalFontStackTest(unittest.TestCase):
    def test_layout_does_not_depend_on_google_fonts(self) -> None:
        code = _strip_comments(_LAYOUT.read_text(encoding='utf-8'))
        self.assertNotIn(
            'next/font',
            code,
            'app/layout.tsx 又 import 了 next/font：构建期会去 fonts.googleapis.com '
            '下载字体（Noto Sans SC 是 CJK，上百个子集），受限网络下 next build 会以 '
            '`An error occurred in next/font` 失败，且报错看不出是网络问题。',
        )

    def test_font_variables_are_defined_in_css(self) -> None:
        css = _strip_comments(_CSS.read_text(encoding='utf-8'))
        for var in ('--font-inter:', '--font-noto-sans-sc:'):
            self.assertIn(
                var, css,
                f'globals.css 没有定义 {var.rstrip(":")}：去掉 next/font 后没人给它赋值，'
                '`--font-sans` 里的 var() 解析为空，字体回退链会断掉。',
            )
        self.assertIn(
            'var(--font-inter)', css,
            '--font-sans 没有引用 --font-inter：字体栈没接上。',
        )


if __name__ == '__main__':
    unittest.main()
