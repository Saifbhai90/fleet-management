import { memo } from "react";

/** Fleet-branded start orb — replace markup or swap for `public/fleet-brand/start-button.svg` if you add a custom logo asset. */
const StartButtonIcon = memo(() => (
  <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <rect height="9" opacity="0.95" rx="1.5" width="9" x="2" y="2" />
    <rect height="9" opacity="0.75" rx="1.5" width="9" x="13" y="2" />
    <rect height="9" opacity="0.75" rx="1.5" width="9" x="2" y="13" />
    <rect height="9" opacity="0.55" rx="1.5" width="9" x="13" y="13" />
  </svg>
));

export default StartButtonIcon;
