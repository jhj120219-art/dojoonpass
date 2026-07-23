Source Registry
이 AI가 어떤 데이터를 얼마나 신뢰하고 어떻게 사용할 것인가를 정의하는 문서입니다.

| Category | Source             | Purpose | Update | Priority | Trust | Output     | Owner        |
| -------- | ------------------ | ------- | ------ | -------- | ----- | ---------- | ------------ |
| 법원       | courtauction.go.kr | 경매물건    | 1h     | S        | ★★★★★ | Auction DB | Crawler      |
| 공공       | 온비드                | 공매      | 3h     | A        | ★★★★★ | Auction DB | Crawler      |
| 뉴스       | 매일경제               | 시장뉴스    | 30m    | A        | ★★★★☆ | News DB    | Crawler      |
| Trend    | Google Trends      | 검색량     | 1h     | S        | ★★★★★ | Trend DB   | Trend Hunter |


Rule

Priority S

↓

항상 수집

Priority A

↓

가능하면 수집

Priority B

↓

리소스 여유 시 수집