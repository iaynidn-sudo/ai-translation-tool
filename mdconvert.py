#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Markdown 纪要导出：支持 md / html / pdf / docx
"""

import os

import markdown as md_lib

CJK_FONTS = [
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
]

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
body {{ font-family: 'SimHei', 'Microsoft YaHei', sans-serif; line-height: 1.7; color: #333; padding: 24px; }}
h1 {{ color: #1a1a1a; border-bottom: 2px solid #3498db; padding-bottom: 8px; }}
h2 {{ color: #2c3e50; border-left: 4px solid #3498db; padding-left: 8px; }}
table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
th {{ background: #f0f4f8; }}
pre {{ background: #f6f8fa; padding: 12px; border-radius: 4px; overflow-x: auto; }}
code {{ background: #f6f8fa; padding: 2px 4px; border-radius: 3px; }}
</style>
</head>
<body>
{content}
</body>
</html>
"""

EXPORT_FORMATS = ["md", "html", "pdf", "docx"]


def _to_html(markdown_text):
    html = md_lib.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "codehilite", "sane_lists", "nl2br"]
    )
    return HTML_TEMPLATE.format(content=html)


def _find_cjk_font():
    for f in CJK_FONTS:
        if os.path.exists(f):
            return f
    return None


def _to_pdf(markdown_text, path):
    from xhtml2pdf import pisa
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_path = _find_cjk_font()
    if font_path:
        base = os.path.splitext(os.path.basename(font_path))[0]
        try:
            pdfmetrics.registerFont(TTFont(base, font_path))
            pdfmetrics.registerFontFamily(base, normal=base, bold=base, italic=base, boldItalic=base)
        except Exception:
            pass

    html = _to_html(markdown_text)
    with open(path, "wb") as f:
        status = pisa.CreatePDF(html, dest=f)
    if status.err:
        raise RuntimeError("PDF 生成失败")
    return path


def _to_docx(markdown_text, path):
    from docx import Document
    from htmldocx import HtmlToDocx

    html = md_lib.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "sane_lists", "nl2br"]
    )
    doc = Document()
    converter = HtmlToDocx()
    converter.add_html_to_document(html, doc)
    doc.save(path)
    return path


def convert_markdown(markdown_text, fmt, output_path):
    """将 Markdown 文本转换为指定格式并保存。

    参数:
        markdown_text: Markdown 文本内容
        fmt: 目标格式，md / html / pdf / docx
        output_path: 输出文件路径（不含扩展名）
    返回完整保存路径。
    """
    fmt = fmt.lower().lstrip(".")
    if fmt == "md":
        path = output_path + ".md"
        with open(path, "w", encoding="utf-8") as f:
            f.write(markdown_text)
    elif fmt == "html":
        path = output_path + ".html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(_to_html(markdown_text))
    elif fmt == "pdf":
        path = output_path + ".pdf"
        _to_pdf(markdown_text, path)
    elif fmt == "docx":
        path = output_path + ".docx"
        _to_docx(markdown_text, path)
    else:
        raise ValueError(f"不支持的格式: {fmt}")
    return path
