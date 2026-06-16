import React from "react";
import { render, screen } from "@testing-library/react";
import App from "../src/App";

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ message: "Hello from RETICLE" }),
  } as unknown as Response);
});

afterEach(() => {
  jest.resetAllMocks();
});

describe("App", () => {
  it("renders without crashing", () => {
    render(<App />);
  });

  it("contains the Header with RETICLE title", () => {
    render(<App />);
    expect(screen.getByText("RETICLE")).toBeTruthy();
  });

  it("contains the Footer copyright text", () => {
    render(<App />);
    expect(
      screen.getByText(/Washington University in St\. Louis/i)
    ).toBeTruthy();
  });
});
