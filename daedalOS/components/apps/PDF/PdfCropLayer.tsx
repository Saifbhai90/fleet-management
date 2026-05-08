import {
  memo,
  useCallback,
  useRef,
  useState,
  type FC,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { usePdfViewerSession } from "components/apps/PDF/PdfViewerSessionContext";
import { replacePdfPageWithPng } from "components/apps/PDF/replacePdfPageWithImage";
import { useFileSystem } from "contexts/fileSystem";
import { useProcesses } from "contexts/process";

const MIN_CROP_PX = 10;

export type CropPixelRect = {
  h: number;
  w: number;
  x: number;
  y: number;
};

type PdfCropLayerProps = {
  canvasHeight: number;
  canvasWidth: number;
  id: string;
  page: number;
};

const PdfCropLayer: FC<PdfCropLayerProps> = ({
  canvasHeight,
  canvasWidth,
  id,
  page,
}) => {
  const { argument, processes: { [id]: process } = {} } = useProcesses();
  const { pageCanvasRefs, reloadDocument } = usePdfViewerSession();
  const { readFile, writeFile } = useFileSystem();
  const url = process?.url ?? "";

  const dragRef = useRef<
    { pointerId: number; sx: number; sy: number } | undefined
  >(undefined);
  const [draft, setDraft] = useState<CropPixelRect | undefined>();

  const pageIndex = page - 1;

  const cancel = useCallback((): void => {
    argument(id, "pdfCropMode", false);
    setDraft(undefined);
    dragRef.current = undefined;
  }, [argument, id]);

  const applyCrop = useCallback(async (): Promise<void> => {
    if (!draft || !url || draft.w < MIN_CROP_PX || draft.h < MIN_CROP_PX) {
      return;
    }

    const source = pageCanvasRefs.current[pageIndex];

    if (!source) return;

    try {
      const cropCanvas = document.createElement("canvas");

      cropCanvas.height = Math.round(draft.h);
      cropCanvas.width = Math.round(draft.w);

      const ctx = cropCanvas.getContext("2d");

      if (!ctx) return;

      ctx.drawImage(
        source,
        draft.x,
        draft.y,
        draft.w,
        draft.h,
        0,
        0,
        draft.w,
        draft.h
      );

      const pngBlob = await new Promise<Blob | null>((resolve) => {
        cropCanvas.toBlob((blob) => {
          resolve(blob);
        }, "image/png");
      });

      if (!pngBlob) return;

      const pngBuffer = await pngBlob.arrayBuffer();
      const pdfBytes = await readFile(url);
      const nextPdf = await replacePdfPageWithPng(
        new Uint8Array(pdfBytes),
        pageIndex,
        pngBuffer
      );

      await writeFile(url, Buffer.from(nextPdf), true);
      reloadDocument();
      cancel();
    } catch {
      // eslint-disable-next-line no-alert -- FS / PDF errors need user feedback
      window.alert("Could not apply crop to this page.");
    }
  }, [
    cancel,
    draft,
    pageCanvasRefs,
    pageIndex,
    readFile,
    reloadDocument,
    url,
    writeFile,
  ]);

  const layerPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>): void => {
      event.currentTarget.setPointerCapture(event.pointerId);
      const bounds = event.currentTarget.getBoundingClientRect();
      const scaleX = canvasWidth / bounds.width;
      const scaleY = canvasHeight / bounds.height;

      dragRef.current = {
        pointerId: event.pointerId,
        sx: (event.clientX - bounds.left) * scaleX,
        sy: (event.clientY - bounds.top) * scaleY,
      };

      setDraft(undefined);
    },
    [canvasHeight, canvasWidth]
  );

  const layerPointerMove = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>): void => {
      const drag = dragRef.current;

      if (!drag || event.pointerId !== drag.pointerId) return;

      const bounds = event.currentTarget.getBoundingClientRect();
      const scaleX = canvasWidth / bounds.width;
      const scaleY = canvasHeight / bounds.height;

      const cx = (event.clientX - bounds.left) * scaleX;
      const cy = (event.clientY - bounds.top) * scaleY;

      const x = Math.min(drag.sx, cx);
      const y = Math.min(drag.sy, cy);
      const w = Math.abs(cx - drag.sx);
      const h = Math.abs(cy - drag.sy);

      setDraft({
        h,
        w,
        x,
        y,
      });
    },
    [canvasHeight, canvasWidth]
  );

  const layerPointerUp = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>): void => {
      const drag = dragRef.current;

      if (!drag || event.pointerId !== drag.pointerId) return;

      try {
        event.currentTarget.releasePointerCapture(event.pointerId);
      } catch {
        // Ignore invalid capture release
      }

      dragRef.current = undefined;
    },
    []
  );

  return (
    <>
      <div
        onPointerDown={layerPointerDown}
        onPointerMove={layerPointerMove}
        onPointerUp={layerPointerUp}
        role="presentation"
        style={{
          backgroundColor: "rgb(0 0 0 / 35%)",
          cursor: "crosshair",
          height: canvasHeight,
          left: 0,
          position: "absolute",
          top: 0,
          touchAction: "none",
          width: canvasWidth,
          zIndex: 12,
        }}
      >
        {draft &&
          draft.w >= 4 &&
          draft.h >= 4 && (
            <div
              style={{
                border: "2px solid rgb(147 197 253)",
                boxShadow: "0 0 0 9999px rgb(0 0 0 / 45%)",
                height: `${String((draft.h / canvasHeight) * 100)}%`,
                left: `${String((draft.x / canvasWidth) * 100)}%`,
                pointerEvents: "none",
                position: "absolute",
                top: `${String((draft.y / canvasHeight) * 100)}%`,
                width: `${String((draft.w / canvasWidth) * 100)}%`,
              }}
            />
          )}
      </div>
      <div
        style={{
          backgroundColor: "rgb(35 38 41 / 95%)",
          borderRadius: "8px",
          bottom: "10px",
          boxShadow: "0 4px 18px hsl(0 0% 0% / 45%)",
          display: "flex",
          gap: "8px",
          left: "50%",
          padding: "8px 12px",
          position: "absolute",
          transform: "translateX(-50%)",
          zIndex: 14,
        }}
      >
        <button
          disabled={
            !draft || draft.w < MIN_CROP_PX || draft.h < MIN_CROP_PX || !url
          }
          onClick={() => {
            applyCrop().catch(() => {
              // surfaced via alert inside applyCrop
            });
          }}
          style={{
            background: "rgb(59 130 246)",
            border: "none",
            borderRadius: "6px",
            color: "#fff",
            cursor: "pointer",
            fontSize: "12px",
            fontWeight: 600,
            padding: "6px 12px",
          }}
          type="button"
        >
          Apply crop
        </button>
        <button
          onClick={cancel}
          style={{
            background: "transparent",
            border: "1px solid rgb(148 163 184)",
            borderRadius: "6px",
            color: "#e2e8f0",
            cursor: "pointer",
            fontSize: "12px",
            padding: "6px 12px",
          }}
          type="button"
        >
          Cancel
        </button>
      </div>
    </>
  );
};

export default memo(PdfCropLayer);
