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
    if (out.length >= limit) break
  }
  return out
}

export function nextShuffleSeed(previous: number): number {
  return (previous * 1103515245 + 12345) >>> 0
}
