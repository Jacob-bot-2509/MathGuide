/** 习题集换批:排除列表去重、截断与种子推进。 */
import { mergeExcludeIds, nextShuffleSeed, shouldConfirmExercise } from '../src/utils/exerciseBatch'

const merged = mergeExcludeIds(['a', 'b'], ['b', 'c', 'd'])
if (merged.join(',') !== 'a,b,c,d') {
  throw new Error(`merge failed: ${merged.join(',')}`)
}

const capped = mergeExcludeIds([], Array.from({ length: 250 }, (_, i) => `id${i}`), 200)
if (capped.length !== 200) {
  throw new Error(`cap failed: ${capped.length}`)
}
if (capped[0] !== 'id50' || capped[capped.length - 1] !== 'id249') {
  throw new Error(`cap kept wrong end: ${capped[0]}..${capped[capped.length - 1]}`)
}

const seeded = nextShuffleSeed(7)
if (!Number.isInteger(seeded) || seeded < 0 || seeded === 7) {
  throw new Error(`seed failed: ${seeded}`)
}

if (shouldConfirmExercise('document', 'draft-1')) {
  throw new Error('document preview must not confirm an exercise draft')
}
if (!shouldConfirmExercise('exercise', 'draft-1')) {
  throw new Error('exercise preview with a draft must confirm')
}

console.log('习题集换批自测通过')
