import {
  memo,
  useCallback,
  useEffect,
  useRef,
  useState,
  type FC,
} from "react";
import Page from "components/apps/PDF/Page";
import PdfThumbnail from "components/apps/PDF/PdfThumbnail";
import Controls from "components/apps/PDF/Controls";
import {
  StyledPdfScrollArea,
  StyledPdfShell,
  StyledPdfThumbnailAside,
} from "components/apps/PDF/StyledPDF";
import usePDF from "components/apps/PDF/usePDF";
import { PdfViewerSessionProvider } from "components/apps/PDF/PdfViewerSessionContext";
import { type ComponentProcessProps } from "components/system/Apps/RenderComponent";
import useFileDrop from "components/system/Files/FileManager/useFileDrop";
import { useProcesses } from "contexts/process";

const PDF: FC<ComponentProcessProps> = ({ id }) => {
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const overlayRefs = useRef<(HTMLCanvasElement | null)[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const reloadDocument = useCallback(() => {
    setReloadKey((key) => key + 1);
  }, []);
  const { argument, linkElement, processes: { [id]: process } = {} } =
    useProcesses();
  const currentPage = process?.page ?? 1;
  const pdfUrl = process?.url ?? "";

  const scrollAreaCallback = useCallback(
    (node: HTMLDivElement | null) => {
      scrollAreaRef.current = node;

      if (node) linkElement(id, "pdfScrollRoot", node);
    },
    [id, linkElement]
  );

  const { pages, thumbnails } = usePDF(id, scrollAreaRef, reloadKey);

  const pagesMarker =
    pages[0]?.dataset.pdfReactKey ?? `len-${String(pages.length)}`;

  const overlayRegister = useCallback(
    (pageIndex: number, element: HTMLCanvasElement | null) => {
      overlayRefs.current[pageIndex] = element;
    },
    []
  );

  /* eslint-disable react-hooks-addons/no-unused-deps -- pagesMarker tracks rebuilt page canvases */
  useEffect(() => {
    overlayRefs.current = [];
  }, [pagesMarker]);
  /* eslint-enable react-hooks-addons/no-unused-deps */

  const jumpToPage = useCallback(
    (pageNumber: number) => {
      argument(id, "page", pageNumber);

      requestAnimationFrame(() => {
        scrollAreaRef.current
          ?.querySelectorAll(":scope > ol.pages > li")
          [pageNumber - 1]?.scrollIntoView({
            behavior: "smooth",
            block: "start",
          });
      });
    },
    [argument, id]
  );

  const fileDropProps = useFileDrop({ id });

  return (
    <PdfViewerSessionProvider value={{ overlayRefs, reloadDocument }}>
      <StyledPdfShell>
        <StyledPdfThumbnailAside>
          {thumbnails.map((thumbCanvas, index) => (
            <PdfThumbnail
              key={thumbCanvas.dataset.pdfReactKey ?? `t-${index}`}
              canvas={thumbCanvas}
              onClick={() => jumpToPage(index + 1)}
              selected={currentPage === index + 1}
            />
          ))}
        </StyledPdfThumbnailAside>
        <StyledPdfScrollArea
          ref={scrollAreaCallback}
          {...fileDropProps}
          className={pdfUrl ? undefined : "drop"}
        >
          <ol className="pages">
            {pages.map((canvas, index) => (
              <Page
                key={canvas.dataset.pdfReactKey ?? `p-${index}`}
                canvas={canvas}
                id={id}
                overlayRegister={overlayRegister}
                page={index + 1}
              />
            ))}
          </ol>
        </StyledPdfScrollArea>
      </StyledPdfShell>
      <Controls id={id} />
    </PdfViewerSessionProvider>
  );
};

export default memo(PDF);
