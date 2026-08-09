"""CJK 文本处理公共工具。

解决“可搜索 PDF”文本层常见的跨行断字问题：PDF 排版把一个中文词
拆在两行（如“两\\n\\n个”），逐行提取后成为两个片段，导致下游
句子切分、挖空、证据片段丢失行首/行尾字。
"""
from __future__ import annotations

import re

_CJK = "\\u4e00-\\u9fff"
# 行尾汉字与行首汉字之间出现任意数量换行 → 断字（段间分隔因行首
# 为缩进空格或标点而不会被匹配）
_REJOIN = re.compile(rf"(?<=[{_CJK}])\n+(?=[{_CJK}])")


def is_cjk_char(char: str) -> bool:
    return bool(char and "\u4e00" <= char <= "\u9fff")


def rejoin_cjk_line_breaks(text: str) -> str:
    """合并 CJK 跨行断字：“两\\n\\n个” → “两个”。

    段间分隔不会误合并：段首行通常带缩进空格（“基本法\\n\\n  本质”），
    或行尾是标点（“。\\n\\n【本节”），均不满足“汉字紧邻汉字”。
    """
    return _REJOIN.sub("", text)
