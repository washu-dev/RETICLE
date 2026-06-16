import React from "react";
import { render, screen } from "@testing-library/react";
import Footer from "../src/components/Footer";

describe("Footer", () => {
  it("renders copyright text", () => {
    render(<Footer />);
    expect(
      screen.getByText(/Washington University in St\. Louis/i)
    ).toBeTruthy();
  });

  it("has contentinfo accessibility role", () => {
    render(<Footer />);
    expect(screen.getByRole("contentinfo")).toBeTruthy();
  });
});
