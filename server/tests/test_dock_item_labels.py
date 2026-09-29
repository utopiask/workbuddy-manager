"""底栏图标标签「常驻显示」的不变式（源码形状）。

为什么值得有：底栏的标题原先是 **hover 才弹的 tooltip**——鼠标一移开就消失，触屏上
更是要先按住才看得到名字。改成常驻标签后，界面行为变了但**没有任何东西会因此报错**：
万一有人改回 hover 版（或把标签塞回 `AnimatePresence` 里），只有肉眼盯着底栏才发现。

这一条与 `test_dock_groups.py` 是同一类「渲染层结构」断言：行为测试（`dock-groups`）
证明不了渲染层真的按预期画了，而这几条恰恰都是「算了却没画对」型的错。

断言的目标区间限定在 `IconContainer` 内——底栏根节点本来就带 `onMouseLeave`（用于把
放大效果复位）与 `onMouseMove`（用于量分隔线矩形），搜全文会误判。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DOCK = _ROOT / 'web' / 'components' / 'ui' / 'floating-dock.tsx'


def _code(path: Path) -> str:
    """读源码并剥掉注释（实现里正解释着「不要这么写」，搜全文会误判）。"""
    src = path.read_text(encoding='utf-8')
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    src = re.sub(r'\{/\*.*?\*/\}', '', src, flags=re.S)
    return re.sub(r'//[^\n]*', '', src)


def _icon_container_block(code: str) -> str:
    start = code.index('const IconContainer = memo(')
    end = code.index('IconContainer.displayName', start)
    return code[start:end]


class DockItemLabelInvariantTest(unittest.TestCase):
    def test_icon_labels_are_not_hover_only(self) -> None:
        block = _icon_container_block(_code(_DOCK))
        self.assertTrue(block, '切不出 IconContainer 的实现（锚点变了？）——这条会空转')

        self.assertNotIn(
            'hovered', block,
            '底栏图标又用回了 hover 状态：标签会退化成「鼠标移开就消失」，'
            '触屏上更是要先按住才看得到名字。',
        )
        self.assertNotIn(
            'onMouseEnter', block,
            '底栏图标又用回了 onMouseEnter：标签不应依赖悬停——它要常驻显示。',
        )
        self.assertNotIn(
            'AnimatePresence', block,
            '底栏图标里又出现了 AnimatePresence：那是「hover 才弹、移开就消失」的'
            'tooltip 写法。标签应当直接渲染，不参与进出场动画。',
        )

    def test_icon_label_is_rendered_and_width_limited(self) -> None:
        block = _icon_container_block(_code(_DOCK))
        self.assertIn(
            '{title}', block,
            '底栏图标没有把 title 渲染成文字（只在 tooltip 里出现不算）——'
            '标签必须直接画在图标下方。',
        )
        self.assertIn(
            'truncate', block,
            '底栏标签没有截断：英文标题（Dashboard / Playground）会把底栏撑宽。',
        )


if __name__ == '__main__':
    unittest.main()
