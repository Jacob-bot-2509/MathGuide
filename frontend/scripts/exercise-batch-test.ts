/** 习题集换批:排除列表去重、截断与种子推进。 */
import { mergeExcludeIds, nextShuffleSeed } from '../src/utils/exerciseBatch'

const merged = mergeExcludeIds(['a', 'b'], ['b', 'c', 'd'])
if (merged.join(',') !== 'a,b,c,d') {
  throw new Error(`merge failed: ${merged.join(',')}`)
}

const capped = mergeExcludeIds([], Array.from({ length: 250 }, (_, i) => `id${i}`), 200)
if (capped.length !== 200) {
  throw new Error(`cap failed: ${capped.length}`)
}

const seeded = nextShuffleSeed(7)
if (!Number.isInteger(seeded) || seeded < 0 || seeded === 7) {
  throw new Error(`seed failed: ${seeded}`)
}

console.log('习题集换批自测通过')
