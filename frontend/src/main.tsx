import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { ApiError } from "./api/client";
import { keys } from "./api/hooks";
import { App } from "./App";
import "./index.css";

// сессия истекла → сбрасываем «me», RequireAuth уведёт на /login
const onError = (error: Error) => {
  if (error instanceof ApiError && error.status === 401) queryClient.setQueryData(keys.me, null);
};

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError }),
  mutationCache: new MutationCache({ onError }),
  defaultOptions: {
    queries: {
      staleTime: 30_000, // свежесть поддерживает WebSocket, частые перезапросы не нужны
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
