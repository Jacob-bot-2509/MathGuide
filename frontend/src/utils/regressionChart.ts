export interface RegressionPointLike {
  row: number
  x?: number
  actual: number
  fitted: number
  residual: number
}

export interface RegressionResultLike {
  points: RegressionPointLike[]
  fitCurve: { x: number; y: number }[]
}

export interface ChartPoint {
  x: number
  y: number
}

export interface ChartSegment {
  points: ChartPoint[]
}

export function fitSegments(result: RegressionResultLike): ChartSegment[] {
  return result.fitCurve.length ? [{ points: result.fitCurve }] : []
}

export function residualSegments(result: RegressionResultLike): ChartPoint[] {
  return result.points.map((point) => ({
    x: point.fitted,
    y: point.residual,
  }))
}
