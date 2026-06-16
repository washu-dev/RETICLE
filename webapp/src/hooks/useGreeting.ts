import { useState, useEffect, useCallback } from "react";
import { getGreeting } from "../services/greetings";

type Status = "idle" | "loading" | "success" | "error";

interface UseGreetingResult {
  status: Status;
  message: string | null;
  error: string | null;
  retry: () => void;
}

export function useGreeting(): UseGreetingResult {
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    setError(null);

    getGreeting(controller.signal)
      .then((data) => {
        setMessage(data.message);
        setStatus("success");
      })
      .catch((err: unknown) => {
        if (err instanceof Error && err.name === "AbortError") return;
        setError(err instanceof Error ? err.message : "Unknown error");
        setStatus("error");
      });

    return () => {
      controller.abort();
    };
  }, [attempt]);

  const retry = useCallback(() => {
    setAttempt((n) => n + 1);
  }, []);

  return { status, message, error, retry };
}
