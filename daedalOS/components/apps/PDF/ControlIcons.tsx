import { memo } from "react";

export const Add = memo(() => (
  <svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">
    <path d="M32 15v2H17v15h-2V17H0v-2h15V0h2v15h15z" />
  </svg>
));

export const Subtract = memo(() => (
  <svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">
    <path d="M32 17H0v-2h32v2z" />
  </svg>
));

export const Download = memo(() => (
  <svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">
    <path d="M6 32v-2h18v2H6zm18.703-15.297L15 26.484l-9.703-9.781 1.406-1.406L14 22.641V0h2v22.641l7.297-7.344z" />
  </svg>
));

export const Print = memo(() => (
  <svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">
    <path d="M30 12q0.406 0 0.773 0.156t0.641 0.43 0.43 0.641 0.156 0.773v14h-8v4h-16v-4h-8v-14q0-0.406 0.156-0.773t0.43-0.641 0.641-0.43 0.773-0.156h6v-12h16v12h6zM10 12h12v-10h-12v10zM22 22h-12v8h12v-8zM30 14h-28v12h6v-6h16v6h6v-12zM5 16q0.406 0 0.703 0.297t0.297 0.703-0.297 0.703-0.703 0.297-0.703-0.297-0.297-0.703 0.297-0.703 0.703-0.297z" />
  </svg>
));

export const Crop = memo(() => (
  <svg fill="none" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M4 9h2V7a2 2 0 012-2h2V3H8a4 4 0 00-4 4v2zm0 6v2a4 4 0 004 4h2v-2H8a2 2 0 01-2-2v-2H4zm16-6h2V9a4 4 0 00-4-4h-2v2h2a2 2 0 012 2v2zm0 6v2a2 2 0 01-2 2h-2v2h2a4 4 0 004-4v-2h-2zM10 10h4v4h-4v-4z"
      fill="currentColor"
    />
  </svg>
));

export const Enhance = memo(() => (
  <svg fill="none" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M7 4l1.6 4.2L13 10l-4.4 1.8L7 16l-1.6-4.2L1 10l4.4-1.8L7 4zm10 8l.9 2.2L20 15l-2.1.8L17 18l-.9-2.2L14 15l2.1-.8L17 12z"
      fill="currentColor"
    />
  </svg>
));

export const Pencil = memo(() => (
  <svg fill="none" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M4 17.5V21h3.5L17.8 10.7l-3.5-3.5L4 17.5zm14.7-9.2c.4-.4.4-1 0-1.4l-2.1-2.1c-.4-.4-1-.4-1.4 0l-1.6 1.6 3.5 3.5 1.6-1.6z"
      fill="currentColor"
    />
  </svg>
));

export const More = memo(() => (
  <svg fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <circle cx="5" cy="12" r="2.25" />
    <circle cx="12" cy="12" r="2.25" />
    <circle cx="19" cy="12" r="2.25" />
  </svg>
));

export const SaveDisk = memo(() => (
  <svg fill="none" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M17 3H7a2 2 0 00-2 2v14l7-3 7 3V5a2 2 0 00-2-2zm0 12l-5-2.2L7 15V5h10v10z"
      fill="currentColor"
    />
  </svg>
));

export const RotateCw = memo(() => (
  <svg fill="none" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M12 6V3L8 7l4 4V8c2.76 0 5 2.24 5 5 0 1.57-.73 2.97-1.86 3.89l1.43 1.43C18.52 16.23 19 14.17 19 12c0-3.87-3.13-7-7-7zm-7.07 3.07L3.5 8.5C2.48 9.63 2 11.05 2 12.5c0 3.87 3.13 7 7 7v3l4-4-4-4v3c-2.76 0-5-2.24-5-5 0-1.06.33-2.04.93-2.93z"
      fill="currentColor"
    />
  </svg>
));

export const Hand = memo(() => (
  <svg fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <path d="M13 3c-1.1 0-2 .9-2 2v5.5l-.8-.8c-.9-.9-2.5-.3-2.5 1v7c0 2.2 1.8 4 4 4h3c2.2 0 4-1.8 4-4v-6c0-1.2-.8-2.2-2-2.5V5c0-1.1-.9-2-2-2zm0 2h2v7h1c.6 0 1 .4 1 1v6c0 1.1-.9 2-2 2h-3c-1.1 0-2-.9-2-2v-7c0-.4.5-.6.8-.3l2.2 2.2V5c0-.6-.4-1-1-1zM8 9c-.6 0-1 .4-1 1v6c0 .7.2 1.4.5 2H7c-1.1 0-2-.9-2-2v-4c0-.9.7-1.6 1.6-1.6.4 0 .8.2 1.1.5l.3.3V10c0-.6-.4-1-1-1z" />
  </svg>
));

export const Undo = memo(() => (
  <svg fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <path d="M12.5 8c-2.65 0-5.06.99-6.9 2.6L2 7v9h9l-3.62-3.62c1.39-1.16 3.16-1.88 5.12-1.88 3.54 0 6.55 2.31 7.6 5.5l2.37-.78C21.08 11.03 17.15 8 12.5 8z" />
  </svg>
));
