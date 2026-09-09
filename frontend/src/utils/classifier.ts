/**
 * 问题分类器:将用户问题归纳到高等数学各大板块。
 * 当前为关键词匹配(按板块优先级从上到下,先匹配者胜);
 * 后端接入后可替换为模型分类,接口保持不变。
 */

export interface CategoryInfo {
  key: string
  label: string
  color: string
}

interface Category extends CategoryInfo {
  keywords: string[]
}

/* 板块顺序 = 匹配优先级:越具体的板块越靠前,数学分析最宽泛放最后。
   关键词中英双语(统一小写,匹配时大小写不敏感),英文提问同样能自动归类 */
export const CATEGORIES: Category[] = [
  {
    key: 'topology',
    label: '拓扑学',
    color: '#4dffb8',
    keywords: [
      '拓扑', '开集', '闭集', '紧致', '紧集', '连通', '同胚', '度量空间', '邻域',
      'topology', 'open set', 'closed set', 'compact', 'connected', 'homeomorph', 'metric space', 'neighborhood',
    ],
  },
  {
    key: 'ode',
    label: '微分方程',
    color: '#ff4dd2',
    keywords: [
      '微分方程', '常微分', '偏微分', '通解', '特解', '初值', '拉普拉斯变换', '特征方程', '分离变量',
      'ode', 'differential equation', 'initial value', 'general solution', 'laplace transform', 'separable',
    ],
  },
  {
    key: 'complex',
    label: '复变函数',
    color: '#ff8fa3',
    keywords: [
      '复变', '留数', '解析函数', '柯西-黎曼', '复积分', '共形',
      'complex analysis', 'residue', 'analytic', 'cauchy-riemann', 'contour integral', 'conformal',
    ],
  },
  {
    key: 'probability',
    label: '概率论与数理统计',
    color: '#ffd166',
    keywords: [
      // 概率论
      '概率', '概率论', '随机变量', '分布', '正态', '泊松', '二项分布', '指数分布', '均匀分布', '几何分布',
      '条件概率', '全概率', '贝叶斯', '独立性', '联合分布', '边缘分布', '概率密度', '分布函数',
      '期望', '方差', '标准差', '协方差', '相关系数', '大数定律', '中心极限', '切比雪夫', '随机过程', '马尔可夫',
      // 数理统计
      '数理统计', '统计', '样本', '抽样', '统计量', '参数估计', '极大似然', '无偏', '置信区间', '区间估计',
      '假设检验', '显著性', 'p值', '卡方', 't分布', 'f分布', '方差分析', '回归', '最小二乘',
      // English
      'probability', 'probability theory', 'random variable', 'distribution', 'normal', 'poisson', 'binomial',
      'exponential distribution', 'uniform distribution', 'geometric distribution',
      'conditional probability', 'total probability', 'bayes', 'independence', 'joint distribution',
      'marginal distribution', 'probability density', 'distribution function',
      'expectation', 'variance', 'standard deviation', 'covariance', 'correlation coefficient',
      'law of large numbers', 'central limit', 'chebyshev', 'stochastic process', 'markov',
      'mathematical statistics', 'statistic', 'sample', 'sampling', 'estimator', 'maximum likelihood',
      'unbiased', 'confidence interval', 'hypothesis test', 'significance', 'p-value', 'chi-square',
      't-distribution', 'f-distribution', 'anova', 'regression', 'least squares',
    ],
  },
  {
    key: 'algebra',
    label: '高等代数',
    color: '#8b5cf6',
    keywords: [
      '矩阵', '行列式', '特征值', '特征向量', '线性', '向量空间', '线性变换', '二次型', '秩', '逆矩阵', '齐次', '对角化', '正交',
      'matrix', 'determinant', 'eigenvalue', 'eigenvector', 'linear algebra', 'linear transformation', 'vector space',
      'quadratic form', 'rank', 'inverse matrix', 'diagonaliz', 'orthogonal',
    ],
  },
  {
    key: 'geometry',
    label: '空间解析几何',
    color: '#2f7bff',
    keywords: [
      '向量', '平面', '直线方程', '曲面', '球面', '柱面', '二次曲面', '空间直角', '叉积', '点积', '方向余弦',
      'vector', 'plane', 'line equation', 'surface', 'sphere', 'cylinder', 'quadric surface', 'cross product', 'dot product', 'direction cosine',
    ],
  },
  {
    key: 'analysis',
    label: '数学分析',
    color: '#4dd6ff',
    keywords: [
      '极限', '连续', '导数', '微分', '积分', '级数', '收敛', '泰勒', '麦克劳林', '洛必达',
      '中值定理', '无穷小', '微积分', '黎曼', '傅里叶', '极值', '单调', '偏导', '梯度', '曲线积分', '曲面积分',
      'limit', 'continuity', 'derivative', 'differentiat', 'integral', 'series', 'convergen', 'taylor', 'maclaurin',
      "l'hopital", 'lhopital', 'mean value theorem', 'infinitesimal', 'calculus', 'riemann', 'fourier',
      'extremum', 'monotonic', 'partial derivative', 'gradient', 'line integral', 'surface integral',
    ],
  },
]

/** 未归类:匹配不到任何板块的问题(如闲聊、通用提问) */
export const FALLBACK_CATEGORY: CategoryInfo = { key: 'other', label: '未归类', color: '#64748b' }

/** 去掉指令前缀(如 [章节知识导航])后分类;中英文关键词统一小写后匹配 */
export function classifyQuestion(text: string): CategoryInfo {
  const content = text.replace(/^\s*\[.+?\]\s*/, '').toLowerCase()
  for (const c of CATEGORIES) {
    if (c.keywords.some((kw) => content.includes(kw))) {
      return { key: c.key, label: c.label, color: c.color }
    }
  }
  return FALLBACK_CATEGORY
}

/** 归纳面板的展示顺序(按教学板块顺序,其他垫底) */
export const DISPLAY_KEYS = ['analysis', 'algebra', 'geometry', 'ode', 'probability', 'complex', 'topology', 'other'] as const

/* ---------- 闲聊识别(与后端 chat.py _QUESTION_RE 保持同一口径) ---------- */

// 题目措辞(数学问题的形态标记,与后端 chat.py _MATH_EXTRA_WORDS 同一口径)
const MATH_STYLE_RE =
  /(?<![请要])求|证明|计算|求解|求导|求证|这道|这题|例题|题目|公式|定理|数学|怎么做|怎么算|如何求|如何证|solve|prove|compute|evaluate|show that|theorem|equation|problem|math/i

// 寒暄/感谢/告别优先于一切判断(如 How are you 里的 how)
const GREET_RE = /^(喂|你好|您好|嗨|哈喽|在吗|在不在)|(hi|hello|hey|hiya|how are you)\b/i
const THANKS_RE = /谢谢|感谢|thanks|thank you|thx/i
const BYE_RE = /再见|拜拜|bye/i

/**
 * 是否为非数学问题(寒暄 / 感谢 / 告别 / 自我介绍 / 情绪 / 一般对话):
 * 这类消息不分类、不进问题归纳、不切换或新开会话,
 * 后端会像人一样做对话式应答。只有确切数学题(板块主题词或题目措辞)才走问题流程。
 */
export function isChitchat(text: string): boolean {
  const content = text.replace(/^\s*\[.+?\]\s*/, '').trim()
  if (!content) return false
  if (GREET_RE.test(content) || THANKS_RE.test(content) || BYE_RE.test(content)) return true
  // 提到数学主题(分类器能命中板块)或明显题目措辞 → 按数学问题流程处理
  if (classifyQuestion(content).key !== 'other') return false
  if (MATH_STYLE_RE.test(content)) return false
  // 其余(自我介绍询问、情绪倾诉、一般对话等)一律正常交际
  return true
}
