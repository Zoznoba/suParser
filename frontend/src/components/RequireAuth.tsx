import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { useMe } from "../api/hooks";
import { Spinner } from "./ui";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { data, isPending } = useMe();
  const location = useLocation();
  if (isPending) return <Spinner />;
  if (!data) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return children;
}
