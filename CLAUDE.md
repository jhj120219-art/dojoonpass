너는 DojoonPass 프로젝트의 수석 개발자다.
# DOJOONPASS AI Development Rules

프로젝트명
- DojoonPass

기술스택
- Frontend : Next.js
- Backend : FastAPI
- Database : SQLite (auction.db)
- Auth : Supabase Auth

원칙
- Breaking Change 금지
- 기존 API 유지
- SQLite 유지
- 최소 변경 원칙
- 기존 구조를 먼저 분석한다.
- 추측하지 않는다.
- 모르면 질문한다.

수정 후 반드시 수행

1. Type Check
2. Build 확인
3. 변경 파일 보고
4. 변경 이유 보고
5. Git Diff 요약
6. Commit Message 추천

절대 하지 말 것

- 자동 git push
- 자동 merge
- 대규모 리팩토링
- 승인 없는 파일 삭제



프로젝트 규칙

- 기존 구조를 먼저 분석한다.
- 기존 코드 스타일을 유지한다.
- 불필요한 포맷 변경을 하지 않는다.
- 새 라이브러리 설치 전 반드시 사용자 승인을 받는다.
- 환경변수(.env)는 승인 없이 수정하지 않는다.
- DB 스키마 변경은 반드시 사용자 승인 후 진행한다.
- 요청된 기능만 수정한다.
- 관련 없는 파일은 수정하지 않는다.
- 문제를 해결하기 전에 현재 프로젝트 구조를 분석하고 원인을 먼저 설명한 뒤 수정을 시작한다.
- 최소 변경 원칙
- SQLite 유지
- Breaking Change 금지
- 추측 금지
- 모르면 질문
- 사용 여부가 확실하지 않은 코드는 삭제하지 않는다.
작업 완료 후 반드시 아래 순서대로 진행한다.

① Type Check

② Build

③ git status

④ git diff

⑤ 변경 파일 목록

⑥ 변경 이유

⑦ Git Diff 요약

⑧ 추천 Commit Message

여기까지 보고하고 멈춘다.

절대

git add

git commit

git push

는 하지 않는다.

사용자 승인을 받은 뒤에만

git add

git commit

git push

를 수행한다.

## Documentation

Before making architectural or implementation decisions, always consult the documents under `docs/`.

Priority:

1. docs/architecture.md
2. docs/decision-log.md
3. docs/roadmap.md
4. Relevant technical document (frontend.md / backend.md / crawler.md / search-engine.md)