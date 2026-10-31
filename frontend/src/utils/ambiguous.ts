/**
 * 跨板块知识点登记表。
 *
 * 同一个词在不同课程里含义/工具不同(最小二乘、傅里叶变换、特征值……)。
 * - 问题只含裸词、没有上下文时:detectAmbiguous 命中,界面先问「想了解哪一方面」;
 * - 已带明确语境(矩阵/回归/留数/微分方程……):resolveAmbiguous 直接定板块,不再追问。
 * 本文件只提供数据与判定,不依赖 classifier,避免循环引用。
 */

export interface Bi {
  zh: string
  en: string
}

export interface AmbiguousOption {
  /** 与 classifier 的板块 key 一致 */
  key: string
  label: Bi
  /** 该方向具体覆盖的内容,展示给用户 */
  hint: Bi
  /** 命中这些词就不必再问 */
  context: RegExp
}

export interface AmbiguousTopic {
  id: string
  term: RegExp
  /** 一句话说明这个知识点跨了哪些方面 */
  scope: Bi
  /** 用户不选、直接按默认板块回答时用 */
  fallback: string
  options: AmbiguousOption[]
}

const C = {
  analysis: { zh: '数学分析', en: 'Mathematical Analysis' },
  algebra: { zh: '高等代数', en: 'Advanced Algebra' },
  geometry: { zh: '空间解析几何', en: 'Analytic Geometry' },
  ode: { zh: '微分方程', en: 'Differential Equations' },
  probability: { zh: '概率论与数理统计', en: 'Probability & Statistics' },
  complex: { zh: '复变函数', en: 'Complex Analysis' },
  numberTheory: { zh: '数论', en: 'Number Theory' },
  topology: { zh: '拓扑学', en: 'Topology' },
} as const

type CatKey = keyof typeof C

function opt(key: CatKey, zh: string, en: string, context: RegExp): AmbiguousOption {
  return { key, label: C[key], hint: { zh, en }, context }
}

export const AMBIGUOUS_TOPICS: AmbiguousTopic[] = [
  {
    id: 'least-squares',
    term: /最小二乘|least squares?/i,
    scope: { zh: '线性代数中的投影与法方程,统计中的回归拟合', en: 'projection/normal equations in linear algebra, regression fitting in statistics' },
    fallback: 'algebra',
    options: [
      opt('algebra', '投影、法方程、超定方程组、QR/广义逆', 'projection, normal equations, overdetermined systems, QR/pseudoinverse', /矩阵|向量|投影|正交|法方程|超定|qr|线性方程组|列空间|秩|线性代数|高等代数|matrix|vector|projection|orthogonal|normal equation|overdetermined|column space|rank|linear algebra/i),
      opt('probability', '线性回归、参数估计、误差与拟合', 'linear regression, parameter estimation, error and fitting', /回归|拟合|统计|误差|样本|方差|估计|regression|fitting|fit|statistic|error|sample|variance|estimat/i),
    ],
  },
  {
    id: 'eigen',
    term: /特征值|特征向量|eigenvalue|eigenvector/i,
    scope: { zh: '矩阵对角化、微分方程组、马尔可夫链/随机矩阵', en: 'matrix diagonalization, ODE systems, Markov chains/random matrices' },
    fallback: 'algebra',
    options: [
      opt('algebra', '对角化、相似标准形、二次型', 'diagonalization, similarity forms, quadratic forms', /矩阵|对角化|相似|二次型|秩|行列式|matrix|diagonal|similar|quadratic form|determinant/i),
      opt('ode', '线性微分方程组、矩阵指数、稳定性', 'linear ODE systems, matrix exponential, stability', /微分方程|方程组|矩阵指数|稳定性|平衡点|ode|differential equation|stability|equilibrium/i),
      opt('probability', '马尔可夫链、随机矩阵、主成分分析', 'Markov chains, random matrices, PCA', /马尔可夫|随机矩阵|主成分|pca|markov|random matrix|principal component/i),
    ],
  },
  {
    id: 'quadratic-form',
    term: /二次型|quadratic form/i,
    scope: { zh: '代数中的标准形/正定性,几何中的二次曲面', en: 'canonical forms/definiteness in algebra, quadric surfaces in geometry' },
    fallback: 'algebra',
    options: [
      opt('algebra', '标准形、惯性定理、正定性', 'canonical form, Sylvester law, positive definiteness', /标准形|惯性|正定|合同|矩阵|standard form|inertia|positive definite|congruent|matrix/i),
      opt('geometry', '二次曲面分类、椭球/双曲/抛物面', 'classification of quadrics, ellipsoids/hyperboloids/paraboloids', /二次曲面|椭球|双曲|抛物|锥面|柱面|quadric|ellipsoid|hyperboloid|paraboloid|cone|cylinder/i),
    ],
  },
  {
    id: 'orthogonal-transform',
    term: /正交变换|orthogonal transformation/i,
    scope: { zh: '代数中的正交矩阵,几何中的旋转/反射/坐标变换', en: 'orthogonal matrices in algebra, rotations/reflections in geometry' },
    fallback: 'algebra',
    options: [
      opt('algebra', '正交矩阵、标准正交基、内积', 'orthogonal matrices, orthonormal bases, inner product', /正交矩阵|标准正交|内积|格拉姆|gram|orthonormal|inner product/i),
      opt('geometry', '坐标旋转、反射、刚体变换', 'coordinate rotations, reflections, rigid motions', /坐标|旋转|反射|刚体|空间|rotation|reflection|rigid|coordinate/i),
    ],
  },
  {
    id: 'vector-space',
    term: /向量空间|线性空间|vector space/i,
    scope: { zh: '代数中的基与线性映射,几何中的几何向量与空间图形', en: 'bases/linear maps in algebra, geometric vectors in geometry' },
    fallback: 'algebra',
    options: [
      opt('algebra', '基、维数、子空间、线性映射', 'bases, dimension, subspaces, linear maps', /基|维数|子空间|线性映射|同构|basis|dimension|subspace|linear map|isomorph/i),
      opt('geometry', '几何向量、平面与直线、空间坐标', 'geometric vectors, planes/lines, coordinates', /平面|直线|空间|坐标|叉积|点积|plane|line|space|coordinate|cross product|dot product/i),
    ],
  },
  {
    id: 'inner-product',
    term: /内积|inner product/i,
    scope: { zh: '代数内积空间、分析中的函数内积、几何点积', en: 'inner-product spaces, function inner products, geometric dot product' },
    fallback: 'algebra',
    options: [
      opt('algebra', '内积空间、正交、Gram 矩阵', 'inner-product spaces, orthogonality, Gram matrices', /内积空间|正交|格拉姆|gram|orthogonal|orthonormal/i),
      opt('analysis', '函数内积、傅里叶系数、希尔伯特空间', 'function inner products, Fourier coefficients, Hilbert spaces', /函数|傅里叶|希尔伯特|fourier|hilbert/i),
      opt('geometry', '点积、夹角、投影', 'dot product, angle, projection', /点积|夹角|投影|dot product|angle|projection/i),
    ],
  },
  {
    id: 'fourier-series',
    term: /傅里叶级数|fourier series/i,
    scope: { zh: '分析中的收敛与系数,复变中的复级数,微分方程中的周期解', en: 'convergence/coefficients in analysis, complex series, periodic solutions in ODEs' },
    fallback: 'analysis',
    options: [
      opt('analysis', '收敛性、系数计算、狄利克雷条件', 'convergence, coefficients, Dirichlet conditions', /收敛|系数|狄利克雷|dirichlet|coefficient|convergen/i),
      opt('complex', '复傅里叶级数、解析函数、留数', 'complex Fourier series, analytic functions, residues', /复|解析|留数|complex|analytic|residue/i),
      opt('ode', '周期解、热方程/波动方程', 'periodic solutions, heat/wave equations', /周期解|热方程|波动方程|偏微分|periodic|heat equation|wave equation|pde/i),
    ],
  },
  {
    id: 'fourier-transform',
    term: /傅里叶变换|fourier transform/i,
    scope: { zh: '分析中的积分变换,复变中的围道/留数,微分方程中的解法', en: 'integral transforms in analysis, contour/residue methods, solving ODEs' },
    fallback: 'analysis',
    options: [
      opt('analysis', '积分变换、收敛、帕塞瓦尔', 'integral transforms, convergence, Parseval', /积分变换|收敛|帕塞瓦尔|parseval|convergen|integral transform/i),
      opt('complex', '解析延拓、围道积分、留数', 'analytic continuation, contour integrals, residues', /解析|围道|留数|complex|analytic|contour|residue/i),
      opt('ode', '解微分方程、卷积、传递函数', 'solving ODEs, convolution, transfer functions', /微分方程|卷积|传递函数|ode|differential equation|convolution|transfer function/i),
    ],
  },
  {
    id: 'laplace-transform',
    term: /拉普拉斯变换|laplace transform/i,
    scope: { zh: '微分方程初值问题,复变中的收敛域/反演,概率中的矩母函数', en: 'IVPs in ODEs, ROC/inversion in complex analysis, moment generating functions' },
    fallback: 'ode',
    options: [
      opt('ode', '初值问题、传递函数、解方程', 'initial-value problems, transfer functions, solving ODEs', /初值|传递函数|解方程|微分方程|initial|transfer function|solve|ode/i),
      opt('complex', '收敛域、反演、复变方法', 'region of convergence, inversion, complex methods', /收敛域|反演|复变|留数|roc|inversion|complex|residue/i),
      opt('probability', '矩母函数、随机变量变换', 'moment generating functions, transforms of random variables', /矩母|随机变量|分布|期望|moment generating|random variable|distribution|expectation/i),
    ],
  },
  {
    id: 'taylor',
    term: /泰勒展开|泰勒级数|taylor (expansion|series)/i,
    scope: { zh: '分析中的余项/收敛,复变中的洛朗级数与奇点', en: 'remainder/convergence in analysis, Laurent series/singularities in complex analysis' },
    fallback: 'analysis',
    options: [
      opt('analysis', '余项、收敛半径、近似计算', 'remainder, radius of convergence, approximation', /余项|收敛|近似|remainder|convergen|approximat/i),
      opt('complex', '洛朗级数、解析函数、奇点', 'Laurent series, analytic functions, singularities', /洛朗|解析|奇点|laurent|analytic|singular/i),
    ],
  },
  {
    id: 'residue',
    term: /留数|residue theorem|residue/i,
    scope: { zh: '复变中的围道积分,分析中用留数算实积分', en: 'contour integrals in complex analysis, real integrals via residues' },
    fallback: 'complex',
    options: [
      opt('complex', '留数定理、围道积分、奇点', 'residue theorem, contour integrals, singularities', /留数定理|围道|奇点|contour|singular/i),
      opt('analysis', '用留数计算实积分/反常积分', 'real or improper integrals via residues', /实积分|反常积分|定积分|real integral|improper integral/i),
    ],
  },
  {
    id: 'power-series',
    term: /幂级数|power series/i,
    scope: { zh: '分析中的收敛半径,复变中的解析延拓', en: 'radius of convergence in analysis, analytic continuation in complex analysis' },
    fallback: 'analysis',
    options: [
      opt('analysis', '收敛半径、一致收敛、求和', 'radius, uniform convergence, summation', /收敛半径|一致收敛|求和|radius|uniform|summ/i),
      opt('complex', '解析延拓、奇点、洛朗级数', 'analytic continuation, singularities, Laurent series', /解析|奇点|洛朗|analytic|singular|laurent/i),
    ],
  },
  {
    id: 'euler-formula',
    term: /欧拉公式|euler'?s formula/i,
    scope: { zh: '复变中的复指数,分析中的级数,拓扑中的多面体公式', en: 'complex exponentials, series in analysis, polyhedron formula in topology' },
    fallback: 'complex',
    options: [
      opt('complex', '复指数、欧拉恒等式', 'complex exponentials, Euler identity', /复指数|复变|欧拉恒等式|complex exponential|complex analysis|identity/i),
      opt('analysis', '级数展开、三角函数', 'series expansions, trigonometric functions', /级数|三角|幂级数|series|trigonometric|power series/i),
      opt('topology', '多面体 V-E+F=2', 'polyhedra V-E+F=2', /多面体|顶点|棱|面|polyhedron|vertices|edges|faces/i),
    ],
  },
  {
    id: 'cauchy-riemann',
    term: /柯西.?黎曼|cauchy.?riemann/i,
    scope: { zh: '复变中的解析条件,分析中的多元可微性', en: 'analyticity conditions in complex analysis, differentiability in multivariable analysis' },
    fallback: 'complex',
    options: [
      opt('complex', '解析函数、复可微', 'analytic functions, complex differentiability', /解析|复可微|复变|analytic|complex differentiab/i),
      opt('analysis', '多元函数可微、偏导', 'multivariable differentiability, partial derivatives', /多元|偏导|可微|partial|multivariable|differentiab/i),
    ],
  },
  {
    id: 'green-theorem',
    term: /格林公式|green'?s theorem/i,
    scope: { zh: '分析中的曲线积分/二重积分,几何中的向量场与旋度', en: 'line/double integrals in analysis, vector fields/curl in geometry' },
    fallback: 'analysis',
    options: [
      opt('analysis', '曲线积分、二重积分、面积', 'line integrals, double integrals, area', /曲线积分|二重积分|面积|line integral|double integral|area/i),
      opt('geometry', '向量场、旋度、平面区域', 'vector fields, curl, planar regions', /向量场|旋度|平面|vector field|curl|plane/i),
    ],
  },
  {
    id: 'divergence-theorem',
    term: /高斯定理|散度定理|divergence theorem/i,
    scope: { zh: '分析中的曲面积分/三重积分,几何中的通量与散度', en: 'surface/triple integrals in analysis, flux/divergence in geometry' },
    fallback: 'analysis',
    options: [
      opt('analysis', '曲面积分、三重积分、通量', 'surface integrals, triple integrals, flux', /曲面积分|三重积分|通量|surface integral|triple integral|flux/i),
      opt('geometry', '向量场、曲面、散度', 'vector fields, surfaces, divergence', /向量场|曲面|散度|vector field|surface|divergence/i),
    ],
  },
  {
    id: 'stokes-theorem',
    term: /斯托克斯|stokes'? theorem/i,
    scope: { zh: '分析中的曲线积分,几何中的曲面/旋度,拓扑中的微分形式', en: 'line integrals, surfaces/curl, differential forms in topology' },
    fallback: 'analysis',
    options: [
      opt('analysis', '曲线积分、旋度、曲面', 'line integrals, curl, surfaces', /曲线积分|旋度|曲面|line integral|curl|surface/i),
      opt('geometry', '空间曲线曲面、向量场', 'space curves/surfaces, vector fields', /空间|向量场|曲线|曲面|space|vector field|curve|surface/i),
      opt('topology', '微分形式、流形上的积分', 'differential forms, integration on manifolds', /微分形式|流形|外微分|differential form|manifold|exterior/i),
    ],
  },
  {
    id: 'vector-calculus',
    term: /梯度|散度|旋度|gradient|divergence|curl/i,
    scope: { zh: '分析中的多元微分/场论,几何中的方向导数与曲面法向', en: 'multivariable calculus/field theory, directional derivatives/surface normals' },
    fallback: 'analysis',
    options: [
      opt('analysis', '多元微分、场论、积分公式', 'multivariable differentiation, field theory, integral theorems', /多元|偏导|场论|积分公式|multivariable|partial|field theory|integral theorem/i),
      opt('geometry', '向量场、方向导数、曲面法向', 'vector fields, directional derivatives, surface normals', /向量场|方向导数|法向|曲面|vector field|directional|normal|surface/i),
    ],
  },
  {
    id: 'line-surface-integral',
    term: /曲线积分|曲面积分|line integral|surface integral/i,
    scope: { zh: '分析中的计算与积分公式,几何中的曲线曲面与通量', en: 'evaluation/integral theorems, curves/surfaces and flux' },
    fallback: 'analysis',
    options: [
      opt('analysis', '计算、格林/高斯/斯托克斯', 'evaluation, Green/Gauss/Stokes', /计算|格林|高斯|斯托克斯|green|gauss|stokes|evaluat/i),
      opt('geometry', '曲线曲面、向量场、通量', 'curves/surfaces, vector fields, flux', /曲线|曲面|向量场|通量|curve|surface|vector field|flux/i),
    ],
  },
  {
    id: 'jacobian',
    term: /雅可比|jacobian/i,
    scope: { zh: '分析中的多元微分/隐函数,代数中的线性变换矩阵', en: 'multivariable differentiation/implicit functions, linear transformation matrices' },
    fallback: 'analysis',
    options: [
      opt('analysis', '多元微分、隐函数、变量替换', 'multivariable differentiation, implicit functions, change of variables', /多元|隐函数|变量替换|偏导|multivariable|implicit|change of variables|partial/i),
      opt('algebra', '线性变换、矩阵表示、秩', 'linear transformations, matrix representation, rank', /线性变换|矩阵表示|秩|linear transformation|matrix|rank/i),
    ],
  },
  {
    id: 'implicit-function',
    term: /隐函数定理|implicit function theorem/i,
    scope: { zh: '分析中的存在性定理,几何中的曲线曲面参数化', en: 'existence theorem in analysis, parametrization of curves/surfaces' },
    fallback: 'analysis',
    options: [
      opt('analysis', '多元微积分、存在性、可微性', 'multivariable calculus, existence, differentiability', /多元|存在|可微|偏导|multivariable|existence|differentiab|partial/i),
      opt('geometry', '曲线曲面、参数化、切平面', 'curves/surfaces, parametrization, tangent planes', /曲线|曲面|参数化|切平面|curve|surface|parametr|tangent/i),
    ],
  },
  {
    id: 'quadric-surface',
    term: /二次曲面|quadric surface/i,
    scope: { zh: '几何中的标准方程/图形,代数中的二次型/合同', en: 'standard equations/shapes in geometry, quadratic forms in algebra' },
    fallback: 'geometry',
    options: [
      opt('geometry', '标准方程、分类、图形', 'standard equations, classification, shapes', /标准方程|分类|图形|椭球|双曲|抛物|standard equation|classif|ellipsoid|hyperboloid|paraboloid/i),
      opt('algebra', '二次型、合同变换、惯性定理', 'quadratic forms, congruence, inertia law', /二次型|合同|惯性|quadratic form|congruen|inertia/i),
    ],
  },
  {
    id: 'norm',
    term: /范数|(^|[^a-z])norms?([^a-z]|$)/i,
    scope: { zh: '代数中的向量/矩阵范数,分析中的函数空间与收敛', en: 'vector/matrix norms in algebra, function spaces/convergence in analysis' },
    fallback: 'algebra',
    options: [
      opt('algebra', '向量空间、内积、矩阵范数', 'vector spaces, inner products, matrix norms', /向量空间|内积|矩阵|vector space|inner product|matrix/i),
      opt('analysis', '函数空间、收敛、逼近', 'function spaces, convergence, approximation', /函数空间|收敛|逼近|function space|convergen|approximat/i),
    ],
  },
  {
    id: 'convolution',
    term: /卷积|convolution/i,
    scope: { zh: '分析中的积分变换,概率中的随机变量和,微分方程中的响应', en: 'integral transforms, sums of random variables, system response' },
    fallback: 'analysis',
    options: [
      opt('analysis', '傅里叶/拉普拉斯变换、积分', 'Fourier/Laplace transforms, integrals', /傅里叶|拉普拉斯|积分|fourier|laplace|integral/i),
      opt('probability', '随机变量和、分布卷积', 'sums of random variables, distribution convolution', /随机变量|分布|概率|random variable|distribution|probability/i),
      opt('ode', '线性系统、脉冲响应', 'linear systems, impulse response', /线性系统|脉冲响应|传递函数|linear system|impulse response|transfer function/i),
    ],
  },
  {
    id: 'generating-function',
    term: /生成函数|母函数|generating function/i,
    scope: { zh: '数论/组合中的分拆,概率中的矩与分支过程,分析中的幂级数', en: 'partitions in number theory, moments/branching in probability, power series in analysis' },
    fallback: 'numberTheory',
    options: [
      opt('numberTheory', '分拆、数论函数、形式幂级数', 'partitions, arithmetic functions, formal power series', /分拆|数论|组合|partition|number theory|combinator|formal power series/i),
      opt('probability', '概率生成函数、矩、分支过程', 'probability generating functions, moments, branching processes', /概率|矩|分支过程|probability|moment|branching/i),
      opt('analysis', '幂级数、收敛、组合计数', 'power series, convergence, combinatorial enumeration', /幂级数|收敛|计数|power series|convergen|enumerat/i),
    ],
  },
  {
    id: 'markov-chain',
    term: /马尔可夫链|markov chain/i,
    scope: { zh: '概率中的转移/平稳分布,代数中的转移矩阵/特征值', en: 'transitions/stationary distributions in probability, transition matrices/eigenvalues' },
    fallback: 'probability',
    options: [
      opt('probability', '转移概率、平稳分布、极限行为', 'transition probabilities, stationary distributions, limiting behavior', /转移概率|平稳分布|极限|transition|stationary|limiting/i),
      opt('algebra', '转移矩阵、特征值、随机矩阵', 'transition matrices, eigenvalues, stochastic matrices', /转移矩阵|特征值|随机矩阵|transition matrix|eigen|stochastic/i),
    ],
  },
  {
    id: 'matrix-exponential',
    term: /矩阵指数|matrix exponential/i,
    scope: { zh: '代数中的矩阵函数,微分方程中的线性系统解', en: 'matrix functions in algebra, linear system solutions in ODEs' },
    fallback: 'algebra',
    options: [
      opt('algebra', '矩阵函数、特征值、最小多项式', 'matrix functions, eigenvalues, minimal polynomials', /矩阵函数|特征值|最小多项式|matrix function|eigen|minimal polynomial/i),
      opt('ode', '线性微分方程组、状态转移', 'linear ODE systems, state transition', /微分方程|线性系统|状态转移|ode|linear system|state transition/i),
    ],
  },
  {
    id: 'ode-system',
    term: /常微分方程组|微分方程组|system of (linear )?odes/i,
    scope: { zh: '微分方程中的解/初值问题,代数中的矩阵/特征值方法', en: 'solutions/IVPs in ODEs, matrix/eigenvalue methods in algebra' },
    fallback: 'ode',
    options: [
      opt('ode', '解的存在唯一、初值问题、稳定性', 'existence/uniqueness, IVPs, stability', /初值|存在唯一|稳定性|解|initial|existence|uniqueness|stability|solution/i),
      opt('algebra', '矩阵形式、特征值、对角化', 'matrix form, eigenvalues, diagonalization', /矩阵|特征值|对角化|matrix|eigen|diagonal/i),
    ],
  },
  {
    id: 'prime-number-theorem',
    term: /素数定理|prime number theorem/i,
    scope: { zh: '数论中的素数分布,复变中的黎曼ζ函数', en: 'prime distribution in number theory, Riemann zeta in complex analysis' },
    fallback: 'numberTheory',
    options: [
      opt('numberTheory', '素数分布、渐近估计', 'prime distribution, asymptotic estimates', /素数分布|渐近|估计|prime distribution|asymptotic|estimat/i),
      opt('complex', '黎曼ζ函数、解析数论', 'Riemann zeta, analytic number theory', /黎曼|ζ|zeta|解析数论|analytic number theory/i),
    ],
  },
  {
    id: 'riemann-zeta',
    term: /黎曼.?ζ|黎曼zeta|riemann zeta/i,
    scope: { zh: '数论中的素数分布,复变中的解析延拓/零点', en: 'prime distribution in number theory, analytic continuation/zeros in complex analysis' },
    fallback: 'numberTheory',
    options: [
      opt('numberTheory', '素数分布、欧拉乘积', 'prime distribution, Euler product', /素数|欧拉乘积|prime|euler product/i),
      opt('complex', '解析延拓、零点、留数', 'analytic continuation, zeros, residues', /解析延拓|零点|留数|analytic|zeros|residue/i),
      opt('analysis', '级数、积分表示', 'series, integral representations', /级数|积分表示|series|integral representation/i),
    ],
  },
  {
    id: 'analytic-number-theory',
    term: /解析数论|analytic number theory/i,
    scope: { zh: '数论中的素数/算术函数,复变中的ζ函数与复分析', en: 'primes/arithmetic functions in number theory, zeta/complex analysis' },
    fallback: 'numberTheory',
    options: [
      opt('numberTheory', '素数分布、算术函数', 'prime distribution, arithmetic functions', /素数|算术函数|prime|arithmetic function/i),
      opt('complex', '复分析、ζ函数、留数', 'complex analysis, zeta, residues', /复分析|ζ|zeta|留数|complex analysis|residue/i),
    ],
  },
  {
    id: 'variational',
    term: /变分法|calculus of variations/i,
    scope: { zh: '分析中的泛函极值,微分方程中的欧拉-拉格朗日方程', en: 'functional extrema in analysis, Euler-Lagrange equations in ODEs' },
    fallback: 'analysis',
    options: [
      opt('analysis', '泛函极值、变分、存在性', 'functional extrema, variations, existence', /泛函|极值|变分|存在|functional|extremum|variation|existence/i),
      opt('ode', '欧拉-拉格朗日方程、边值问题', 'Euler-Lagrange equations, boundary-value problems', /欧拉.?拉格朗日|边值|微分方程|euler.?lagrange|boundary|ode/i),
    ],
  },
  {
    id: 'green-function',
    term: /格林函数|green'?s function/i,
    scope: { zh: '微分方程中的边值问题,分析中的积分方程/变换', en: 'boundary-value problems in ODEs, integral equations/transforms in analysis' },
    fallback: 'ode',
    options: [
      opt('ode', '微分方程、边值问题、响应', 'differential equations, boundary-value problems, response', /微分方程|边值|响应|ode|boundary|response/i),
      opt('analysis', '积分方程、傅里叶/拉普拉斯', 'integral equations, Fourier/Laplace', /积分方程|傅里叶|拉普拉斯|integral equation|fourier|laplace/i),
    ],
  },
  {
    id: 'parseval',
    term: /帕塞瓦尔|parseval/i,
    scope: { zh: '分析中的傅里叶级数/能量恒等式,复变中的正交展开', en: 'Fourier series/energy identity in analysis, orthogonal expansions in complex analysis' },
    fallback: 'analysis',
    options: [
      opt('analysis', '傅里叶级数、能量恒等式', 'Fourier series, energy identity', /傅里叶|能量|fourier|energy/i),
      opt('complex', '复傅里叶、正交展开', 'complex Fourier, orthogonal expansions', /复|正交|复变|complex|orthogonal/i),
    ],
  },
]

function stripMeta(text: string): string {
  return text.replace(/^\s*\[.+?\]\s*/, '').trim()
}

export function topicById(id: string): AmbiguousTopic | null {
  return AMBIGUOUS_TOPICS.find((topic) => topic.id === id) ?? null
}

/** 已有上下文能确定方向时返回该方向;否则返回 null。 */
export function resolveAmbiguous(text: string): { topic: AmbiguousTopic; option: AmbiguousOption } | null {
  const content = stripMeta(text).toLowerCase()
  for (const topic of AMBIGUOUS_TOPICS) {
    if (!topic.term.test(content)) continue
    const option = topic.options.find((item) => item.context.test(content))
    if (option) return { topic, option }
    return null
  }
  return null
}

/** 只提到裸词、没有任何方向线索时返回待询问的知识点。 */
export function detectAmbiguous(text: string): AmbiguousTopic | null {
  const content = stripMeta(text).toLowerCase()
  for (const topic of AMBIGUOUS_TOPICS) {
    if (!topic.term.test(content)) continue
    if (topic.options.some((option) => option.context.test(content))) return null
    return topic
  }
  return null
}
