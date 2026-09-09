/**
 * 国际化(简体中文 / English)。
 * 语言由 设置 → 应用 → 语言 控制,存于 settingsState.language;
 * 模板中调用 t('key'),语言切换后自动重新渲染。
 */
import { settingsState } from '@/stores/settings'
import type { AuthMethod } from '@/stores/user'

type Dict = Record<string, string>

const ZH: Dict = {
  /* 开场 */
  'intro.tagline': '高等数学学习辅助 · 科学研究',
  'intro.enter': '进入 MATHGUIDE',

  /* 登录 */
  'login.slogan': '登录方式即实名认证方式 · 信息仅用于账号管理',
  'login.tabPass': '密码登录',
  'login.tabCode': '验证码登录',
  'login.tabRegister': '创建账户',
  'login.phone': '手机号',
  'login.password': '密码(至少 6 位)',
  'login.setPassword': '设置密码(至少 6 位)',
  'login.confirm': '确认密码',
  'login.code': '验证码',
  'login.getCode': '获取验证码',
  'login.resend': 's 后重发',
  'login.submitLogin': '登录',
  'login.submitAuto': '登录 / 自动注册',
  'login.submitRegister': '创建账户',
  'login.third': '其他登录方式',
  'login.wechat': '微信登录',
  'login.qq': 'QQ 登录',
  'login.agreement': '登录即代表同意《用户协议》与《隐私政策》(演示环境)',
  'login.authTitleWx': '正在唤起微信授权…',
  'login.authTitleQq': '正在唤起 QQ 授权…',
  'login.authDesc': '请在设备上确认授权,账号信息将与 MathGuide 完成交接',
  'login.toastPhone': '请输入正确的手机号',
  'login.toastPw': '密码至少 6 位',
  'login.toastCodeErr': '验证码错误(演示验证码:123456)',
  'login.toastCodeSent': '验证码已发送(模拟):123456',
  'login.toastNotFound': '该手机号尚未注册,请先创建账户',
  'login.toastWrong': '密码错误,请重试',
  'login.toastMismatch': '两次输入的密码不一致',
  'login.toastExists': '该手机号已注册,请直接登录',
  'login.toastCreated': '账户创建成功,已自动登录',
  'login.welcome': '欢迎,',
  'login.toastNet': '无法连接服务器,请确认后端服务已启动(端口 8000)',
  'login.toastExpired': '登录状态已失效,请重新登录',

  /* 首页 */
  'home.heroSub': '基于大模型的高等数学学习辅助与科学研究智能助手',
  'home.learnTitle': '学习辅助',
  'home.learnDesc': '一体化智能答疑对话,概念动画、例题精讲等五大指令随问随用。',
  'home.open': '已开放',
  'home.researchTitle': '科学研究',
  'home.researchDesc': '公式推导辅助 · 符号计算验算 · 论文公式解析,面向科研场景的深度推理。',
  'home.researchPending': '第二阶段 · 敬请期待',

  /* 学习辅助 */
  'learn.title': '学习辅助 · 智能答疑',
  'learn.newChat': '＋ 新建对话',
  'learn.archive': '▤ 问题归纳',
  'learn.context': '上下文',
  'learn.newSession': '新会话 · 待分类',
  'learn.placeholder': '输入你的高数问题,Enter 发送(Shift+Enter 换行);或点击下方指令快速执行',
  'learn.listening': '正在聆听,请说话…',
  'learn.send': '发送',
  'learn.generating': '生成中',
  'learn.stop': '停止生成',
  'learn.stoppedNote': '⏹ 已停止生成',
  'learn.cmdLabel': '指令 / COMMANDS',
  'learn.voiceLabel': 'MG 语音回复',
  'learn.devBadge': '待开发',
  'learn.thinking': 'MG 思考中',
  'learn.errStream': '⚠ 连接失败:未能从后端获得回复,请确认后端服务已启动后重新提问。',
  'learn.attach': '上传附件',
  'learn.attachAlbum': '从相册选择照片',
  'learn.attachCamera': '拍照(调用设备相机)',
  'learn.attachFile': '上传文件(本地 / 微信 / QQ / WPS)',
  'learn.attachPaste': '粘贴导入(剪贴板)',
  'learn.dropHint': '松开鼠标,导入文件(图片 / 文档)',
  'learn.toastPasteEmpty': '剪贴板为空或读取失败,请先复制内容再试',
  'learn.toastDropTooMany': '一次最多导入 3 个文件,本次拖入已取消',
  'learn.toastVoiceDenied': '请在设置 → 隐私与安全中开启语音识别授权',
  'learn.toastNoSR': '当前浏览器不支持语音识别,请使用 Chrome / Edge',
  'learn.toastMicDenied': '麦克风权限被拒绝:请点击地址栏的权限图标,允许本网站使用麦克风后重试',
  'learn.toastNoVoice': '未识别到语音,请重试',
  'learn.toastVoiceDev': '模型语音回复开发中,当前仍使用文本回复',
  'learn.toastVoiceNetwork': '语音服务连接失败,建议在电脑 Chrome / Edge 中演示',
  'learn.toastTrashed': '记录已移入回收站',
  'learn.toastBusy': '当前问题回复中,请稍候再提问',
  'learn.deleteConfirm': '删除这条问答记录?30 天内可在 设置 → 回收站 中恢复。',
  'learn.voiceInput': '语音输入',
  'learn.stopListening': '点击停止聆听',
  'learn.voiceHint': '大模型语音交流(待开发):开启后模型边交流边文本输出',
  'learn.toastStorage': '本地存储空间不足,图片较多的历史记录可能无法完整保存',

  /* 归纳面板 */
  'panel.title': '问题归纳 · QUESTION ARCHIVE',
  'panel.total': '已归纳 {n} 个问题',
  'panel.hint': '点击问题打开原会话 · ✕ 删除该条记录',
  'panel.jump': '打开该问答所在的历史会话',
  'panel.del': '删除这条记录',

  /* 设置 */
  'settings.title': '设置',
  'settings.sectionAccount': '账号',
  'settings.sectionApp': '应用',
  'settings.sectionAbout': '关于',
  'settings.account': '账号管理',
  'settings.privacy': '隐私与安全',
  'settings.trash': '回收站',
  'settings.language': '语言',
  'settings.appearance': '外观',
  'settings.dark': '深色',
  'settings.light': '浅色',
  'settings.feedback': '功能与改进',
  'settings.about': '关于 MG',
  'settings.logout': '退出登录',
  'settings.logoutConfirm': '确定退出登录吗?',
  'settings.toastLight': '已切换浅色主题',
  'settings.toastDark': '已切换深色主题',
  'settings.toastLoggedOut': '已退出登录',
  'settings.items': '{n} 条',

  /* 账号管理 */
  'acc.title': '账号管理',
  'acc.changeAvatar': '更换头像',
  'acc.collapse': '收起',
  'acc.fromAlbum': '从相册选择',
  'acc.nickname': '昵称',
  'acc.save': '保存',
  'acc.info': '账号信息',
  'acc.phone': '手机号',
  'acc.unbound': '未绑定',
  'acc.method': '登录方式',
  'acc.realname': '实名认证',
  'acc.status': '认证状态',
  'acc.name': '姓名',
  'acc.id': '身份证号',
  'acc.submit': '提交认证',
  'acc.namePh': '姓名(选填补全)',
  'acc.idPh': '身份证号(选填补全)',
  'acc.nickPh': '输入昵称',
  'acc.note': '登录方式已提供实名基础认证;此处补全信息用于账号找回等场景。',
  'acc.toastNickEmpty': '昵称不能为空',
  'acc.toastNickSaved': '昵称已保存',
  'acc.toastAvatar': '头像已更新',
  'acc.toastAvatarFail': '图片读取失败,请换一张试试',
  'acc.toastAlbumDenied': '请先在「隐私与安全」中授权访问相册',
  'acc.toastNameEmpty': '请输入姓名',
  'acc.toastIdErr': '请输入正确的 18 位身份证号',
  'acc.toastRealSaved': '实名信息已保存(演示环境仅本地保存,正式环境将由权威渠道核验)',

  /* 隐私与安全 */
  'privacy.title': '隐私与安全',
  'privacy.perms': '授权管理',
  'privacy.data': '数据管理',
  'privacy.album': '允许访问相册',
  'privacy.albumDesc': '用于设置头像时选择本地图片,仅在你有操作时读取',
  'privacy.voice': '允许语音识别',
  'privacy.voiceDesc': '聊天页麦克风按钮使用浏览器本地语音识别(不经过服务器)',
  'privacy.personal': '个性化学习数据',
  'privacy.personalDesc': '问题归纳在本地进行,用于个性化学习',
  'privacy.clear': '清除本地聊天记录',
  'privacy.clearDesc': '删除问题归纳中的全部会话数据(不影响账号信息)',
  'privacy.clearBtn': '清除',
  'privacy.clearConfirm': '确定清除本地聊天记录与归纳数据吗?此操作不可恢复。',
  'privacy.toastCleared': '本地聊天数据已清除',
  'privacy.toastOn': '已开启',
  'privacy.toastOff': '已关闭',
  'privacy.foot': '当前为演示环境:所有账号与设置数据仅保存在本机浏览器中,不会上传到任何服务器。',

  /* 关于 */
  'about.title': '功能与改进 · 关于 MG',
  'about.feedbackTitle': '功能与改进',
  'about.feedbackPh': '告诉我们你想要的功能、遇到的问题或改进建议…',
  'about.submit': '提交反馈',
  'about.aboutTitle': '关于 MG',
  'about.desc': 'MathGuide 是基于大模型的高等数学学习辅助与科学研究智能助手:学习辅助提供从基础入门到竞赛拔尖的智能答疑、概念动画与问题归纳;科学研究板块(第二阶段)将接入更强的推理模型与计算验证闭环。',
  'about.toastEmpty': '请先填写你的反馈内容',
  'about.toastThanks': '感谢你的反馈!功能改进会优先参考(演示环境)',

  /* 回收站 */
  'trash.title': '回收站',
  'trash.note': '删除的问答记录保留 {n} 天,超期自动清除;恢复后将重新分配到原板块。',
  'trash.empty': '回收站是空的',
  'trash.deletedOn': '删除于 {d} · 剩余 {n} 天',
  'trash.restore': '恢复',
  'trash.purge': '彻底删除',
  'trash.purgeConfirm': '彻底删除这条记录?此操作不可恢复。',
  'trash.toastRestored': '已恢复,并重新分配到原板块',
  'trash.toastPurged': '已彻底删除',
  'trash.emptyQuestion': '(空问题)',

  /* 通用 */
  'common.back': '← 返回',
  'common.backHome': '← 返回首页',
  'common.modelPending': 'MODEL · MG-CORE(待接入)',
  'common.planned': '规划中',
  'common.tbd': '待开发',
  'common.settings': '设置',
  'common.mgLearn': 'MG · LEARN',

  /* 科学研究占位 */
  'research.title': '科学研究',
  'research.icon': '∇',
  'research.desc': '面向科研场景的深度推理与计算验证闭环',
  'research.status': '界面开发中 · 阶段四',
  'research.f1': '公式推导辅助',
  'research.f2': '符号计算验算',
  'research.f3': '论文公式解析',
  'research.f4': '文献检索辅助',
  'research.f5': '科研助手对话',
  'research.f6': '计算后端对接',

  /* 页面标题 */
  'title.intro': 'MathGuide',
  'title.login': '登录 · MathGuide',
  'title.home': 'MathGuide · 首页',
  'title.learn': 'MathGuide · 学习辅助',
  'title.research': 'MathGuide · 科学研究',
  'title.settings': 'MathGuide · 设置',
  'title.settings-account': 'MathGuide · 账号管理',
  'title.settings-privacy': 'MathGuide · 隐私与安全',
  'title.settings-about': 'MathGuide · 关于',
  'title.settings-trash': 'MathGuide · 回收站',
}

const EN: Dict = {
  'intro.tagline': 'Higher Mathematics Learning & Research',
  'intro.enter': 'ENTER MATHGUIDE',

  'login.slogan': 'Sign-in method = identity verification · Info is used only for account management',
  'login.tabPass': 'Password',
  'login.tabCode': 'SMS Code',
  'login.tabRegister': 'Create Account',
  'login.phone': 'Phone number',
  'login.password': 'Password (min 6 chars)',
  'login.setPassword': 'Set password (min 6 chars)',
  'login.confirm': 'Confirm password',
  'login.code': 'SMS code',
  'login.getCode': 'Get Code',
  'login.resend': 's',
  'login.submitLogin': 'Log In',
  'login.submitAuto': 'Log In / Auto-signup',
  'login.submitRegister': 'Create Account',
  'login.third': 'Other sign-in methods',
  'login.wechat': 'WeChat Login',
  'login.qq': 'QQ Login',
  'login.agreement': 'By logging in you agree to the Terms of Service and Privacy Policy (demo)',
  'login.authTitleWx': 'Launching WeChat authorization…',
  'login.authTitleQq': 'Launching QQ authorization…',
  'login.authDesc': 'Confirm the authorization on your device to link your account with MathGuide',
  'login.toastPhone': 'Enter a valid phone number',
  'login.toastPw': 'Password must be at least 6 characters',
  'login.toastCodeErr': 'Wrong code (demo code: 123456)',
  'login.toastCodeSent': 'Code sent (demo): 123456',
  'login.toastNotFound': 'This number is not registered. Create an account first',
  'login.toastWrong': 'Wrong password, try again',
  'login.toastMismatch': 'Passwords do not match',
  'login.toastExists': 'This number is already registered, log in directly',
  'login.toastCreated': 'Account created, logged in automatically',
  'login.welcome': 'Welcome, ',
  'login.toastNet': 'Cannot reach the server. Make sure the backend is running (port 8000)',
  'login.toastExpired': 'Your session has expired — please sign in again',

  'home.heroSub': 'AI-powered higher mathematics learning & research assistant',
  'home.learnTitle': 'Learn',
  'home.learnDesc': 'One-stop intelligent Q&A: concept animations, worked examples and 4 more commands on demand.',
  'home.open': 'Open',
  'home.researchTitle': 'Research',
  'home.researchDesc': 'Formula derivation · symbolic verification · paper formula parsing, deep reasoning for research.',
  'home.researchPending': 'Phase 2 · Coming soon',

  'learn.title': 'Learn · Intelligent Q&A',
  'learn.newChat': '+ New Chat',
  'learn.archive': '▤ Archive',
  'learn.context': 'context',
  'learn.newSession': 'New chat · unclassified',
  'learn.placeholder': 'Ask a higher math question, Enter to send (Shift+Enter for newline), or tap a command below',
  'learn.listening': 'Listening, speak now…',
  'learn.send': 'Send',
  'learn.generating': 'Generating',
  'learn.stop': 'Stop',
  'learn.stoppedNote': '⏹ Stopped',
  'learn.cmdLabel': 'COMMANDS',
  'learn.voiceLabel': 'MG voice reply',
  'learn.devBadge': 'TBD',
  'learn.thinking': 'MG thinking',
  'learn.errStream': '⚠ Connection failed: no reply from the backend. Make sure the backend service is running, then ask again.',
  'learn.attach': 'Attach',
  'learn.attachAlbum': 'Photo from album',
  'learn.attachCamera': 'Take a photo (device camera)',
  'learn.attachFile': 'Upload file (local / WeChat / QQ / WPS)',
  'learn.attachPaste': 'Paste import (clipboard)',
  'learn.dropHint': 'Release to import files (images / documents)',
  'learn.toastPasteEmpty': 'Clipboard is empty or unreadable — copy something first',
  'learn.toastDropTooMany': 'Up to 3 files per drop — this drop was cancelled',
  'learn.toastVoiceDenied': 'Enable voice recognition in Settings → Privacy & Security first',
  'learn.toastNoSR': 'Speech recognition is not supported in this browser, use Chrome / Edge',
  'learn.toastMicDenied': 'Microphone permission denied: click the permission icon in the address bar and allow mic access',
  'learn.toastNoVoice': 'No speech detected, try again',
  'learn.toastVoiceDev': 'MG voice reply is under development, text replies are still used',
  'learn.toastVoiceNetwork': 'Speech service unreachable. Use desktop Chrome / Edge for the demo',
  'learn.toastTrashed': 'Moved to trash',
  'learn.toastBusy': 'A reply is in progress, please wait before asking again',
  'learn.deleteConfirm': 'Delete this Q&A record? It can be restored in Settings → Trash within 30 days.',
  'learn.voiceInput': 'Voice input',
  'learn.stopListening': 'Stop listening',
  'learn.voiceHint': 'MG voice replies (in development): text replies are still used',
  'learn.toastStorage': 'Local storage is full; history with many images may not be saved completely',

  'panel.title': 'QUESTION ARCHIVE',
  'panel.total': '{n} questions archived',
  'panel.hint': 'Click a question to open its chat · ✕ deletes the record',
  'panel.jump': 'Open the original chat of this Q&A',
  'panel.del': 'Delete this record',

  'settings.title': 'Settings',
  'settings.sectionAccount': 'Account',
  'settings.sectionApp': 'App',
  'settings.sectionAbout': 'About',
  'settings.account': 'Account Management',
  'settings.privacy': 'Privacy & Security',
  'settings.trash': 'Trash',
  'settings.language': 'Language',
  'settings.appearance': 'Appearance',
  'settings.dark': 'Dark',
  'settings.light': 'Light',
  'settings.feedback': 'Feedback & Improvements',
  'settings.about': 'About MG',
  'settings.logout': 'Log Out',
  'settings.logoutConfirm': 'Log out?',
  'settings.toastLight': 'Light theme enabled',
  'settings.toastDark': 'Dark theme enabled',
  'settings.toastLoggedOut': 'Logged out',
  'settings.items': '{n}',

  'acc.title': 'Account Management',
  'acc.changeAvatar': 'Change avatar',
  'acc.collapse': 'Collapse',
  'acc.fromAlbum': 'From album',
  'acc.nickname': 'Nickname',
  'acc.save': 'Save',
  'acc.info': 'Account info',
  'acc.phone': 'Phone',
  'acc.unbound': 'Not bound',
  'acc.method': 'Sign-in method',
  'acc.realname': 'Identity verification',
  'acc.status': 'Verification status',
  'acc.name': 'Name',
  'acc.id': 'ID number',
  'acc.submit': 'Submit',
  'acc.namePh': 'Name (optional)',
  'acc.idPh': 'ID number (optional)',
  'acc.nickPh': 'Enter nickname',
  'acc.note': 'Your sign-in method already provides basic identity verification; the info here helps with account recovery.',
  'acc.toastNickEmpty': 'Nickname cannot be empty',
  'acc.toastNickSaved': 'Nickname saved',
  'acc.toastAvatar': 'Avatar updated',
  'acc.toastAvatarFail': 'Failed to load the image, try another one',
  'acc.toastAlbumDenied': 'Grant album access in Privacy & Security first',
  'acc.toastNameEmpty': 'Enter your name',
  'acc.toastIdErr': 'Enter a valid 18-digit ID number',
  'acc.toastRealSaved': 'Saved (demo stores locally only; official verification comes with the backend)',

  'privacy.title': 'Privacy & Security',
  'privacy.perms': 'Permissions',
  'privacy.data': 'Data management',
  'privacy.album': 'Allow album access',
  'privacy.albumDesc': 'Used only when you pick an avatar image from this device',
  'privacy.voice': 'Allow voice recognition',
  'privacy.voiceDesc': 'The mic button uses on-device browser speech recognition (no server involved)',
  'privacy.personal': 'Personalized learning data',
  'privacy.personalDesc': 'Question archiving and difficulty levels run locally for personalized learning',
  'privacy.clear': 'Clear local chat history',
  'privacy.clearDesc': 'Removes all archived conversations (account info is kept)',
  'privacy.clearBtn': 'Clear',
  'privacy.clearConfirm': 'Clear all local chat history and archives? This cannot be undone.',
  'privacy.toastCleared': 'Local chat history cleared',
  'privacy.toastOn': 'Enabled',
  'privacy.toastOff': 'Disabled',
  'privacy.foot': 'Demo environment: all account and settings data is stored only in this browser and never uploaded.',

  'about.title': 'Feedback & About MG',
  'about.feedbackTitle': 'Feedback & Improvements',
  'about.feedbackPh': 'Tell us what features you want, problems you found, or suggestions…',
  'about.submit': 'Submit',
  'about.aboutTitle': 'About MG',
  'about.desc': 'MathGuide is an LLM-powered higher mathematics learning & research assistant: Learn offers intelligent Q&A from beginner to competition level, concept animations and a question archive; the Research module (phase 2) will connect stronger reasoning models with a computation-verification loop.',
  'about.toastEmpty': 'Write your feedback first',
  'about.toastThanks': 'Thanks for your feedback! (demo environment)',

  'trash.title': 'Trash',
  'trash.note': 'Deleted records are kept for {n} days, then removed automatically. Restoring puts them back into their original category.',
  'trash.empty': 'Trash is empty',
  'trash.deletedOn': 'Deleted on {d} · {n} days left',
  'trash.restore': 'Restore',
  'trash.purge': 'Delete forever',
  'trash.purgeConfirm': 'Delete this record forever? This cannot be undone.',
  'trash.toastRestored': 'Restored to its original category',
  'trash.toastPurged': 'Deleted forever',
  'trash.emptyQuestion': '(empty question)',

  'common.back': '← Back',
  'common.backHome': '← Home',
  'common.modelPending': 'MODEL · MG-CORE (PENDING)',
  'common.planned': 'Planned',
  'common.tbd': 'TBD',
  'common.settings': 'Settings',
  'common.mgLearn': 'MG · LEARN',

  'research.title': 'Research',
  'research.icon': '∇',
  'research.desc': 'Deep reasoning and computation-verification loops for research',
  'research.status': 'UI under development · Phase 4',
  'research.f1': 'Formula derivation',
  'research.f2': 'Symbolic verification',
  'research.f3': 'Paper formula parsing',
  'research.f4': 'Literature search',
  'research.f5': 'Research assistant chat',
  'research.f6': 'Compute backend',

  'title.intro': 'MathGuide',
  'title.login': 'Login · MathGuide',
  'title.home': 'MathGuide · Home',
  'title.learn': 'MathGuide · Learn',
  'title.research': 'MathGuide · Research',
  'title.settings': 'MathGuide · Settings',
  'title.settings-account': 'MathGuide · Account',
  'title.settings-privacy': 'MathGuide · Privacy',
  'title.settings-about': 'MathGuide · About',
  'title.settings-trash': 'MathGuide · Trash',
}

export function t(key: string, params?: Record<string, string | number>): string {
  const raw = settingsState.language === 'en' ? EN[key] : ZH[key]
  let s = raw ?? ZH[key] ?? key
  if (params) {
    for (const [k, v] of Object.entries(params)) s = s.replace(`{${k}}`, String(v))
  }
  return s
}

/* ---------- 动态内容:板块 / 指令 / 登录方式 ---------- */

const CAT_NAMES: Record<string, [string, string]> = {
  analysis: ['数学分析', 'Mathematical Analysis'],
  algebra: ['高等代数', 'Advanced Algebra'],
  geometry: ['空间解析几何', 'Analytic Geometry'],
  ode: ['微分方程', 'Differential Equations'],
  probability: ['概率论与数理统计', 'Probability & Mathematical Statistics'],
  complex: ['复变函数', 'Complex Analysis'],
  topology: ['拓扑学', 'Topology'],
  other: ['未归类', 'Uncategorized'],
}

export function catName(key: string): string {
  const pair = CAT_NAMES[key]
  return pair ? (settingsState.language === 'en' ? pair[1] : pair[0]) : key
}

const CMD_NAMES: Record<string, [string, string]> = {
  概念动画演示: ['概念动画演示', 'Concept Animation'],
  例题精讲: ['例题精讲', 'Worked Examples'],
  章节知识导航: ['章节知识导航', 'Chapter Navigator'],
  错题归纳: ['错题归纳', 'Mistake Review'],
  公式查询手册: ['公式查询手册', 'Formula Handbook'],
}

const CMD_HINTS: Record<string, [string, string]> = {
  概念动画演示: ['输入想看的数学概念,演示其几何意义', 'Enter a concept to see its geometric meaning animated'],
  例题精讲: ['输入题目或知识点,给出例题与讲解', 'Enter a topic to get worked examples'],
  章节知识导航: ['上传或粘贴教材后,一键划分章节;点击章节查看知识指引', 'Upload or paste a textbook to get its chapter list; tap a chapter for guidance'],
  错题归纳: ['粘贴错题,归纳错误原因与易错点', 'Paste a wrong answer to analyze its causes'],
  公式查询手册: ['查询常用公式与定理', 'Look up common formulas and theorems'],
}

const CMD_DEFAULTS: Record<string, [string, string]> = {
  概念动画演示: ['函数极限的动画演示', 'Animation of the limit of a function'],
  例题精讲: ['一道经典极限例题', 'A classic limit example'],
  章节知识导航: ['高等数学章节结构', 'Chapter structure of higher mathematics'],
  错题归纳: ['错题归纳模板', 'Mistake review template'],
  公式查询手册: ['常用公式速查', 'Common formulas at a glance'],
}

function pick(pair: [string, string] | undefined, key: string): string {
  return pair ? (settingsState.language === 'en' ? pair[1] : pair[0]) : key
}

export function cmdName(key: string): string {
  return pick(CMD_NAMES[key], key)
}

export function cmdHint(key: string): string {
  return pick(CMD_HINTS[key], '')
}

export function cmdDefault(key: string): string {
  return pick(CMD_DEFAULTS[key], key)
}

const AUTH_NAMES: Record<AuthMethod, [string, string]> = {
  'phone-pass': ['手机号 + 密码', 'Phone + Password'],
  'phone-code': ['手机号 + 验证码', 'Phone + SMS Code'],
  wechat: ['微信登录', 'WeChat'],
  qq: ['QQ 登录', 'QQ'],
}

const REALNAME_TEXTS: Record<AuthMethod, [string, string]> = {
  'phone-pass': ['已通过手机号实名认证', 'Verified via phone number'],
  'phone-code': ['已通过手机号实名认证', 'Verified via phone number'],
  wechat: ['已通过微信实名认证(演示环境为模拟授权)', 'Verified via WeChat (simulated in demo)'],
  qq: ['已通过 QQ 实名认证(演示环境为模拟授权)', 'Verified via QQ (simulated in demo)'],
}

export function authName(method: AuthMethod): string {
  return pick(AUTH_NAMES[method], method)
}

export function realnameText(method: AuthMethod): string {
  return pick(REALNAME_TEXTS[method], '')
}
