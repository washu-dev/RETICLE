import React from "react";
import { render, screen } from "@testing-library/react";
import Header from "../src/components/Header";

describe("Header", () => {
  it("renders RETICLE title", () => {
    render(<Header />);
    expect(screen.getByText("RETICLE")).toBeTruthy();
  });

  it("has banner accessibility role", () => {
    render(<Header />);
    expect(screen.getByRole("banner")).toBeTruthy();
  });
});
