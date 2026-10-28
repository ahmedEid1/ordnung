import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PersonTag } from "./PersonTag";

describe("PersonTag", () => {
  it("says whose letter it is, with the whole name in its title for when it is cut", () => {
    render(<PersonTag name="Alexandra Maria Rivera-Hernández" />);
    const tag = screen.getByText("For Alexandra Maria Rivera-Hernández").closest("[data-person-tag]");
    expect(tag).not.toBeNull();
    expect(tag!.getAttribute("title")).toBe("For Alexandra Maria Rivera-Hernández");
    expect(tag!.querySelector("svg[aria-hidden]")).not.toBeNull();
  });
});
