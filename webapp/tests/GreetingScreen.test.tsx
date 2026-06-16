import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe, toHaveNoViolations } from "jest-axe";
import GreetingScreen from "../src/components/GreetingScreen";

expect.extend(toHaveNoViolations);

describe("GreetingScreen", () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  it("renders loading state initially", () => {
    global.fetch = jest.fn(() => new Promise(() => {})) as jest.Mock;
    render(<GreetingScreen />);
    expect(screen.getByText("Loading...")).toBeTruthy();
  });

  it("renders greeting message on fetch success", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ message: "Hello, RETICLE!" }),
    }) as jest.Mock;

    render(<GreetingScreen />);

    await waitFor(() => {
      expect(screen.getByText("Hello, RETICLE!")).toBeTruthy();
    });
  });

  it("renders error message and retry button on fetch failure", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => null,
    }) as jest.Mock;

    render(<GreetingScreen />);

    await waitFor(() => {
      expect(screen.getByText("Retry")).toBeTruthy();
    });
  });

  it("retries fetch when retry button is clicked", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => null,
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ message: "Hello after retry!" }),
      });
    global.fetch = fetchMock as jest.Mock;

    const user = userEvent.setup();
    render(<GreetingScreen />);

    await waitFor(() => {
      expect(screen.getByText("Retry")).toBeTruthy();
    });

    await user.click(screen.getByText("Retry"));

    await waitFor(() => {
      expect(screen.getByText("Hello after retry!")).toBeTruthy();
    });
  });

  it("has no accessibility violations in success state", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ message: "Hello!" }),
    }) as jest.Mock;

    const { container } = render(<GreetingScreen />);

    await waitFor(() => {
      expect(screen.getByText("Hello!")).toBeTruthy();
    });

    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
