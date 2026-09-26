import { useEffect } from "react";
import { OnboardingWizard } from "@/features/onboarding/OnboardingWizard";

/** First-run setup (`/welcome`, outside the app shell). */
export default function WelcomePage() {
  useEffect(() => {
    document.title = "Welcome · Ordnung";
  }, []);
  return <OnboardingWizard />;
}
