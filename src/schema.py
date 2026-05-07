from typing import Literal, TypedDict


class CleanedPage(TypedDict):
    page: int  # PDF 物理页码（1-indexed，由系统填）
    page_type: Literal[
        "cover",  # 标题页、半标题页
        "copyright",  # 版权信息页
        "dedication",  # 题献页
        "toc",  # 目录
        "preface",  # 前言、序言
        "acknowledgments",  # 致谢
        "body",  # 正文章节、引言
        "notes",  # 章节末或书末注释集合
        "bibliography",  # 参考文献
        "index",  # 索引
        "appendix",  # 附录
        "blank",  # 完全空白页
    ]
    book_page: str | None  # LLM 识别的原书页码（如 "12"、"xii"），无法识别则 None
    body_md: str
    warnings: list[str]


class CleanedBatch(TypedDict):
    batch_id: str  # 格式 "001-003"（首页-末页）
    pages: list[CleanedPage]  # 本批次各页清洗结果
