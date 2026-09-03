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
  // 2026-09-03 — `tenant_rights.source` 는 NOT NULL 이 아니고 `api/v1/item.py` 가
  // `_project()` 로 행 값을 그대로 실어 보낸다. 쓰는 곳은 `=== 'SPEC'` / `=== 'STATUS'`
  // 동등 비교뿐이라 null 이 와도 **양쪽 어디에도 안 들어가고 조용히 빠진다** —
  // 런타임 동작은 그대로 두고 선언만 사실에 맞춘다.
  source: string | null
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

// `SPEC_NOT_PARSED`는 2026-08-11 Sprint 55에 추가됐다.
// 그전에는 "명세서 문서가 없다"와 "문서는 있는데 임차인 정보가 파싱되지 않았다"가 둘 다
// `MISSING_SPEC` 하나로 나갔다. 문서 수집 상태가 화면에 제대로 반영되기 시작하자(BUGS #50)
// 이 뭉뚱그림이 드러났다 — 같은 화면에 이렇게 떴다:
//     정보원  SPEC ✓ 확보
//     경고    [MISSING_SPEC] 매각물건명세서에서 확인 가능한 임차인 상세정보가 없습니다.
// 둘 다 사실이지만(문서는 있고, 파싱 결과는 없다) 같은 단어를 써서 모순으로 읽힌다.
// 두 상황은 해야 할 일이 다르다 — 전자는 수집, 후자는 파서 점검이다.
export type WarningCode =
  | 'MISSING_SPEC'
  | 'SPEC_NOT_PARSED'
  | 'MISSING_STATUS'
  | 'MULTIPLE_DEPOSIT'
  | 'MULTIPLE_DATE'
  | 'PARSER_LIMITATION'

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

// 두 정보원을 실제로 대조할 수 있는 조건. `detectConflicts()`의 가드와 `computeConfidence()`의
// 입력이 **같은 함수**를 쓰게 해서 둘이 따로 놀지 않도록 한다 (BUGS #44 재발 방지).
// 정보원이 둘 다 있어도 비교 대상 값(임차인 수)이 NULL이면 대조는 못 한 것이다.
export function canCrossCheck(statusView?: StatusView, specView?: SpecView): boolean {
  if (!statusView || !specView) return false
  return statusView.totalTenantCount != null
}

function detectConflicts(statusView?: StatusView, specView?: SpecView): Conflict[] {
  const conflicts: Conflict[] = []
  if (!canCrossCheck(statusView, specView)) return conflicts

  // canCrossCheck()가 통과했으므로 아래 두 값은 존재한다.
  const statusCount = statusView!.totalTenantCount as number
  const specCount = specView!.tenantCount

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

function detectWarnings(
  statusView?: StatusView,
  specView?: SpecView,
  specDocumentAvailable = false
): Warning[] {
  const warnings: Warning[] = []
  if (!specView) {
    // 문서가 있는데 파싱 결과가 없는 것과, 문서 자체가 없는 것은 다른 상황이다.
    warnings.push(
      specDocumentAvailable
        ? {
            code: 'SPEC_NOT_PARSED',
            message: '매각물건명세서는 확보했으나 임차인 상세정보가 아직 분석되지 않았습니다.',
          }
        : {
            code: 'MISSING_SPEC',
            message: '매각물건명세서에서 확인 가능한 임차인 상세정보가 없습니다.',
          }
    )
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

// 신뢰도 = "얼마나 교차 검증됐는가". 충돌 유무만이 아니라 **대조 가능했는지**를 함께 본다.
//
// 2026-08-11 Sprint 54 수정 (BUGS #44):
// `detectConflicts()`는 `!statusView || !specView`이면 즉시 `[]`를 돌려준다. 즉 정보원이
// 하나뿐이면 "충돌 없음"이 아니라 **대조를 못 한 것**인데, 예전 구현은 그 둘을 구분하지 않고
// 똑같이 HIGH를 줬다. 그 결과 화면에 이런 모순이 그대로 나왔다:
//     신뢰도 HIGH  +  "매각물건명세서에서 확인 가능한 임차인 상세정보가 없습니다."
// 실측(2026-08-11): 권리 정보원이 하나라도 있는 180건 중 **81건**(STATUS만 63 + SPEC만 18)이
// 이 상태였다 — 근거가 가장 빈약한 물건이 가장 높은 신뢰도로 표시되고 있었다.
//
// 등급 기준은 새로 만들지 않고 기존 3단계의 의미를 그대로 따른다:
//   LOW    = 정보원끼리 정면으로 어긋남 (기존)
//   MEDIUM = 확정할 수 없음 — 집계 차이가 있거나(기존), 대조할 상대가 없음(추가)
//   HIGH   = 둘 이상의 정보원이 서로 일치 (기존 의미를 지키기 위해 조건을 명시)
// 반박된 것(LOW)과 확인되지 않은 것(MEDIUM)은 다르므로 단일 정보원을 LOW로 낮추지는 않는다.
function computeConfidence(conflicts: Conflict[], crossCheckable: boolean): 'HIGH' | 'MEDIUM' | 'LOW' {
  if (conflicts.some((c) => c.type === 'DIRECT_CONFLICT')) return 'LOW'
  if (conflicts.some((c) => c.type === 'AGGREGATION_DIFFERENCE')) return 'MEDIUM'
  if (!crossCheckable) return 'MEDIUM'
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
  const warnings = detectWarnings(statusView, specView, specDocumentAvailable)
  const confidence = computeConfidence(conflicts, canCrossCheck(statusView, specView))

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
