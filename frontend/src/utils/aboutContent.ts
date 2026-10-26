/**
 * 设置 → 关于 MG:版本记录、用途说明与协议文本的唯一真源。
 *
 * 版本号与发布日期在此维护;页面只负责排版,不再各自写死 "v0.1.0"。
 * 协议正文与界面分离,便于发布前统一校对与替换。
 */

export const APP_NAME = 'MathGuide'
export const APP_VERSION = 'v1.10.0-dev'
export const APP_STABLE_VERSION = 'v1.9.0'
export const APP_STABLE_DATE = '2026-10-26'
export const APP_REPO_URL = 'https://github.com/Jacob-bot-2509/MathGuide'
export const APP_ISSUES_URL = `${APP_REPO_URL}/issues`
export const APP_RELEASES_URL = `${APP_REPO_URL}/releases`

export interface Bi {
  zh: string
  en: string
}

export type BiPicker = (value: Bi) => string

export interface ReleaseEntry {
  version: string
  /** 稳定版填发布日期;开发版留空 */
  date: string
  status: 'dev' | 'latest' | 'released'
  items: Bi[]
}

export interface PurposeEntry {
  glyph: string
  title: Bi
  desc: Bi
}

export interface LegalSection {
  title: Bi
  paragraphs?: Bi[]
  bullets?: Bi[]
}

export interface LegalDoc {
  updated: string
  intro: Bi
  sections: LegalSection[]
}

export const RELEASES: ReleaseEntry[] = [
  {
    version: APP_VERSION,
    date: '',
    status: 'dev',
    items: [
      {
        zh: '待办清单:一次性 / 每天 / 每周任务,到点高亮提醒、浏览器通知、过期补看与暂停。',
        en: 'To-do list: one-off, daily and weekly tasks with timed reminders, browser notifications, expired-task review and pause.',
      },
      {
        zh: '停止生成后可点「回复」,从截断处续写,不重复已生成的内容。',
        en: 'After stopping a reply, press “Resume” to continue from the cut-off point without repeating existing text.',
      },
      {
        zh: '设置改版:拆分「功能与改进」与「关于 MG」,新增服务协议与隐私政策。',
        en: 'Settings redesign: split Feedback from About MG, and add Terms of Service and Privacy Policy.',
      },
      {
        zh: '数据与账号:导出账号、用量与本地学习数据;自助注销会级联删除账号、令牌与用量记录。',
        en: 'Data and account: export account, usage and local learning data; self-service deletion cascades through the account, tokens and usage records.',
      },
      {
        zh: '测评安全:token 只存 SHA-256、邀请码注册、API 安全响应头与 CSP 部署模板。',
        en: 'Evaluation security: SHA-256 token hashes, invite-code registration, API security headers and a CSP deployment template.',
      },
    ],
  },
  {
    version: 'v1.9.0',
    date: APP_STABLE_DATE,
    status: 'latest',
    items: [
      {
        zh: '安全加固:PBKDF2 口令、登录限流、请求体上限、导出文档 CSP nonce 与跨用户缓存隔离。',
        en: 'Security hardening: PBKDF2 passwords, login rate limits, request-body caps, export-document CSP nonces and per-user cache isolation.',
      },
      {
        zh: '可靠性:嵌入冷启动回退、按模型隔离的向量缓存、响应体积上限与可取消的检索请求。',
        en: 'Reliability: embedding cold-start fallback, model-keyed vector cache, response-size caps and cancellable research requests.',
      },
      {
        zh: '发布物:完整源码、补丁、SHA-256 校验清单与可重复运行的后端测试。',
        en: 'Release artifacts: full source, patch, SHA-256 manifest and a repeatable backend test suite.',
      },
    ],
  },
  {
    version: 'v1.8.0',
    date: '2026-09-12',
    status: 'released',
    items: [
      {
        zh: '首字超时看门狗:慢速时自动切换异平台备胎,缩短等待首个字的时间。',
        en: 'First-token watchdog: automatically switches to a backup provider on slow responses.',
      },
    ],
  },
  {
    version: 'v1.7.0',
    date: '2026-09-11',
    status: 'released',
    items: [
      {
        zh: '研究综述导出 PDF;问题记录与问题归纳面板统一为浮层形态。',
        en: 'PDF export for research summaries; unified overlay panels for question archive and notebook.',
      },
    ],
  },
]

export const PURPOSES: PurposeEntry[] = [
  {
    glyph: '∑',
    title: { zh: '学习辅助', en: 'Study assistance' },
    desc: {
      zh: '从基础入门到竞赛拔尖的智能答疑,配合概念动画、章节导航、问题归纳与待办清单。',
      en: 'Intelligent Q&A from first principles to competition level, with concept animations, chapter navigation, a question notebook and a to-do list.',
    },
  },
  {
    glyph: '∇',
    title: { zh: '科学研究', en: 'Research support' },
    desc: {
      zh: '公式推导辅助、文献检索与综述整理;第二阶段接入更强的推理模型与计算验证闭环。',
      en: 'Formula derivation support, literature search and review drafting; phase two adds stronger reasoning models and a computation-verification loop.',
    },
  },
  {
    glyph: '◷',
    title: { zh: '学习管理', en: 'Study management' },
    desc: {
      zh: '把提问、复习计划与历史归档放在同一处;学习数据默认留在本机浏览器。',
      en: 'Keep questions, review plans and past work in one place; learning data stays in your browser by default.',
    },
  },
]

export const OPEN_SOURCE: { name: string; license: string }[] = [
  { name: 'Vue 3', license: 'MIT' },
  { name: 'KaTeX', license: 'MIT' },
  { name: 'MathJax', license: 'Apache-2.0' },
  { name: 'pdf.js', license: 'Apache-2.0' },
  { name: 'Starlette', license: 'BSD-3-Clause' },
]

export const TERMS: LegalDoc = {
  updated: '2026-10-26',
  intro: {
    zh: '本协议说明 MathGuide(MG)演示环境的使用规则。使用 MG 即表示你已阅读并同意本协议;如不同意,请停止使用。',
    en: 'These terms govern use of the MathGuide (MG) demo environment. By using MG you confirm that you have read and accept them; if you do not agree, please stop using the service.',
  },
  sections: [
    {
      title: { zh: '服务内容', en: 'What MG provides' },
      paragraphs: [
        {
          zh: 'MG 是面向高等数学的学习辅助与科学研究辅助工具。学习辅助包括智能答疑、概念动画、章节知识导航、问题归纳与待办清单;科学研究模块将分阶段接入更强的推理模型与计算验证闭环。',
          en: 'MG is a study and research assistant for higher mathematics. Study assistance includes Q&A, concept animations, chapter navigation, a question notebook and a to-do list; the research module will add stronger reasoning models and a computation-verification loop in stages.',
        },
        {
          zh: '当前为演示环境,功能、模型与数据可能随时调整、暂停或重置,不承诺可用性、连续性或数据永久保存。',
          en: 'This is a demo environment. Features, models and data may change, pause or reset at any time; availability, continuity and permanent data storage are not guaranteed.',
        },
      ],
    },
    {
      title: { zh: '账号与登录', en: 'Accounts and sign-in' },
      paragraphs: [
        {
          zh: '请使用真实、可联系的手机号注册,并妥善保管密码与登录设备。登录令牌有效期为 24 小时。',
          en: 'Register with a real, reachable phone number and keep your password and devices secure. Sign-in tokens expire after 24 hours.',
        },
        {
          zh: '共用设备使用后请退出登录并清除本地数据。不得出借、转让账号或冒用他人身份。演示环境中的验证码、微信与 QQ 授权为模拟流程,不构成法定实名认证。',
          en: 'On shared devices, sign out and clear local data when finished. Do not lend, transfer or impersonate an account. In the demo environment, verification codes and WeChat/QQ authorization are simulated and are not legal identity verification.',
        },
      ],
    },
    {
      title: { zh: 'AI 生成内容', en: 'AI-generated content' },
      paragraphs: [
        {
          zh: '回答由第三方大模型生成,可能错误、过时、遗漏或引用不准确。数学结论请自行推导核验,不要仅凭回答完成作业、考试或论文。',
          en: 'Answers are generated by third-party large language models and may be wrong, outdated, incomplete or inaccurately cited. Verify mathematical results yourself; do not rely on MG alone for homework, exams or papers.',
        },
        {
          zh: 'MG 不替代教师、教材、考试规则或专业意见。引用与检索结果来自第三方平台,其内容、版权与可用性由原平台负责。',
          en: 'MG does not replace teachers, textbooks, exam rules or professional advice. Citations and search results come from third-party platforms, which are responsible for their content, copyright and availability.',
        },
      ],
    },
    {
      title: { zh: '使用规范', en: 'Acceptable use' },
      bullets: [
        {
          zh: '不得用于违法、侵权、骚扰、仇恨、欺诈或危害他人的用途。',
          en: 'Do not use MG for illegal, infringing, harassing, hateful, fraudulent or harmful purposes.',
        },
        {
          zh: '不得上传未授权的教材、试卷、个人信息或敏感数据。',
          en: 'Do not upload unauthorized textbooks, exam papers, personal information or sensitive data.',
        },
        {
          zh: '不得攻击、扫描、绕过限流、批量抓取或干扰服务。',
          en: 'Do not attack, scan, bypass rate limits, scrape at scale or disrupt the service.',
        },
        {
          zh: '不得用 MG 代替真人完成考试或冒充真人作答。',
          en: 'Do not use MG to take exams for a person or to impersonate a person in assessments.',
        },
        {
          zh: '违反上述规则时,维护者可限制或终止访问。',
          en: 'The maintainers may restrict or terminate access when these rules are violated.',
        },
      ],
    },
    {
      title: { zh: '知识产权', en: 'Intellectual property' },
      paragraphs: [
        {
          zh: 'MG 的界面、代码与标识归项目维护者所有;你上传的教材、题目与图片的权利归原权利人。',
          en: 'The MG interface, code and marks belong to the project maintainers. Rights in textbooks, problems and images you upload remain with their owners.',
        },
        {
          zh: '你对自己输入的内容负责,并同意 MG 为提供服务在必要范围内处理这些内容,包括发送给所配置的模型服务。',
          en: 'You are responsible for the content you submit and agree that MG may process it as necessary to provide the service, including sending it to the configured model providers.',
        },
      ],
    },
    {
      title: { zh: '服务变更与终止', en: 'Changes and termination' },
      paragraphs: [
        {
          zh: '演示环境可不经通知调整功能、限制用量或清空数据。',
          en: 'The demo environment may change features, limit usage or clear data without notice.',
        },
        {
          zh: '你可以随时停止使用并清除本地数据;设置 → 账号管理 提供数据导出与自助注销,注销会删除后端账号、令牌与用量记录。',
          en: 'You may stop using MG and clear local data at any time. Settings → Account Management offers data export and self-service deletion, which removes the backend account, tokens and usage records.',
        },
      ],
    },
    {
      title: { zh: '责任限制', en: 'Limitation of liability' },
      paragraphs: [
        {
          zh: '在适用法律允许的范围内,MG 按「现状」提供,不对因使用或无法使用造成的间接损失承担责任。',
          en: 'To the extent permitted by law, MG is provided “as is” and the maintainers are not liable for indirect losses arising from use or inability to use it.',
        },
        {
          zh: '第三方模型、检索平台、网络或设备导致的失败,MG 不承担超出法律强制范围的责任。',
          en: 'The maintainers are not liable beyond what the law requires for failures caused by third-party models, search platforms, networks or devices.',
        },
        {
          zh: '正式发布前,本协议将由法律顾问复核;当前文本用于说明演示环境的使用规则。',
          en: 'These terms will be reviewed by legal counsel before a production release; the current text explains the rules of the demo environment.',
        },
      ],
    },
    {
      title: { zh: '协议更新', en: 'Updates to these terms' },
      paragraphs: [
        {
          zh: '协议更新后会在本页发布,继续使用视为接受更新。',
          en: 'Updated terms are published on this page; continued use means you accept the update.',
        },
        {
          zh: '如有异议、需要删除账号数据或报告安全问题,请通过项目 Issues 联系维护者。',
          en: 'For objections, account-data deletion or security reports, contact the maintainers through the project issues page.',
        },
      ],
    },
  ],
}

export const PRIVACY: LegalDoc = {
  updated: '2026-10-26',
  intro: {
    zh: '本政策说明 MG 演示环境处理哪些数据、存放在哪里、流向何处,以及你可以如何控制。原则是少收集:问答会话默认留在你的浏览器。',
    en: 'This policy explains what data the MG demo handles, where it lives, where it goes and how you can control it. The principle is minimal collection: conversations stay in your browser by default.',
  },
  sections: [
    {
      title: { zh: '我们处理哪些数据', en: 'Data we process' },
      bullets: [
        {
          zh: '账号:手机号、口令摘要(PBKDF2-HMAC-SHA256 加盐,服务端不保存明文口令)、昵称、头像与登录方式。',
          en: 'Account: phone number, salted password digest (PBKDF2-HMAC-SHA256; the server does not store plaintext passwords), nickname, avatar and sign-in method.',
        },
        {
          zh: '学习数据:会话、问题归纳、待办与设置,保存在浏览器 localStorage。',
          en: 'Learning data: conversations, question notebook, to-dos and settings, stored in browser localStorage.',
        },
        {
          zh: '临时缓存:上传的教材与滚动摘要保存在后端进程内存,按账号与会话隔离,服务重启即清除。',
          en: 'Temporary cache: uploaded textbooks and rolling summaries live in backend process memory, isolated by account and session, and are cleared on restart.',
        },
        {
          zh: '用量记录:时间、账号标识(uid)、指令名、字符数与模型角色;不含手机号、昵称或完整问答正文。',
          en: 'Usage records: time, account identifier (uid), command name, character counts and model role; phone numbers, nicknames and full question/answer text are not included.',
        },
        {
          zh: '实名信息(如填写):姓名与脱敏证件号仅保存在本机浏览器,不上传后端。',
          en: 'Identity details (if provided): name and masked ID number stay in your browser and are not sent to the backend.',
        },
      ],
    },
    {
      title: { zh: '数据存放在哪里', en: 'Where data is stored' },
      paragraphs: [
        {
          zh: '浏览器 localStorage 保存登录令牌与档案(mg-user)、会话(mg-learn-sessions)、归纳本(mg-notebook)、设置(mg-settings)、待办(mg-todo:<accountKey>)、回收站与搜索范围。登录令牌 24 小时过期。',
          en: 'Browser localStorage holds the sign-in token and profile (mg-user), conversations (mg-learn-sessions), notebook (mg-notebook), settings (mg-settings), to-dos (mg-todo:<accountKey>), trash and search scope. Sign-in tokens expire after 24 hours.',
        },
        {
          zh: '后端 backend/data/ 保存 users.json(手机号、口令摘要、昵称、头像)、tokens.json(token 的 SHA-256 映射,24 小时)与 usage.jsonl(按 uid 的用量元数据,约保留最近 2000 条)。',
          en: 'The backend backend/data/ directory holds users.json (phone, password digest, nickname, avatar), tokens.json (SHA-256 token hashes, 24 hours) and usage.jsonl (uid-keyed usage metadata, roughly the latest 2,000 records).',
        },
        {
          zh: '演示部署使用 JSON 文件存储,未启用独立的静态加密。生产部署应补充磁盘加密、目录权限、备份访问控制与密钥管理。',
          en: 'The demo deployment uses JSON files and does not enable separate encryption at rest. Production deployments should add disk encryption, directory permissions, backup access control and key management.',
        },
      ],
    },
    {
      title: { zh: '数据流向何处', en: 'Where data goes' },
      bullets: [
        {
          zh: '提问、附件与必要的对话历史会发送给配置的大模型服务(当前为阿里云百炼与智谱开放平台);启用向量检索时,知识片段与查询也会发送给同一平台。',
          en: 'Questions, attachments and the necessary conversation history are sent to the configured model providers (currently Alibaba Cloud Bailian and Zhipu). When vector search is enabled, knowledge chunks and queries are sent to the same platform.',
        },
        {
          zh: '研究型提问的关键词会发送给所选检索平台(arXiv、zbMATH Open、Semantic Scholar、OpenAlex、StackExchange);可在「搜索范围」中关闭不想使用的平台。',
          en: 'Research query keywords are sent to the selected search platforms (arXiv, zbMATH Open, Semantic Scholar, OpenAlex, StackExchange). You can disable any platform under Search Scope.',
        },
        {
          zh: '语音识别由浏览器提供,音频不经过 MG 服务器;部分浏览器会把音频发送给其自有语音服务,具体以浏览器实现为准。',
          en: 'Speech recognition is provided by the browser and audio does not pass through the MG server; some browsers send audio to their own speech service, depending on the implementation.',
        },
        {
          zh: 'MG 不出售数据、不做广告画像,也不接入第三方统计脚本。',
          en: 'MG does not sell data, build advertising profiles or load third-party analytics scripts.',
        },
      ],
    },
    {
      title: { zh: '保存期限', en: 'Retention' },
      bullets: [
        {
          zh: '浏览器数据:保留到你清除或退出登录。退出登录会清理本机会话、归纳、回收站与语音缓存;待办按账号分桶保留,可在「隐私与安全」一键清除。',
          en: 'Browser data: kept until you clear it or sign out. Signing out clears local conversations, notebook, trash and speech cache; to-dos remain in their account bucket and can be cleared under Privacy & Security.',
        },
        {
          zh: '登录令牌:24 小时后失效。',
          en: 'Sign-in tokens: expire after 24 hours.',
        },
        {
          zh: '后端账号:保留至用户注销或维护者删除;注销会同时删除该账号的全部令牌与用量记录。游客账号超过上限时,会清理没有有效令牌的最旧记录。',
          en: 'Backend accounts: kept until the user or a maintainer deletes them; deletion removes all tokens and usage records for that account. When guest accounts exceed the limit, the oldest records without a valid token are removed.',
        },
        {
          zh: '用量记录:内存最多 2000 条,文件只保留最近记录,不存完整问答正文。',
          en: 'Usage records: at most 2,000 in memory; the file keeps only recent records and never stores full question or answer text.',
        },
        {
          zh: '会话缓存:服务重启即失效。',
          en: 'Session cache: cleared when the service restarts.',
        },
        {
          zh: '留存期限:若部署启用了自动清理,长期未登录的账号与超过期限的用量记录会被删除;管理员账号保留。',
          en: 'Retention: if automatic cleanup is enabled, accounts inactive for the configured period and expired usage records are deleted; admin accounts are retained.',
        },
      ],
    },
    {
      title: { zh: '你的控制权', en: 'Your controls' },
      bullets: [
        {
          zh: '设置 → 隐私与安全:管理相册、语音与个性化开关,清除本地学习数据。',
          en: 'Settings → Privacy & Security: manage album, voice and personalization switches, and clear local learning data.',
        },
        {
          zh: '退出登录:清除本机学习数据并吊销当前令牌。',
          en: 'Sign out: clears local learning data and revokes the current token.',
        },
        {
          zh: '搜索范围:关闭不想查询的检索平台。',
          en: 'Search Scope: disable search platforms you do not want to use.',
        },
        {
          zh: '账号导出与注销:设置 → 账号管理 可导出账号、用量与浏览器学习数据;注销会删除后端账号、全部令牌与用量记录,并清理本机学习数据。',
          en: 'Account export and deletion: Settings → Account Management exports the account, usage and browser learning data; deletion removes the backend account, all tokens and usage records, and clears local learning data.',
        },
      ],
    },
    {
      title: { zh: '安全措施', en: 'Security measures' },
      paragraphs: [
        {
          zh: '口令使用 PBKDF2-HMAC-SHA256 加盐摘要;登录令牌只保存 SHA-256 哈希;登录限流、请求体上限、HTML 转义、导出文档 CSP 与跨用户缓存隔离已启用。',
          en: 'Passwords use salted PBKDF2-HMAC-SHA256 digests; sign-in tokens are stored only as SHA-256 hashes. Login rate limits, request-body caps, HTML escaping, CSP on exported documents and per-user cache isolation are enabled.',
        },
        {
          zh: '生产部署必须使用 HTTPS、关闭 MG_DEMO_MODE、配置 CORS 白名单,并限制 backend/data/ 的访问权限。',
          en: 'Production deployments must use HTTPS, disable MG_DEMO_MODE, configure a CORS allowlist and restrict access to backend/data/.',
        },
        {
          zh: '任何系统都无法保证绝对安全。发现漏洞请私下联系维护者,不要公开利用或传播他人数据。',
          en: 'No system is perfectly secure. If you find a vulnerability, contact the maintainers privately; do not exploit it publicly or expose other people’s data.',
        },
      ],
    },
    {
      title: { zh: '未成年人', en: 'Minors' },
      paragraphs: [
        {
          zh: '未满 14 周岁的用户应在监护人同意下使用。请勿上传身份证件、住址、联系方式等敏感个人信息。',
          en: 'Users under 14 should use MG with guardian consent. Do not upload ID documents, home addresses, contact details or other sensitive personal information.',
        },
      ],
    },
    {
      title: { zh: '政策更新', en: 'Updates to this policy' },
      paragraphs: [
        {
          zh: '政策更新后会在本页发布;重大变更会在应用内提示。',
          en: 'Updated policies are published on this page; material changes will be announced in the app.',
        },
        {
          zh: '对数据处理有疑问或需要行使删除权,请通过项目 Issues 联系维护者。',
          en: 'For questions about data processing or to exercise deletion rights, contact the maintainers through the project issues page.',
        },
      ],
    },
  ],
}
