from __future__ import annotations

from pathlib import Path

import fitz


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "artifacts" / "demo-civil-law.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    texts = [
        """第一章 善意取得\n\n善意取得制度用于保护交易安全。受让人取得动产或者不动产所有权，应当具备以下条件：处分人为无处分权人；受让人在受让该财产时为善意；以合理价格转让；依法应当登记的已经登记，不需要登记的已经交付。\n\n判断善意的时间点，应当结合登记或者交付时点。原权利人可以向无处分权人请求损害赔偿。""",
        """第二节 无权处分与无权代理\n\n无权处分处理的是处分人对标的物缺少处分权的问题。无权代理处理的是行为人缺少代理权，却以被代理人名义实施法律行为的问题。二者的权利外观、法律后果和相对人审查对象均不相同。\n\n答题时应先识别行为人以谁的名义实施行为，再判断缺少的是处分权还是代理权。""",
    ]
    font_path = next(
        (
            p
            for p in (
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "C:/Windows/Fonts/msyh.ttc",
                "/System/Library/Fonts/PingFang.ttc",
            )
            if Path(p).exists()
        ),
        None,
    )
    for text in texts:
        page = document.new_page(width=595, height=842)
        if font_path:
            page.insert_font(fontname="cjk", fontfile=font_path)
        else:
            page.insert_font(fontname="cjk", ordering=0)  # 内置 CJK 回退
        page.insert_textbox(fitz.Rect(60, 70, 535, 780), text, fontsize=13, fontname="cjk", lineheight=1.45)
    document.save(output)
    document.close()
    print(output)


if __name__ == "__main__":
    main()
