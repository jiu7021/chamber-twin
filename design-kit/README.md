# SnowUI Shell — 포트폴리오용 재사용 디자인 키트

claude.ai/design 의 **SnowUI Design System** 토큰을 그대로 옮긴 스타일시트다.
다른 프로젝트에 파일 세 개만 복사하면 같은 화면이 나온다.

| 파일 | 내용 |
|---|---|
| `snowui-shell.css` | 토큰(다크/라이트) + 사이드바 셸 + 콘텐츠 컴포넌트 |
| `snowui-shell.js` | 스크롤 스파이(현재 위치 표시) + 테마 토글 |
| `starter.html` | 골격. 복사해서 내용만 채우면 된다 |

## 쓰는 법

1. 세 파일을 프로젝트의 정적 폴더(예: `docs/`)에 복사한다.
2. `starter.html` 을 `index.html` 로 이름 바꾸고 내용을 채운다.
3. 레일의 `href="#s-…"` 와 섹션의 `id="s-…"` 만 맞추면 스크롤 연동은 자동이다.

`<html>` 에 `data-theme="dark"` 가 있어야 다크로 시작한다. Inter 는 한글 글리프가
없으므로 Noto Sans KR 링크를 반드시 같이 넣는다 (starter.html 에 이미 있다).

## 클래스 목록

**셸** `shell` `rail` `rail-brand` `rail-dot` `rail-sec` `rail-group` `rail-row` `ri`
`rail-ext` `rail-foot` `col` `topbar` `crumb` `topbar-r` `icon-btn` `scroll` `hero` `sub` `ftr`

**콘텐츠** `panel` `panel-head` `hint` `para` `fig` `badge`(`.ghost` `.bad`) `btn`(`.primary`)
`inline-link` `dim`

**KPI** `kpi-row` `kpi`(`.tint` `.tint-2`) `kpi-lab` `kpi-val` `kpi-sub`

**서사** `steps` `step`(`.ok` `.half` `.no`) `step-n` `turn` `cmp` `kv` `limits`

`step` 의 `.ok / .half / .no` 는 좌측 막대 색으로 가설의 결과를 표시한다.
기각된 가설을 숨기지 말고 붉은 막대로 드러내는 쪽이 낫다.

## 지켜야 할 것 — SnowUI 예시와 대조해 확정한 값

- **패널에 테두리를 두르지 않는다.** 배경색 차이와 여백으로 나눈다.
- 섹션 간격 **28**, 패널 패딩 **24**, 패널 radius **20**, 카드 radius **16**.
- KPI 라벨은 **14px semibold**, 값은 **24px semibold**.
- 다크에서도 `.kpi.tint` 는 파스텔 밝은 면을 유지하고 글자만 어둡게 뒤집는다.

이 값들을 줄이면 촘촘하고 답답해진다. 처음 만들 때 그렇게 했다가 고쳤다.

## 원본을 다시 읽어야 할 때

`DesignSync` 도구로 claude.ai/design 프로젝트를 읽는다. 인증은 기기에 한 번만 하면 된다
(대화형 터미널에서 `claude` 실행 후 `/design-login`).

    tokens/colors.css · typography.css · shape.css · fonts.css
    ui_kits/dashboard/{Shell,NavRail,OverviewScreen}.jsx
    guidelines/*.card.html
