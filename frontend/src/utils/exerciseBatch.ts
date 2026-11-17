/** 习题集换批:排除列表去重/截断与确定性种子推进。 */

export function mergeExcludeIds(
  current: string[],
  batchIds: string[],
  limit = 200,
): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const id of [...current, ...batchIds]) {
    if (!id || seen.has(id)) continue
    seen.add(id)
    out.push(id)
  }
  return out.length > limit ? out.slice(-limit) : out
}

export function nextShuffleSeed(previous: number): number {
  return (previous * 1103515245 + 12345) >>> 0
}

/** 只有站在习题预览页、且草稿属于这次预览时，下载才可确认历史。 */
export function shouldConfirmExercise(kind: 'document' | 'exercise', draftId: string): boolean {
  return kind === 'exercise' && draftId.length > 0
}
