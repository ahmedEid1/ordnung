import { useState } from "react";
import { RouterProvider } from "react-router/dom";
import { AppProviders } from "@/app/providers";
import { AppErrorBoundary } from "@/app/ErrorBoundary";
import { createAppRouter } from "@/app/router";

export default function App() {
  const [router] = useState(createAppRouter);
  return (
    <AppErrorBoundary>
      <AppProviders>
        <RouterProvider router={router} />
      </AppProviders>
    </AppErrorBoundary>
  );
}
