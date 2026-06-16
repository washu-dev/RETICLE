import { renderHook, waitFor } from "@testing-library/react";
import { useGreeting } from "../src/hooks/useGreeting";
import * as greetings from "../src/services/greetings";

jest.mock("../src/services/greetings");

const mockGetGreeting = greetings.getGreeting as jest.MockedFunction<
  typeof greetings.getGreeting
>;

describe("useGreeting", () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  it("starts in loading state", () => {
    mockGetGreeting.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useGreeting());
    expect(result.current.status).toBe("loading");
  });

  it("transitions to success state with message", async () => {
    mockGetGreeting.mockResolvedValue({ message: "Hello!" });
    const { result } = renderHook(() => useGreeting());

    await waitFor(() => {
      expect(result.current.status).toBe("success");
    });

    expect(result.current.message).toBe("Hello!");
    expect(result.current.error).toBeNull();
  });

  it("transitions to error state on failure", async () => {
    mockGetGreeting.mockRejectedValue(new Error("Network error"));
    const { result } = renderHook(() => useGreeting());

    await waitFor(() => {
      expect(result.current.status).toBe("error");
    });

    expect(result.current.error).toBe("Network error");
    expect(result.current.message).toBeNull();
  });

  it("retries fetch when retry is called", async () => {
    mockGetGreeting
      .mockRejectedValueOnce(new Error("First failure"))
      .mockResolvedValueOnce({ message: "Retry succeeded!" });

    const { result } = renderHook(() => useGreeting());

    await waitFor(() => {
      expect(result.current.status).toBe("error");
    });

    result.current.retry();

    await waitFor(() => {
      expect(result.current.status).toBe("success");
    });

    expect(result.current.message).toBe("Retry succeeded!");
  });
});
