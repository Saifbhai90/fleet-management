import {
  useRef,
  useEffect,
  memo,
  useCallback,
  type FC,
} from "react";
import PdfCropLayer from "components/apps/PDF/PdfCropLayer";
import { usePdfViewerSession } from "components/apps/PDF/PdfViewerSessionContext";
import { useProcesses } from "contexts/process";

const MAX_PEN_UNDO = 40;

type PageProps = {
  canvas: HTMLCanvasElement;
  id: string;
  overlayRegister: (pageIndex: number, element?: HTMLCanvasElement) => void;
  page: number;
  pageCanvasRegister: (pageIndex: number, element?: HTMLCanvasElement) => void;
};

const Page: FC<PageProps> = ({
  canvas,
  id,
  overlayRegister,
  page,
  pageCanvasRegister,
}) => {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasMountRef = useRef<HTMLDivElement | null>(null);
  const overlayRef = useRef<HTMLCanvasElement | null>(null);
  const undoStackRef = useRef<ImageData[]>([]);
  const pendingBeforeStrokeRef = useRef<ImageData | undefined>(undefined);
  const { penUndoHandlersRef } = usePdfViewerSession();
  const {
    argument,
    processes: { [id]: process },
  } = useProcesses();
  const {
    componentWindow,
    pdfCropMode = false,
    pdfEditMode = false,
    pdfScrollRoot,
    pdfTool = "hand",
  } = process || {};

  const pageIndex = page - 1;
  const currentVisiblePage = process?.page ?? 1;
  const cropThisPage = pdfCropMode && currentVisiblePage === page;

  const setOverlayRef = useCallback(
    (element: HTMLCanvasElement | null) => {
      overlayRef.current = element;
      overlayRegister(pageIndex, element ?? undefined);
    },
    [overlayRegister, pageIndex]
  );

  useEffect(() => {
    const mount = canvasMountRef.current;

    if (mount) mount.replaceChildren(canvas);

    pageCanvasRegister(pageIndex, canvas);

    return () => {
      pageCanvasRegister(pageIndex);
      canvas.remove();
    };
  }, [canvas, pageCanvasRegister, pageIndex]);

  useEffect(() => {
    undoStackRef.current = [];
    pendingBeforeStrokeRef.current = undefined;
  }, [canvas.height, canvas.width]);

  useEffect(() => {
    if (!pdfEditMode) undoStackRef.current = [];
  }, [pdfEditMode]);

  useEffect(() => {
    const handlers = penUndoHandlersRef.current;

    const undoLastStroke = (): void => {
      const overlay = overlayRef.current;
      const ctx = overlay?.getContext("2d");

      if (!overlay || !ctx) return;

      const snap = undoStackRef.current.pop();

      if (!snap) return;

      ctx.putImageData(snap, 0, 0);
    };

    handlers[pageIndex] = undoLastStroke;

    return (): void => {
      handlers[pageIndex] = undefined;
    };
  }, [pageIndex, penUndoHandlersRef]);

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
      let activePenStroke = false;

      const getOffsets = (
        event: Pick<PointerEvent | MouseEvent, "clientX" | "clientY">
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
        activePenStroke = true;
        pendingBeforeStrokeRef.current = ctx.getImageData(
          0,
          0,
          overlay.width,
          overlay.height
        );
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

      const finishPenStroke = (event: PointerEvent): void => {
        if (!drawing) return;

        drawing = false;

        try {
          overlay.releasePointerCapture(event.pointerId);
        } catch {
          // Ignore invalid capture release
        }

        if (activePenStroke && pendingBeforeStrokeRef.current) {
          undoStackRef.current.push(pendingBeforeStrokeRef.current);
          pendingBeforeStrokeRef.current = undefined;

          while (undoStackRef.current.length > MAX_PEN_UNDO) {
            undoStackRef.current.shift();
          }
        }

        activePenStroke = false;
      };

      const onPointerUp = (event: PointerEvent): void => {
        finishPenStroke(event);
      };

      const onClick = (event: MouseEvent): void => {
        if (pdfTool !== "text") return;

        const { offsetX, offsetY } = getOffsets(event);

        // eslint-disable-next-line no-alert -- lightweight annotation UX inside desktop shell
        const label = window.prompt("Enter text to place on this page");

        if (!label) return;

        ctx.fillText(label, offsetX, offsetY);
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

  const overlayInteractive =
    pdfEditMode && pdfTool !== "hand" && !pdfCropMode;

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
            cursor:
              pdfCropMode || !pdfEditMode
                ? "default"
                : pdfTool === "hand"
                  ? "grab"
                  : pdfTool === "pen"
                    ? "crosshair"
                    : "text",
            height: canvas.height,
            left: 0,
            pointerEvents: overlayInteractive ? "auto" : "none",
            position: "absolute",
            top: 0,
            touchAction: "none",
            width: canvas.width,
            zIndex: 2,
          }}
        />
        {cropThisPage && (
          <PdfCropLayer
            canvasHeight={canvas.height}
            canvasWidth={canvas.width}
            id={id}
            page={page}
          />
        )}
      </div>
    </li>
  );
};

export default memo(Page);
