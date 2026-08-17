<#
.SYNOPSIS
    수집 파이프라인 3개를 Windows 작업 스케줄러에 등록한다. **기본은 dry-run.**

.DESCRIPTION
    2026-08-14 신설. 이 저장소의 `--apply` 관례를 따른다 ―
    아무 인자 없이 실행하면 **무엇을 등록할지 보여주기만** 하고 아무것도 바꾸지 않는다.

    왜 필요한가
    ---------------------------------------------------------------------------
    저장소를 가리키는 작업 스케줄러 항목이 **0개**다(2026-08-14 실측, 전체 248개 중).
    그래서 2026-08-12 이후 크롤이 돌지 않았고, 남은 진행 중 물건은 **9건**이며
    전부 2026-08-19까지의 기일이다 ― **2026-08-20부터 검색 결과가 0건이 된다.**

    선행 조건은 전부 확인됐다(.bat 3개의 경로/로그/실패 검출, python 해석, 마이그레이션).
    남은 것은 등록뿐이라 이 스크립트가 그 한 단계를 담당한다.

    ★ 계정 함정 (2026-08-14 실측)
    ---------------------------------------------------------------------------
    `python.exe` 가 **사용자 PATH 에만** 있다.

        머신 PATH 에 Python312  : False
        사용자 PATH 에 Python312: True
        C:\ProgramData\Anaconda3\python.exe : 없음

    따라서 작업을 **SYSTEM 계정으로 등록하면 python 을 찾지 못해 실패한다.**
    (조용히 실패하지는 않는다 ― `.bat` 이 `[FAILED] Python 인터프리터를 찾을 수 없습니다`
     를 로그에 남기고 exit 1 한다. Sprint 54의 3단 폴백 덕이다.)

    그래서 이 스크립트는 **현재 사용자 계정**으로, 로그온 상태에서 도는 방식으로 등록한다.
    비밀번호 입력이 필요 없고, 데스크톱 PC 운영에 맞는 가장 단순한 형태다.

    로그온하지 않은 상태에서도 돌려야 한다면 `-RunWhetherLoggedOn` 을 주면 되고,
    그때는 Windows 가 자격 증명을 묻는다.

.PARAMETER Apply
    실제로 등록한다. 주지 않으면 계획만 출력한다.

.PARAMETER RunWhetherLoggedOn
    로그온하지 않아도 실행되게 등록한다(자격 증명 입력 필요).
    이때는 사용자 PATH 가 로드되므로 python 해석은 그대로 동작한다.

.EXAMPLE
    .\register_scheduler_tasks.ps1
    # 무엇을 등록할지 보여준다. 아무것도 바꾸지 않는다.

.EXAMPLE
    .\register_scheduler_tasks.ps1 -Apply
    # 실제로 등록하고, 등록 결과를 다시 조회해 확인한다.
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$RunWhetherLoggedOn
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

# 시각은 docs/CLAUDE.md 의 파이프라인 설명을 따른다.
#   01:50 우선순위 재계산 -> 02:00 문서 수집 -> 06:00 사건 수집 + migrate
# 순서가 중요하다: 우선순위가 먼저 갱신돼야 임박 물건이 문서 수집에서 앞으로 온다.
$Tasks = @(
    @{ Name = 'DojoonPass-PriorityRefresh'; Bat = 'run_priority_refresh.bat'; Time = '01:50'
       Desc = '문서 수집 우선순위 재계산 (기일 임박도)' }
    @{ Name = 'DojoonPass-DocWorker';       Bat = 'run_doc_worker.bat';       Time = '02:00'
       Desc = 'document_queue 소진 - 물건별 문서 수집' }
    @{ Name = 'DojoonPass-DailyCrawl';      Bat = 'run_daily.bat';            Time = '06:00'
       Desc = '법원경매 사건 수집 -> 검증/정규화 -> auction -> auction_item 동기화' }
)

Write-Host ('=' * 74)
Write-Host '수집 파이프라인 스케줄러 등록'
Write-Host ('=' * 74)
Write-Host "  저장소 : $Root"
Write-Host "  계정   : $env:USERDOMAIN\$env:USERNAME"
Write-Host ''

# --- 선행 조건 확인 (등록 전에 실패할 것을 미리 잡는다) --------------------------
$problems = @()
foreach ($t in $Tasks) {
    $p = Join-Path $Root $t.Bat
    if (-not (Test-Path $p)) { $problems += "배치 파일 없음: $($t.Bat)" }
}
$anaconda = Test-Path 'C:\ProgramData\Anaconda3\python.exe'
$pathPy = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $anaconda -and -not $pathPy) {
    $problems += 'python.exe 를 찾을 수 없다 (Anaconda 경로도, PATH 에도 없다)'
}

Write-Host '선행 조건'
Write-Host ("  배치 파일 3개        : {0}" -f $(if ($problems | Where-Object { $_ -like '배치*' }) { '★ 누락' } else { 'OK' }))
Write-Host ("  Anaconda python      : {0}" -f $(if ($anaconda) { '있음' } else { '없음 (PATH 폴백)' }))
Write-Host ("  PATH python          : {0}" -f $(if ($pathPy) { $pathPy } else { '★ 없음' }))

$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$machineHasPy = $false
foreach ($d in ($machinePath -split ';')) {
    if ($d -and (Test-Path (Join-Path $d 'python.exe') -ErrorAction SilentlyContinue)) { $machineHasPy = $true; break }
}
Write-Host ("  머신 PATH 로 해석 가능 : {0}" -f $(if ($machineHasPy) { '예' } else { '아니오 -> SYSTEM 계정 등록 금지' }))

# --- 이 스크립트가 모르는, 같은 .bat 을 가리키는 기존 작업 탐지 (2026-08-17 Sprint 187) ---
#
# 실측(2026-08-17): 이 저장소를 가리키는 작업이 "DOJOONPASS_DAILY"라는 **다른 이름**으로
# 이미 등록돼 있었다 (매일 03:00, run_daily.bat, LastTaskResult 0 = 정상 동작 중).
# 이 스크립트는 자기가 등록/조회하는 이름(DojoonPass-DailyCrawl 등)만 알아서 그 존재를
# 모르고, 그대로 -Apply 하면 **같은 run_daily.bat 을 하루 두 번(03:00 기존 + 06:00 신규)
# 도는 중복 작업**이 생긴다 — mvp_scraper.py 는 idempotent upsert라 데이터가 깨지지는
# 않지만, 법원 사이트에 불필요한 크롤을 두 배로 걸고 로그도 두 갈래로 갈린다.
#
# 자동으로 지우지 않는다 — 어떤 이름의 기존 작업을 정리할지는 이 스크립트가 판단할
# 일이 아니라 실행하는 사람의 몫이다. 여기서는 **알아채지 못하고 지나치는 일**만 막는다.
$knownNames = $Tasks.Name
$legacyCandidates = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
    $_.TaskName -notin $knownNames -and
    ($_.Actions | ForEach-Object { $_.Arguments }) -match 'run_daily\.bat|run_doc_worker\.bat|run_priority_refresh\.bat'
}
if ($legacyCandidates) {
    Write-Host ''
    Write-Host '★ 이 스크립트가 등록/관리하지 않는, 같은 배치를 가리키는 기존 작업이 있다:'
    foreach ($lc in $legacyCandidates) {
        $info = Get-ScheduledTaskInfo -TaskName $lc.TaskName -ErrorAction SilentlyContinue
        Write-Host ("    - {0}  (마지막 실행 {1}, 결과 {2})" -f $lc.TaskName, $info.LastRunTime, $info.LastTaskResult)
    }
    Write-Host '  -Apply 로 그대로 진행하면 같은 배치가 하루 두 번 이상 돈다.'
    Write-Host '  계속하기 전에 위 작업을 남길지/지울지 직접 판단할 것 (이 스크립트는 지우지 않는다).'
}

if ($problems) {
    Write-Host ''
    Write-Host '★ 선행 조건이 충족되지 않았다. 등록해도 실행 시 실패한다:'
    $problems | ForEach-Object { Write-Host "    - $_" }
    exit 1
}

# --- 계획 출력 ----------------------------------------------------------------
Write-Host ''
Write-Host '등록할 작업'
foreach ($t in $Tasks) {
    $existing = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
    $mark = if ($existing) { '(이미 있음 -> 덮어씀)' } else { '(신규)' }
    Write-Host ("  {0,-28} 매일 {1}  {2}  {3}" -f $t.Name, $t.Time, $t.Bat, $mark)
    Write-Host ("  {0,-28} {1}" -f '', $t.Desc)
}

Write-Host ''
Write-Host ("실행 방식 : {0}" -f $(if ($RunWhetherLoggedOn) { '로그온 여부와 무관 (자격 증명 필요)' } else { '로그온 상태에서만 (비밀번호 불필요)' }))

if (-not $Apply) {
    Write-Host ''
    Write-Host '[DRY-RUN] 아무것도 등록하지 않았다. 실제로 등록하려면 -Apply 를 붙여라.'
    Write-Host '          예: .\register_scheduler_tasks.ps1 -Apply'
    exit 0
}

# --- 실제 등록 ----------------------------------------------------------------
Write-Host ''
foreach ($t in $Tasks) {
    $action  = New-ScheduledTaskAction -Execute 'cmd.exe' `
                   -Argument ('/c "' + (Join-Path $Root $t.Bat) + '"') -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -Daily -At $t.Time
    # 노트북/절전 환경에서 놓치지 않도록: 놓친 실행은 가능한 한 따라잡고,
    # 배터리 상태로 중단되지 않게 한다. (매일 도는 배치라 실행 시간 제한도 넉넉히)
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
                   -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
                   -ExecutionTimeLimit (New-TimeSpan -Hours 4)

    if ($RunWhetherLoggedOn) {
        $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Password
        Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger `
            -Settings $settings -Principal $principal -Description $t.Desc -Force | Out-Null
    } else {
        $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
        Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger `
            -Settings $settings -Principal $principal -Description $t.Desc -Force | Out-Null
    }
    Write-Host ("  등록: {0}" -f $t.Name)
}

# --- 등록 결과를 **다시 조회해서** 확인한다 ("등록했다"가 아니라 "등록됐다") ------
Write-Host ''
Write-Host '확인 (다시 조회)'
$ok = $true
foreach ($t in $Tasks) {
    $q = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
    if ($q) {
        $next = (Get-ScheduledTaskInfo -TaskName $t.Name).NextRunTime
        Write-Host ("  OK  {0,-28} 다음 실행 {1}" -f $t.Name, $next)
    } else {
        Write-Host ("  ★   {0,-28} 조회되지 않는다" -f $t.Name)
        $ok = $false
    }
}

Write-Host ''
if ($ok) {
    Write-Host '등록 완료. 첫 실행 뒤 아래 로그로 결과를 확인할 것:'
    Write-Host '    logs\daily_run.log   (사건 수집 + migrate)'
    Write-Host '    logs\doc_run.log     (문서 수집 / 우선순위)'
    Write-Host '  각 로그 끝에 [SUCCESS] 또는 [FAILED] 마커가 남는다.'
    exit 0
}
Write-Host '★ 일부 작업이 등록되지 않았다. 위 출력을 확인할 것.'
exit 1
