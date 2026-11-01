import { useQuery } from "@tanstack/react-query";
import { getMe } from "./api/client";

/**
 * Placeholder shell. Real routing (Dashboard, Applications, ApplicationDetail,
 * Analytics, Settings, Onboarding) is built in tasks 14-16.
 */
export function App() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["me"],
    queryFn: getMe,
    retry: false,
  });

  return (
    <main style={{ fontFamily: "system-ui", padding: "2rem" }}>
      <h1>Job Application Tracker</h1>
      {isLoading && <p>Loading…</p>}
      {isError && <p>Not signed in. Connect your Outlook to get started.</p>}
      {data && <p>Signed in as {data.email}</p>}
    </main>
  );
}
