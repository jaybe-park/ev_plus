# GTO 데이터 입력 가이드

## 파일 위치
```
gto_data/preflop/
  open/          ← 첫 오픈 레이즈 레인지
    BTN.json
    CO.json
    MP.json
    UTG.json
    SB.json
  vs_open/       ← 오픈에 대한 수비/3벳 레인지
    BB_vs_BTN.json
    BB_vs_CO.json
    SB_vs_BTN.json
    ...
  vs_3bet/       ← 3벳에 대한 4벳/콜/폴드 레인지
    BTN_vs_BB.json
    ...
```

## JSON 형식

### open/ 파일 (fold / raise 두 가지 액션)
```json
{
  "situation": "BTN open RFI",
  "actions": ["fold", "raise"],
  "raise_size": "2.5bb",
  "hands": {
    "AA":  {"fold": 0.0, "raise": 1.0},
    "AKs": {"fold": 0.0, "raise": 1.0},
    "AKo": {"fold": 0.0, "raise": 1.0},
    "JTo": {"fold": 0.15, "raise": 0.85},
    "72o": {"fold": 1.0,  "raise": 0.0}
  }
}
```

### vs_open/ 파일 (fold / call / raise 세 가지 액션)
```json
{
  "situation": "BB vs BTN open",
  "actions": ["fold", "call", "raise"],
  "raise_size": "3x",
  "hands": {
    "AA":  {"fold": 0.0, "call": 0.0,  "raise": 1.0},
    "AKs": {"fold": 0.0, "call": 0.33, "raise": 0.67},
    "72o": {"fold": 1.0, "call": 0.0,  "raise": 0.0}
  }
}
```

## 핸드 표기 규칙
- 수트 있음(suited):   `AKs`, `T9s`, `54s`
- 수트 없음(offsuit):  `AKo`, `T9o`, `54o`
- 페어:                `AA`, `KK`, `22`
- 모든 169개 핸드 조합 입력 (미입력 시 fold 100% 처리)

## GTO Wizard에서 복사하는 방법
1. 상황 선택 (예: BTN RFI)
2. 레인지 차트에서 각 핸드의 액션 빈도 확인
3. 아래 형식으로 hands 딕셔너리에 입력
4. 빈도 합계가 1.0이 되어야 함 (fold + call + raise = 1.0)

## 단축 입력: 레인지 문자열
전체 핸드를 일일이 입력하기 번거로우면 tools/range_parser.py를 사용:
  python tools/range_parser.py "AA,KK,QQ,AKs,AKo:0.5"
  → JSON 자동 생성
