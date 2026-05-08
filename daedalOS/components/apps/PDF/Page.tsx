import {
  useRef,
  useEffect,
  memo,
  useCallback,
  type FC,
} from "react";
import { useProcesses } from "contexts/process";

type PageProps = {
  canvas: HTMLCanvasElement;
  id: string;
  overlayRegister: (
    pageIndex: number,
    element: HTMLCanvasElement | null
  ) => void;
  page: number;
};

const Page: FC<PageProps> = ({
  canvas,
  id,
  overlayRegister,
  page,
}) => {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasMountRef = useRef<HTMLDivElement | null>(null);
  const overlayRef = useRef<HTMLCanvasElement | null>(null);
  const {
    argument,
    processes: { [id]: process },
  } = useProcesses();
  const {
    componentWindow,
    pdfEditMode = false,
    pdfScrollRoot,
    pdfTool = "pen",
  } = process || {};

  const pageIndex = page - 1;

  const setOverlayRef = useCallback(
    (element: HTMLCanvasElement | null) => {
      overlayRef.current = element;
      overlayRegister(pageIndex, element);
    },
    [overlayRegister, pageIndex]
  );

  useEffect(() => {
    const mount = canvasMountRef.current;

    if (mount) mount.replaceChildren(canvas);

    return () => {
      canvas.remove();
    };
  }, [canvas]);

  useEffect(() => {
    let cleanup: (() => void) | undefined;

    const overlay = overlayRef.current;
    const ctx = overlay?.getContext("2d");

    if (overlay && ctx && pdfEditMode) {
      ctx.strokeStyle = "#111827";
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.font = "16px system-ui, sans-serif";
    ctx.fillStyle = "#111827";

    let drawing = false;

    const getOffsets = (
      event: PointerEvent
    ): { offsetX: number; offsetY: number } => {
      const rect = overlay.getBoundingClientRect();

      return {
        offsetX: event.clientX - rect.left,
        offsetY: event.clientY - rect.top,
      };
    };

    const onPointerDown = (event: PointerEvent): void => {
      if (pdfTool !== "pen") return;

      overlay.setPointerCapture(event.pointerId);
      drawing = true;
      const { offsetX, offsetY } = getOffsets(event);

      ctx.beginPath();
      ctx.moveTo(offsetX, offsetY);
    };

    const onPointerMove = (event: PointerEvent): void => {
      if (!drawing || pdfTool !== "pen") return;

      const { offsetX, offsetY } = getOffsets(event);

      ctx.lineTo(offsetX, offsetY);
      ctx.stroke();
    };

    const onPointerUp = (event: PointerEvent): void => {
      if (!drawing) return;

      drawing = false;

      try {
        overlay.releasePointerCapture(event.pointerId);
      } catch {
        // Ignore invalid capture release
      }
    };

    const onClick = (event: MouseEvent): void => {
      if (pdfTool !== "text") return;

      // eslint-disable-next-line no-alert -- lightweight annotation UX inside desktop shell
      const label = window.prompt("Enter text to place on this page");

      if (!label) return;

      ctx.fillText(label, event.offsetX, event.offsetY);
    };

      overlay.addEventListener("pointerdown", onPointerDown);
      overlay.addEventListener("pointermove", onPointerMove);
      overlay.addEventListener("pointerup", onPointerUp);
      overlay.addEventListener("pointercancel", onPointerUp);
      overlay.addEventListener("click", onClick);

      cleanup = () => {
        overlay.removeEventListener("pointerdown", onPointerDown);
        overlay.removeEventListener("pointermove", onPointerMove);
        overlay.removeEventListener("pointerup", onPointerUp);
        overlay.removeEventListener("pointercancel", onPointerUp);
        overlay.removeEventListener("click", onClick);
      };
    }

    return cleanup;
  }, [pdfEditMode, pdfTool]);

  useEffect(() => {
    const overlay = overlayRef.current;

    if (!overlay || !canvas) return;

    overlay.width = canvas.width;
    overlay.height = canvas.height;
  }, [canvas, canvas.height, canvas.width]);

  useEffect(() => {
    const wrap = wrapRef.current;
    const scrollRoot = pdfScrollRoot ?? componentWindow;

    let observer: IntersectionObserver | undefined;

    if (wrap instanceof HTMLElement && scrollRoot instanceof HTMLElement) {
      observer = new IntersectionObserver(
        (entries) => {
          entries.forEach(({ isIntersecting }) => {
            if (isIntersecting) argument(id, "page", page);
          });
        },
        { root: scrollRoot, threshold: 0.5 }
      );

      observer.observe(wrap);
    }

    return () => observer?.disconnect();
  }, [argument, componentWindow, id, page, pdfScrollRoot]);

  return (
    <li>
      <div
        ref={wrapRef}
        style={{
          display: "inline-block",
          margin: "4px 4px 0",
          position: "relative",
        }}
      >
        <div ref={canvasMountRef} />
        <canvas
          ref={setOverlayRef}
          style={{
            cursor: pdfEditMode
              ? pdfTool === "pen"
                ? "crosshair"
                : "text"
              : "default",
            height: canvas.height,
            left: 0,
            pointerEvents: pdfEditMode ? "auto" : "none",
            position: "absolute",
            top: 0,
            touchAction: "none",
            width: canvas.width,
          }}
        />
      </div>
    </li>
  );
};

export default memo(Page);
