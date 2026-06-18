import { apiGet } from "./api";

export interface GreetingResponse {
  message: string;
}

export const getGreeting = (signal?: AbortSignal) =>
  apiGet<GreetingResponse>("/api/greetings", { signal });
