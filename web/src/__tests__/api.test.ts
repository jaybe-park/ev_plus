import { describe, it, expect } from "vitest";
import { formatApiError } from "../api";

describe("formatApiError — FastAPI 422 detail 평탄화 (T-031)", () => {
  it("문자열 detail은 그대로 통과시킨다", () => {
    expect(formatApiError("세션을 찾을 수 없습니다.")).toBe("세션을 찾을 수 없습니다.");
  });

  it("Pydantic 검증 오류 배열을 사람이 읽는 문장으로 합친다", () => {
    const detail = [
      { loc: ["body", "chips"], msg: "Input should be greater than 0", type: "greater_than" },
      { loc: ["body", "num_bots"], msg: "Input should be less than or equal to 5", type: "less_than_equal" },
    ];
    const msg = formatApiError(detail);
    expect(msg).not.toBe("[object Object]");
    expect(msg).toContain("chips: Input should be greater than 0");
    expect(msg).toContain("num_bots: Input should be less than or equal to 5");
    expect(msg).toBe(
      "chips: Input should be greater than 0 / num_bots: Input should be less than or equal to 5"
    );
  });

  it("loc의 선행 'body' 토큰은 필드 경로에서 제외한다", () => {
    const msg = formatApiError([{ loc: ["body", "chips"], msg: "실패" }]);
    expect(msg).toBe("chips: 실패");
  });

  it("모델 단위 검증 오류(loc=['body'])는 필드 접두사 없이 안내만 낸다 (T-027)", () => {
    const msg = formatApiError([
      { loc: ["body"], msg: "시작 칩은 빅 블라인드의 10배(100) 이상이어야 합니다.", type: "chips_shallow" },
    ]);
    expect(msg).toBe("시작 칩은 빅 블라인드의 10배(100) 이상이어야 합니다.");
  });

  it("detail이 비었거나 알 수 없는 형태면 기본 문구를 낸다", () => {
    expect(formatApiError(undefined)).toBe("요청을 처리할 수 없습니다.");
    expect(formatApiError([])).toBe("요청을 처리할 수 없습니다.");
  });
});
