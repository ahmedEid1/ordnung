import { OnboardingWizard } from "@/features/onboarding/OnboardingWizard";

/** First-run setup (`/welcome`, outside the app shell). The wizard names each step in the tab title. */
export default function WelcomePage() {
  return <OnboardingWizard />;
}
