// 권리분석 ViewModel 조립 계층 (읽기 전용)
// - tenant_rights / rights_summary 원본 데이터를 그대로 두고, 화면에 보여줄 형태로만 가공한다.
// - StatusMapper / SpecMapper / RightsAnalysisAssembler 구조를 유지한다.

export type SourceType = 'STATUS' | 'SPEC' | 'REGISTRY'

export interface TenantRow {
  tenant_name: string | null
  occupied_area: string | null
  deposit: number | null
  monthly_rent: number | null
  move_in_date: string | null
  fixed_date: string | null
  demand_date: string | null
  has_demand: number | null
  source: string
}

export interface RightsSummaryRaw {
  total_tenant_count: number | null
  is_vacant: number | null
  occupancy_status: string | null
  occupancy_difficulty: string | null
  risk_level: string | null
  estimated_inheritance: number | null
}

export interface StatusView {
  totalTenantCount: number | null
  isVacant: boolean | null
  occupancyStatus: string | null
  occupancyDifficulty: string | null
}

export interface SpecTenant {
  name: string | null
  occupiedArea: string | null
  deposit: number | null
  monthlyRent: number | null
  moveInDate: string | null
  fixedDate: string | null
  demandDate: string | null
  hasDemand: boolean | null
}

export interface SpecView {
  tenantCount: number
  tenants: SpecTenant[]
}

// eslint-disable-next-line @typescript-eslint/no-empty-object-type
export interface RegistryView {
  // 미래 예약 - 등기부 Sprint에서 채워짐
}

export type ConflictType = 'DIRECT_CONFLICT' | 'AGGREGATION_DIFFERENCE' | 'REPRESENTATION_DIFFERENCE'

export interface Conflict {
  field: string
  type: ConflictType
  values: { source: SourceType; value: unknown }[]
  description?: string
}

export type WarningCode = 'MISSING_SPEC' | 'MISSING_STATUS' | 'MULTIPLE_DEPOSIT' | 'MULTIPLE_DATE' | 'PARSER_LIMITATION'

export interface Warning {
  code: WarningCode
  message: string
}

export interface SourceStatus {
  source: SourceType
  available: boolean
}

export interface RightsAnalysisViewModel {
  statusView?: StatusView
  specView?: SpecView
  registryView?: RegistryView
  sourceStatus: SourceStatus[]
  sources: SourceType[]
  conflicts: Conflict[]
  warnings: Warning[]
  confidence: 'HIGH' | 'MEDIUM' | 'LOW'
  generatedAt: string
}

// ---------------------------------------------------------------------------
// StatusMapper
// ---------------------------------------------------------------------------

export function mapStatusView(rightsSummary: RightsSummaryRaw | null): StatusView | undefined {
  if (!rightsSummary) return undefined
  return {
    totalTenantCount: rightsSummary.total_tenant_count,
    isVacant: rightsSummary.is_vacant == null ? null : rightsSummary.is_vacant === 1,
    occupancyStatus: rightsSummary.occupancy_status,
    occupancyDifficulty: rightsSummary.occupancy_difficulty,
  }
}

// ---------------------------------------------------------------------------
// SpecMapper
// ---------------------------------------------------------------------------

export function mapSpecView(tenants: TenantRow[]): SpecView | undefined {
  const specRows = tenants.filter((t) => t.source === 'SPEC')
  if (specRows.length === 0) return undefined
  return {
    tenantCount: specRows.length,
    tenants: specRows.map((t) => ({
      name: t.tenant_name,
      occupiedArea: t.occupied_area,
      deposit: t.deposit,
      monthlyRent: t.monthly_rent,
      moveInDate: t.move_in_date,
      fixedDate: t.fixed_date,
      demandDate: t.demand_date,
      hasDemand: t.has_demand == null ? null : t.has_demand === 1,
    })),
  }
}

// ---------------------------------------------------------------------------
// RightsAnalysisAssembler
// ---------------------------------------------------------------------------

function detectConflicts(statusView?: StatusView, specView?: SpecView): Conflict[] {
  const conflicts: Conflict[] = []
  if (!statusView || !specView) return conflicts

  const statusCount = statusView.totalTenantCount
  const specCount = specView.tenantCount
  if (statusCount == null) return conflicts

  if (statusCount === 0 && specCount > 0) {
    conflicts.push({
      field: 'occupancy',
      type: 'DIRECT_CONFLICT',
      values: [
        { source: 'STATUS', value: '공실(0명)' },
        { source: 'SPEC', value: `임차인 ${specCount}명` },
      ],
      description: `현황조사서는 공실(0명)로, 매각물건명세서는 임차인 ${specCount}명으로 기록되어 있습니다.`,
    })
  } else if (statusCount !== specCount) {
    conflicts.push({
      field: 'total_tenant_count',
      type: 'AGGREGATION_DIFFERENCE',
      values: [
        { source: 'STATUS', value: statusCount },
        { source: 'SPEC', value: specCount },
      ],
      description: `현황조사서(${statusCount}명)와 매각물건명세서(${specCount}명)의 집계 인원수가 다릅니다. 집계 기준(호실 단위 vs 계약 단위) 차이일 수 있습니다.`,
    })
  }

  return conflicts
}

function detectWarnings(statusView?: StatusView, specView?: SpecView): Warning[] {
  const warnings: Warning[] = []
  if (!specView) {
    warnings.push({
      code: 'MISSING_SPEC',
      message: '매각물건명세서에서 확인 가능한 임차인 상세정보가 없습니다.',
    })
  }
  if (!statusView) {
    warnings.push({
      code: 'MISSING_STATUS',
      message: '현황조사서 기준 점유 현황 정보가 없습니다.',
    })
  }
  // MULTIPLE_DEPOSIT / MULTIPLE_DATE: 현재 DB에는 "왜 NULL인지"가 남아있지 않아
  // 이번 Sprint에서는 구현하지 않는다 (원인 파악 전까지 추정 금지 원칙).
  return warnings
}

function computeConfidence(conflicts: Conflict[]): 'HIGH' | 'MEDIUM' | 'LOW' {
  if (conflicts.some((c) => c.type === 'DIRECT_CONFLICT')) return 'LOW'
  if (conflicts.some((c) => c.type === 'AGGREGATION_DIFFERENCE')) return 'MEDIUM'
  return 'HIGH'
}

export function assembleRightsAnalysis(
  rightsSummary: RightsSummaryRaw | null,
  tenants: TenantRow[],
  // 내부 입력: 기존 Document Viewer Sprint의 GET/HEAD /api/v1/item/{id}/documents/SPEC
  // 판정 결과(파일시스템 기준 실제 존재 여부)를 그대로 전달받는다. ViewModel에는 이 값 자체가
  // 아니라 sourceStatus로 일반화되어 노출된다.
  specDocumentAvailable: boolean
): RightsAnalysisViewModel {
  const statusView = mapStatusView(rightsSummary)
  const specView = mapSpecView(tenants)

  const sources: SourceType[] = []
  if (statusView) sources.push('STATUS')
  if (specView) sources.push('SPEC')

  const conflicts = detectConflicts(statusView, specView)
  const warnings = detectWarnings(statusView, specView)
  const confidence = computeConfidence(conflicts)

  const sourceStatus: SourceStatus[] = [
    { source: 'STATUS', available: statusView !== undefined },
    { source: 'SPEC', available: specDocumentAvailable },
    { source: 'REGISTRY', available: false },
  ]

  return {
    statusView,
    specView,
    registryView: undefined,
    sourceStatus,
    sources,
    conflicts,
    warnings,
    confidence,
    generatedAt: new Date().toISOString(),
  }
}
