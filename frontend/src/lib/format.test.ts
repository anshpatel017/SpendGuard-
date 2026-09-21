import { describe, expect, it } from "vitest";

import { formatDate, formatMoney, formatMoneyShort, groupIndian } from "./format";

describe("money", () => {
  it.each([
    ["0.00", "₹0.00"],
    ["999.5", "₹999.50"],
    ["1000", "₹1,000.00"],
    ["360000.00", "₹3,60,000.00"],
    ["1234567.5", "₹12,34,567.50"],
    ["12345678.90", "₹1,23,45,678.90"],
    ["97698491.83", "₹9,76,98,491.83"],
    ["-2500.5", "-₹2,500.50"],
    ["-0.00", "₹0.00"],
  ])("formats %s with Indian grouping as %s", (input, expected) => {
    expect(formatMoney(input)).toBe(expected);
  });

  it("never rounds through a float", () => {
    // As a float this is 9007199254740992; formatting the string keeps every digit.
    expect(formatMoney("9007199254740993.07")).toBe("₹9,00,71,99,25,47,40,993.07");
  });

  it("shows a dash for missing money rather than zero", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(undefined)).toBe("—");
  });

  it("reads large amounts in lakh and crore", () => {
    expect(formatMoneyShort("97698491.83")).toBe("₹9.77 crore");
    expect(formatMoneyShort("360000")).toBe("₹3.60 lakh");
    expect(formatMoneyShort("87450")).toBe("₹87,450.00");
  });

  it("groups plain digits the Indian way", () => {
    expect(groupIndian("50907")).toBe("50,907");
    expect(groupIndian("123")).toBe("123");
  });
});

describe("dates", () => {
  it("formats a date-only string without a timezone shift", () => {
    expect(formatDate("2024-08-21")).toBe("21 Aug 2024");
    expect(formatDate("2026-01-01")).toBe("01 Jan 2026");
  });
});
