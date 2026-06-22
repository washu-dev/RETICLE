import { render, screen } from "@testing-library/react";
import App from "../src/App";

describe("App", () => {
  it("renders without crashing", () => {
    render(<App />);
  });

  it("shows RETICLE branding on the landing page", () => {
    render(<App />);
    expect(screen.getAllByText("RETICLE").length).toBeGreaterThan(0);
  });

  it("shows the upload gene list call-to-action", () => {
    render(<App />);
    expect(screen.getByText("Upload gene list")).toBeTruthy();
  });
});
