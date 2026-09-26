---
name: update-docs
description: 변경 사항을 반영해 ev_plus의 현재 상태 문서(docs/spec, 이관 전 도메인은 기존 docs)·ADR·TODO·DECISIONS를 최신화한다. 커밋 전 문서 정리, "문서 업데이트해줘", "md 최신화" 요청 시 사용.
---

# 문서 최신화 (ev_plus)

문서 구조는 `docs/ai-dev-workflow-playbook.md` §3을 따른다. **뒤처진 정보가 남는 것이
문서가 없는 것보다 나쁘다**는 원칙으로 작업한다.

## 문서 층 (섞지 않는다)

| 층 | 위치 | 갱신 방식 |
|---|---|---|
| 현재 상태 | `docs/spec/<domain>.md` (이관 전 도메인은 `CLAUDE.md` 문서 지도의 기존 문서) | **덮어쓴다.** "(정정)"·과거 서술 금지 |
| 결정 | `docs/decisions/NNNN-*.md` + `README.md` 목록 | 고치지 않는다. 뒤집히면 새 ADR + 옛 ADR 상태만 `대체됨 → NNNN` |
| 결정 대기 | `DECISIONS.md` | 결정되면 항목 삭제 + ADR 작성 |
| 할 일 | `TODO.md` | 완료 Task는 **삭제**(archive로 옮기지 않는다) |
| 이력 | git log | 커밋 메시지에 무엇을·왜 |

## 절차

1. **범위 파악** — `git status --short`, `git diff --stat`, `git log --oneline -15`,
   대화에서 결정된 사항 중 문서에 없는 것.
2. **문서 지도 기준** — `CLAUDE.md` 문서 지도에 있는 문서만 대상. 지도에 없는 md를
   발견하면 지도에 추가할지(현재 상태 문서라면) 사람에게 묻는다.
3. **대조 검토** (문서별)
   - 낡은 사실: 포트·경로·명령·테이블·개수 등 구체적 수치를 코드로 확인
   - 누락: 새 기능/파일/스크립트
   - 깨진 참조: 삭제된 파일·명령을 가리키는 링크
   - spec 규칙마다 강제 장치(테스트 이름)가 실제로 존재하는가 — 없으면 "장치 없음"
4. **갱신**
   - 확인한 값만 기록(추측 금지)
   - 완료 Task는 TODO에서 삭제. 남길 판단이 있으면 ADR로 승격
   - 결정이 필요한 것은 고치지 말고 `DECISIONS.md`에 등록
   - `docs/gto-preflop-progress.md`는 수동 편집 금지 — `python3 scripts/gto_tree_report.py`로만
5. **보고** — 문서별 한 줄 요약 + 판단이 필요해 건드리지 않은 것

## 주의

- `memo.md`는 사람의 입력함 — 지시가 있을 때만 처리 후 비운다.
- 커밋 지시가 없으면 커밋하지 않는다.
- `self-reviews/`는 관찰 기록이라 고치지 않는다.
