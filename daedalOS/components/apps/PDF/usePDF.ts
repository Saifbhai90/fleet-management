import { basename } from "path";
import {
  type RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  type PDFWorker,
  type PDFDocumentProxy,
} from "pdfjs-dist/types/src/display/api";
import { type MetadataInfo } from "components/apps/PDF/types";
import useTitle from "components/system/Window/useTitle";
import { useFileSystem } from "contexts/fileSystem";
import { useProcesses } from "contexts/process";
import { BASE_2D_CONTEXT_OPTIONS } from "utils/constants";
import { loadFiles } from "utils/functions";

export const scales = [
  0.25, 0.33, 0.5, 0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4,
  5,
];

const CANVAS_MARGIN_PX = 4;
const THUMB_MAX_PX = 96;

const stampCanvasId = (): string =>
  globalThis.crypto?.randomUUID?.() ??
  `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;

const getInitialScale = (windowWidth = 0, canvasWidth = 0): number => {
  const adjustedWindowWidth = windowWidth - CANVAS_MARGIN_PX * 2;

  if (adjustedWindowWidth >= canvasWidth) return 1;

  const minScale = adjustedWindowWidth / canvasWidth;
  const minScaleIndex = scales.findIndex((scale) => scale >= minScale);

  return minScaleIndex > 0 ? scales[minScaleIndex - 1] : 1;
};

type UsePdfResult = {
  pages: HTMLCanvasElement[];
  thumbnails: HTMLCanvasElement[];
};

const renderPageToCanvas = async (
  doc: PDFDocumentProxy,
  pageNumber: number,
  scale: number,
  rotation: number
): Promise<HTMLCanvasElement> => {
  const canvas = document.createElement("canvas");
  const canvasContext = canvas.getContext(
    "2d",
    BASE_2D_CONTEXT_OPTIONS
  ) as CanvasRenderingContext2D;
  const page = await doc.getPage(pageNumber);
  const viewport = page.getViewport({ rotation, scale });

  canvas.height = viewport.height;
  canvas.width = viewport.width;

  await page.render({ canvas, canvasContext, viewport }).promise;

  return canvas;
};

const usePDF = (
  id: string,
  containerRef: RefObject<HTMLDivElement | null>,
  reloadKey: number
): UsePdfResult => {
  const { readFile } = useFileSystem();
  const {
    argument,
    processes: { [id]: process } = {},
    url: setUrl,
  } = useProcesses();
  const {
    libs = [],
    pdfPageRotations,
    scale,
    url: processUrl,
  } = process || {};
  const [pages, setPages] = useState<HTMLCanvasElement[]>([]);
  const [thumbnails, setThumbnails] = useState<HTMLCanvasElement[]>([]);
  const pdfWorker = useRef<PDFWorker | undefined>(undefined);
  const docRef = useRef<PDFDocumentProxy | undefined>(undefined);
  const [docEpoch, setDocEpoch] = useState(0);
  const { prependFileToTitle } = useTitle(id);
  const renderCancelledRef = useRef(false);

  const paintPages = useCallback(async (): Promise<void> => {
    const doc = docRef.current;

    if (!doc || !processUrl || !containerRef.current || !window.pdfjsLib) {
      return;
    }

    argument(id, "rendering", true);

    try {
      let effectiveScale = scale;

      if (effectiveScale === undefined && doc.numPages > 0) {
        const firstPage = await doc.getPage(1);

        if (renderCancelledRef.current) return;

        const firstRotation = pdfPageRotations?.[0] ?? 0;
        const vp = firstPage.getViewport({
          rotation: firstRotation,
          scale: 1,
        });
        effectiveScale = getInitialScale(containerRef.current.clientWidth, vp.width);
        argument(id, "scale", effectiveScale);
      }

      effectiveScale = scale ?? effectiveScale ?? 1;

      const nextPages: HTMLCanvasElement[] = [];
      const nextThumbs: HTMLCanvasElement[] = [];

      /* eslint-disable no-await-in-loop -- page renders are sequential to cap memory */
      for (let pageNumber = 1; pageNumber <= doc.numPages; pageNumber += 1) {
        if (renderCancelledRef.current) return;

        const pageRotation = pdfPageRotations?.[pageNumber - 1] ?? 0;

        const pageCanvas = await renderPageToCanvas(
          doc,
          pageNumber,
          effectiveScale,
          pageRotation
        );

        const pageObj = await doc.getPage(pageNumber);
        const unitVp = pageObj.getViewport({
          rotation: pageRotation,
          scale: 1,
        });
        const thumbScale = Math.min(
          THUMB_MAX_PX / unitVp.width,
          THUMB_MAX_PX / unitVp.height
        );

        const thumbCanvas = await renderPageToCanvas(
          doc,
          pageNumber,
          thumbScale,
          pageRotation
        );

        pageCanvas.dataset.pdfReactKey = stampCanvasId();
        thumbCanvas.dataset.pdfReactKey = stampCanvasId();

        nextPages.push(pageCanvas);
        nextThumbs.push(thumbCanvas);
      }

      /* eslint-enable no-await-in-loop */

      if (renderCancelledRef.current) return;

      setPages(nextPages);
      setThumbnails(nextThumbs);
    } finally {
      argument(id, "rendering", false);
    }
  }, [
    argument,
    containerRef,
    id,
    pdfPageRotations,
    processUrl,
    scale,
  ]);

  useEffect(() => {
    renderCancelledRef.current = false;

    return () => {
      renderCancelledRef.current = true;
    };
  }, []);

  /* eslint-disable react-hooks-addons/no-unused-deps -- reloadKey forces reloading PDF bytes after save */
  useEffect(() => {
    renderCancelledRef.current = false;
    pdfWorker.current?.destroy();
    pdfWorker.current = undefined;
    docRef.current = undefined;
    setPages([]);
    setThumbnails([]);

    if (!processUrl) {
      if (containerRef.current) {
        containerRef.current.classList.add("drop");
      }

      argument(id, "subTitle", "");
      argument(id, "count", 0);
      argument(id, "page", 1);
      prependFileToTitle("");

      return () => {
        renderCancelledRef.current = true;
      };
    }

    if (containerRef.current) {
      containerRef.current.classList.remove("drop");
      // eslint-disable-next-line no-param-reassign
      containerRef.current.scrollTop = 0;
    }

    let cancelled = false;

    loadFiles(libs).then(() => {
      if (cancelled || !window.pdfjsLib || !processUrl) return;

      readFile(processUrl)
        .then(async (fileData) => {
          if (cancelled || renderCancelledRef.current) return;

          if (fileData.length === 0) throw new Error("File is empty");

          const pdfjs = window.pdfjsLib;

          if (!pdfjs) return;

          const loader = pdfjs.getDocument(fileData);
          const doc = await loader.promise;

          if (cancelled || renderCancelledRef.current) return;

          pdfWorker.current = (
            loader as unknown as { _worker: PDFWorker }
          )._worker;
          docRef.current = doc;

          const { info } = await doc.getMetadata();
          const { Title } = info as MetadataInfo;

          argument(id, "subTitle", Title);
          argument(id, "count", doc.numPages);
          argument(id, "page", 1);
          prependFileToTitle(Title || basename(processUrl));

          setDocEpoch((epoch) => epoch + 1);
        })
        .catch(() => {
          if (!cancelled) {
            setUrl(id, "");
            argument(id, "subTitle", "");
            argument(id, "count", 0);
            prependFileToTitle("");
          }
        });
    });

    return () => {
      cancelled = true;
      renderCancelledRef.current = true;
    };
  }, [
    argument,
    containerRef,
    id,
    libs,
    prependFileToTitle,
    processUrl,
    readFile,
    reloadKey,
    setUrl,
  ]);
  /* eslint-enable react-hooks-addons/no-unused-deps */

  /* eslint-disable react-hooks-addons/no-unused-deps -- repaint when docEpoch / zoom / rotation changes */
  useEffect(() => {
    let cleanup: (() => void) | undefined;

    if (docRef.current && processUrl) {
      renderCancelledRef.current = false;

      paintPages().catch(() => {
        argument(id, "rendering", false);
      });

      cleanup = () => {
        renderCancelledRef.current = true;
      };
    }

    return cleanup;
  }, [
    argument,
    docEpoch,
    id,
    paintPages,
    pdfPageRotations,
    processUrl,
    scale,
  ]);
  /* eslint-enable react-hooks-addons/no-unused-deps */

  return { pages, thumbnails };
};

export default usePDF;
