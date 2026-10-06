import { describe, expect, it } from "vitest";
import { ApiError, qs } from "./api";
import { errText, fmtNum } from "./i18n";

describe("api helpers", () => {
  it("builds query strings without empty values", () => {
    expect(qs({ a: 1, b: "", c: null, d: "x y" })).toBe("?a=1&d=x%20y");
  });
  it("parses error details from API", () => {
    const e = new ApiError(400, { code: "errors.no_permit", params: { person: "Иванов" } });
    expect(e.code).toBe("errors.no_permit");
    expect(errText(e)).toContain("errors.no_permit");
    expect(new ApiError(404, "errors.not_found").code).toBe("errors.not_found");
  });
  it("formats numbers", () => {
    expect(fmtNum(null)).toBe("—");
    expect(fmtNum(2.345, 2)).toMatch(/2[.,]3[45]/);
  });
});
