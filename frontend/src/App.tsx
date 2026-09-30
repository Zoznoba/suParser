import { BrowserRouter, Route, Routes } from "react-router";

import { Layout } from "./components/Layout";
import { RequireAuth } from "./components/RequireAuth";
import { CandidatePage } from "./pages/CandidatePage";
import { FeedPage } from "./pages/FeedPage";
import { LoginPage } from "./pages/LoginPage";
import { ProfilesPage } from "./pages/ProfilesPage";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<FeedPage />} />
          <Route path="candidates/:id" element={<CandidatePage />} />
          <Route path="profiles" element={<ProfilesPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
