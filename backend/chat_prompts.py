"""聊天用文案与 system prompt 常量。

全部是常量(或只返回常量的函数),改动可被 review 逐行看清;
拆出来是为了让 chat.py 只剩流程。
"""
from __future__ import annotations

WELCOME_ZH = (
    "**欢迎回到 MATHGUIDE · 学习辅助**\n\n"
    "我是 MG,你的高等数学学习与研究助手。直接提问即可,或用下方指令:"
    "学习分析 / 章节知识导航 / 问题记录 / 公式查询手册 / 待办清单。\n\n"
    "问题的**板块我会自动识别**,先给严谨的推导与结论;需要通俗解释时,"
    "点回答下的「换个直观说法」即可;"
    "中文、英文提问都可以。\n\n"
    "(Welcome to MATHGUIDE · Learn. You can also ask in English, e.g. \"explain limits with intuition\".)"
)

WELCOME_RESEARCH_ZH = (
    "**欢迎回到 MATHGUIDE · 科学研究**\n\n"
    "我是 MG,你的科研工作区助手。本区会话、研究档案与检索范围与学习辅助完全独立,"
    "可直接提问,或用下方指令:研究档案 / 搜索范围 / 待办清单。\n\n"
    "提出研究型问题时,我会按选定的**搜索范围**跨文献库检索,并给出带编号引用的综合解答;"
    "中文、英文提问都可以。\n\n"
    "(Welcome to MATHGUIDE · Research. This workspace is isolated from Learn; ask in English if you prefer.)"
)

FALLBACK_ZH = (
    "这个问题我按通用方法论给你搭分析框架。\n\n"
    "**通用三步走(专业表述):** ① 明确对象与条件,把问题转化为标准型(极限式、方程、积分、模型);"
    "② 选择对应工具求解;③ **回代验算**——MG 的「自我验证工作流」会在解答发布前进行一致性检查与符号复验,"
    "低置信度时会主动标注「该解答需进行人工处理」。\n\n"
    "把题目原文(或拍照上传)发给我,我会按上面的框架给出带完整过程的解答。"
)

FALLBACK_EN = (
    "Here is a general framework I can apply to this problem.\n\n"
    "**Approach (3 steps):** 1) Identify the objects and conditions, and rewrite the problem into a canonical form "
    "(a limit, an equation, an integral, or a model); 2) apply the matching tool; 3) **verify by substitution**. "
    "MG's self-verification workflow runs consistency checks and symbolic re-validation before publishing an answer, "
    "flagging low-confidence ones as \"manual review required\".\n\n"
    "Paste the full problem (or upload a photo) and I'll work through it step by step."
)

ATTACH_IMAGE_ZH = (
    "已收到你上传的图片 **{name}**。\n\n"
    "当前演示环境会保留图片于会话记录中;接入视觉模型后,MG 将直接识图作答:"
    "拍照的手写题目 → OCR + 版面解析 → 按板块与难度路由。\n\n"
    "**现在你可以:** ① 把题目文字打出来,我照常解答;② 先手动归入对应板块(题目类型判断已生效)。"
)

ATTACH_FILE_ZH = (
    "已收到文件 **{name}**(大小 {size} KB)。\n\n"
    "文本/PDF 教材已读取正文,可执行「章节知识导航」一键划分章节;"
)

ATTACH_IMAGE_EN = (
    "Image **{name}** received and kept in this conversation.\n\n"
    "The demo backend stores the preview only; once the vision model is wired up, "
    "MathGuide will read handwritten problems directly from photos. "
    "Meanwhile, type the problem text and I will solve it as usual."
)

ATTACH_FILE_EN = (
    "File **{name}** received (metadata only, {size} KB).\n\n"
    "Document parsing (PDF / lecture notes) arrives with the real file service."
)

def _nav_system():
    return (
        "你是教材章节导航助手。用户上传了一本教材,教材内容已随提问给出。"
        "请只输出该教材的章节划分列表:每一章单独一行,格式严格为 "
        "[第N章 章节名](cmd://chapter/第N章章节名),链接地址内不要含空格、括号或标点。"
        "不要展示任何章节内容,不要解释,不要输出列表以外的任何文字。"
        "若文本不像一本教材,按其内容结构推断章节并同样只输出章节列表。"
    )

def _nav_guide_system():
    return (
        "你是教材章节导航助手。教材内容与用户点击的章节已随提问给出。"
        "请针对该章节输出大概知识指引:该章学什么(核心概念)、重点与难点、"
        "与前后章节的联系、学习建议。条目式回答,与用户提问同语言,控制在 150 字以内。"
    )

_CLARIFY_ZH = "请先询问我想查哪个具体知识点"

_CLARIFY_EN = "Please first ask me which specific topic"

_INTUITION_SYSTEM_ZH = (
    "你是数学直观解释助手。用生活化类比解释给定的数学内容,要求:"
    "1. 先用一句话点明要解释的对象;"
    "2. 给出一个贴切的类比;"
    "3. 明确类比与数学对象的对应关系;"
    "4. 指出类比的局限;"
    "5. 200 字以内,不重复原解答的推导步骤,最多保留一个关键公式。"
)

_INTUITION_SYSTEM_EN = (
    "You explain math intuitively. Given a question (and an optional answer excerpt), "
    "1) name the object being explained in one sentence; 2) give one apt everyday analogy; "
    "3) map the analogy to the math explicitly; 4) state its limits; "
    "5) stay under 150 words, do not repeat the original derivation, keep at most one formula."
)
