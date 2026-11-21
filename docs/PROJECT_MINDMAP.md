# MathGuide 项目功能关系图

> 精简版：只保留板块之间、核心功能之间和主要数据流。

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'fontSize': '22px', 'fontFamily': 'Microsoft YaHei, Arial'}}}%%
flowchart TB
  USER([用户]) --> HOME[首页 / 工作区选择]

  subgraph LEARN[学习辅助板块]
    CHAT[智能聊天]
    LEARN_TOOLS[章节导航 · 公式语音 · 归纳本 · 待办 · 图解]
    LEARN_MAP[知识图谱]
    LEARN_LOOP[诊断 · 掌握度 · 学习推荐]
    CHAT --> LEARN_TOOLS
    CHAT --> LEARN_MAP
    LEARN_MAP --> LEARN_LOOP
    LEARN_LOOP --> CHAT
  end

  subgraph RESEARCH[科学研究板块]
    SEARCH[文献检索与论文阅读]
    TABLE[数据表 · 公式 · 统计 · 回归]
    REPORT[图表与研究报告]
    SEARCH --> TABLE
    TABLE --> REPORT
  end

  HOME --> CHAT
  HOME --> SEARCH

  subgraph PLATFORM[共享平台能力]
    ROUTE[问题路由]
    RAG[RAG 检索]
    KNOWLEDGE[知识库 / 论文语料]
    MODEL[LLM / Embedding]
    EXPORT[统一文档导出]
    ROUTE --> RAG
    RAG --> KNOWLEDGE
    RAG --> MODEL
  end

  CHAT --> ROUTE
  SEARCH --> ROUTE
  CHAT --> EXPORT
  TABLE --> EXPORT
  REPORT --> EXPORT

  subgraph DATA[数据与安全]
    AUTH[认证 · 限流 · 安全校验]
    DB[(SQLite)]
    LOCAL[(localStorage)]
  end

  AUTH --> DB
  CHAT -. 会话/归纳/待办 .-> LOCAL
  SEARCH -. 研究历史/设置 .-> LOCAL
  AUTH -. 保护所有接口 .-> ROUTE
  AUTH -. 保护所有接口 .-> EXPORT

  classDef main fill:#172554,stroke:#60a5fa,color:#ffffff,font-size:24px
  classDef learn fill:#064e3b,stroke:#34d399,color:#ffffff,font-size:22px
  classDef research fill:#3f1d5b,stroke:#c084fc,color:#ffffff,font-size:22px
  classDef platform fill:#451a03,stroke:#fbbf24,color:#ffffff,font-size:22px
  classDef data fill:#374151,stroke:#d1d5db,color:#ffffff,font-size:22px

  class USER,HOME main
  class CHAT,LEARN_TOOLS,LEARN_MAP,LEARN_LOOP learn
  class SEARCH,TABLE,REPORT research
  class ROUTE,RAG,KNOWLEDGE,MODEL,EXPORT platform
  class AUTH,DB,LOCAL data
```

## 三条核心关系

1. **学习闭环**：智能聊天 → 知识图谱 → 诊断与推荐 → 回到针对性学习。
2. **研究闭环**：文献检索 → 论文阅读 → 数据表分析 → 图表与研究报告。
3. **共享能力**：学习和研究都经过问题路由、RAG、模型调用、统一导出，并受到统一认证与安全校验保护。

## 数据归属

- `知识库 / 论文语料`：供聊天、文献阅读和研究问答检索。
- `SQLite`：保存账号、令牌、用量和诊断记录。
- `localStorage`：保存浏览器侧会话、归纳本、待办、研究历史和设置。
