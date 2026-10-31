/** 问题分类器:最小二乘在线性代数/统计之间的上下文判定。 */
/* eslint-disable */
declare const process: { exit(code: number): void }

import { classifyQuestion } from '../src/utils/classifier'
import { detectAmbiguous, resolveAmbiguous } from '../src/utils/ambiguous'

let passed = 0
const failed: string[] = []
function check(name: string, actual: string, expected: string) {
  if (actual === expected) passed++
  else failed.push(`${name}: ${actual} != ${expected}`)
}

const cases: Array<[string, string]> = [
  ['最小二乘法', 'algebra'],
  ['高等代数中的最小二乘法', 'algebra'],
  ['最小二乘法的矩阵形式', 'algebra'],
  ['用正交投影理解最小二乘', 'algebra'],
  ['最小二乘回归', 'probability'],
  ['线性回归的最小二乘估计', 'probability'],
  ['最小二乘拟合', 'probability'],
  ['least squares', 'algebra'],
  ['least squares regression', 'probability'],
]

for (const [text, expected] of cases) {
  check(text, classifyQuestion(text).key, expected)
}

// 裸词要触发询问;带方向词不能打扰用户
const ambiguousCases: Array<[string, string, string]> = [
  ['最小二乘法', 'least-squares', 'ask'],
  ['特征值', 'eigen', 'ask'],
  ['傅里叶变换', 'fourier-transform', 'ask'],
  ['二次型', 'quadratic-form', 'ask'],
  ['矩阵特征值', '', 'resolved'],
  ['最小二乘回归', '', 'resolved'],
  ['二次曲面的标准方程', '', 'resolved'],
  ['normal distribution', '', 'none'],
  ['普通的高数问题', '', 'none'],
]
for (const [text, id, expected] of ambiguousCases) {
  if (expected === 'ask') {
    check(`${text} 询问`, detectAmbiguous(text)?.id ?? 'none', id)
  } else if (expected === 'resolved') {
    check(`${text} 不询问`, detectAmbiguous(text) ? 'ask' : 'resolved', 'resolved')
    check(`${text} 有方向`, resolveAmbiguous(text) ? 'yes' : 'no', 'yes')
  } else {
    check(`${text} 不触发`, detectAmbiguous(text) ? 'ask' : 'none', 'none')
  }
}

if (failed.length) {
  console.error(`分类器自测:${passed}/${passed + failed.length} 通过`)
  failed.forEach((item) => console.error(`  ✗ ${item}`))
  process.exit(1)
}
console.log(`分类器自测:${passed}/${passed} 通过`)
