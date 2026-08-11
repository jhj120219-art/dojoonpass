"""한 번의 수집 실행이 실제로 무엇을 이뤘는지 담는 값 객체.

2026-08-11 Sprint 55 신설 (BUGS #47).

왜 `mvp_scraper.py`가 아니라 여기인가 — `mvp_scraper.py`는 import 한 줄만으로
`crawler.court_crawler` -> `selenium`을 끌어온다. 성패 판정 로직을 거기 두면
**selenium이 설치된 환경에서만 테스트할 수 있고**, 지금 이 저장소가 바로 그렇지 않다.
판정은 순수 산술이므로 의존성 없는 곳으로 분리해 테스트 가능하게 만든다.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CrawlOutcome:
    courts: int = 0                          # 시도한 법원 수
    skipped: List[str] = field(default_factory=list)  # 기일이 없어 건너뛴 법원 (정상)
    failed: List[str] = field(default_factory=list)   # 예외로 실패한 법원
    collected: int = 0                       # 크롤로 얻은 사건 수
    inserted: int = 0                        # DB 신규
    updated: int = 0                         # DB 갱신
    upsert_failed: int = 0                   # DB 저장 실패

    @property
    def persisted(self) -> int:
        """실제로 DB에 남은 건수. 0이면 그 실행은 아무것도 이루지 못한 것이다."""
        return self.inserted + self.updated

    def failure_reason(self) -> Optional[str]:
        """치명적 실패면 사유 문자열, 아니면 None.

        '치명적'의 기준은 새 정책을 만든 것이 아니라 **명백한 것만** 잡는다.
        수집이 0건이거나 DB에 한 건도 남지 않았다면 그 실행은 목적을 달성하지 못했다.

        법원 몇 곳이 실패한 정도(부분 실패)는 사이트 사정으로 흔히 일어나므로
        경고만 남기고 성공으로 둔다 — 임계값을 임의로 정하면 그 자체가 새 정책이 되고,
        멀쩡한 실행이 매일 실패로 보고되면 경보가 무시당해 결국 같은 곳으로 돌아간다.

        2026-08-02 실측 사례가 정확히 여기 걸린다:
            법원 60곳 / 오류 59곳 / 스킵 1곳 / 저장 0건  ->  "수집 건수 0건"
        그때는 이 판정이 없어서 배치가 성공으로 끝났다.
        """
        if self.courts and len(self.failed) == self.courts:
            return "전 법원(%d곳) 수집 실패" % self.courts
        if self.collected == 0:
            return "수집 건수 0건 (오류 %d곳 / 스킵 %d곳)" % (len(self.failed), len(self.skipped))
        if self.persisted == 0:
            return "DB 저장 0건 (수집 %d건, 저장 실패 %d건)" % (self.collected, self.upsert_failed)
        return None

    def exit_code(self) -> int:
        """배치가 읽을 종료 코드. 0=성공, 1=치명적 실패."""
        return 1 if self.failure_reason() else 0


@dataclass
class DocWorkerOutcome:
    """PDF 수집 Worker 한 번의 실행 결과.

    `doc_worker.py`도 `crawler.doc_crawler` -> `selenium`을 import하므로 판정만 여기로
    분리한다(`CrawlOutcome`과 같은 이유).
    """

    processed: int = 0   # 실제로 수집을 시도한 큐 항목 수
    succeeded: int = 0   # 그중 성공한 수

    def failure_reason(self) -> Optional[str]:
        """큐가 비어 아무것도 시도하지 않은 것(processed==0)은 정상이다 — 매일 도는
        워커이므로 할 일이 없는 날이 있다.

        시도했는데 **한 건도 성공하지 못한 것**은 다르다. 드라이버/사이트/선택자 중 하나가
        통째로 깨졌다는 신호이고, 조용히 지나가면 큐만 계속 쌓인다
        (2026-08-11 실측: pending 2,703건 / doc_raw 0행).
        """
        if self.processed > 0 and self.succeeded == 0:
            return "PDF 수집 %d건 시도, 성공 0건" % self.processed
        return None

    def exit_code(self) -> int:
        return 1 if self.failure_reason() else 0
