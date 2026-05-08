import { basename } from "path";
import {
  memo,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FC,
} from "react";
import {
  Add,
  Crop,
  Download,
  Enhance,
  Hand,
  More,
  Pencil,
  Print,
  RotateCw,
  SaveDisk,
  Subtract,
  Undo,
} from "components/apps/PDF/ControlIcons";
import { mergeOverlaysIntoPdf } from "components/apps/PDF/mergePdfOverlays";
import { enhanceCanvasToDataUrl } from "components/apps/PDF/pdfImageEnhance";
import { usePdfViewerSession } from "components/apps/PDF/PdfViewerSessionContext";
import StyledControls from "components/apps/PDF/StyledControls";
import { scales } from "components/apps/PDF/usePDF";
import { type ComponentProcessProps } from "components/system/Apps/RenderComponent";
import { useFileSystem } from "contexts/fileSystem";
import { useProcesses } from "contexts/process";
import Button from "styles/common/Button";
import { bufferToUrl, label } from "utils/functions";

const COMPACT_TOOLBAR_PX = 640;

const Controls: FC<ComponentProcessProps> = ({ id }) => {
  const {
    overlayRefs,
    pageCanvasRefs,
    penUndoHandlersRef,
    reloadDocument,
    setEnhancePreview,
  } = usePdfViewerSession();
  const { readFile, writeFile } = useFileSystem();
  const { argument, processes: { [id]: process } = {} } = useProcesses();
  const {
    count = 0,
    page: currentPage = 1,
    pdfCropMode = false,
    pdfEditMode = false,
    pdfPageRotations = [],
    pdfTool = "hand",
    pdfScrollRoot,
    rendering = false,
    scale = 1,
    subTitle = "",
    url = "",
  } = process || {};

  const navRef = useRef<HTMLElement>(null);
  const moreWrapRef = useRef<HTMLLIElement>(null);
  const [compactToolbar, setCompactToolbar] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);

  useLayoutEffect(() => {
    const node = navRef.current;
    let observer: ResizeObserver | undefined;

    if (node && typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(([entry]) => {
        setCompactToolbar(entry.contentRect.width < COMPACT_TOOLBAR_PX);
      });
      observer.observe(node);
    }

    return (): void => {
      observer?.disconnect();
    };
  }, []);

  useEffect(() => {
    let removeDocMouseDown: (() => void) | undefined;

    if (moreOpen) {
      const onDocMouseDown = (event: MouseEvent): void => {
        if (
          moreWrapRef.current?.contains(event.target as globalThis.Node)
        ) {
          return;
        }

        setMoreOpen(false);
      };

      document.addEventListener("mousedown", onDocMouseDown);
      removeDocMouseDown = (): void =>
        document.removeEventListener("mousedown", onDocMouseDown);
    }

    return (): void => {
      removeDocMouseDown?.();
    };
  }, [moreOpen]);

  const scrollMainPageIntoView = (pageNumber: number): void => {
    requestAnimationFrame(() => {
      pdfScrollRoot
        ?.querySelectorAll(":scope > ol.pages > li")
        [pageNumber - 1]?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
    });
  };

  const persistPdfWithOverlays = async (): Promise<void> => {
    const bytes = await readFile(url);
    const merged = await mergeOverlaysIntoPdf(
      new Uint8Array(bytes),
      overlayRefs.current
    );
    const wrote = await writeFile(url, Buffer.from(merged), true);

    if (!wrote) throw new Error("writeFile returned false");
  };

  const onSave = async (): Promise<void> => {
    if (!url || count === 0) return;

    try {
      await persistPdfWithOverlays();
      reloadDocument();
    } catch {
      // eslint-disable-next-line no-alert -- user-visible failure for blocked FS writes
      window.alert("Could not save PDF changes.");
    }
  };

  const runEnhancePreview = (): void => {
    argument(id, "pdfCropMode", false);
    argument(id, "pdfEditMode", false);

    const canvas = pageCanvasRefs.current[currentPage - 1];

    if (!canvas) return;

    const dataUrl = enhanceCanvasToDataUrl(canvas);

    if (!dataUrl) return;

    setEnhancePreview(dataUrl, currentPage);
  };

  const toggleCrop = (): void => {
    const next = !pdfCropMode;

    argument(id, "pdfCropMode", next);

    if (next) {
      argument(id, "pdfEditMode", false);
      setEnhancePreview(undefined, undefined);
    }
  };

  const toggleEdit = (): void => {
    const next = !pdfEditMode;

    argument(id, "pdfEditMode", next);

    if (next) {
      argument(id, "pdfCropMode", false);
      argument(id, "pdfTool", "hand");
      setEnhancePreview(undefined, undefined);
    }
  };

  const rotatePage = async (): Promise<void> => {
    if (!url || count === 0) return;

    try {
      await persistPdfWithOverlays();
      const rotations = [...pdfPageRotations];

      while (rotations.length < count) rotations.push(0);

      const idx = currentPage - 1;

      rotations[idx] = ((rotations[idx] ?? 0) + 90) % 360;
      argument(id, "pdfPageRotations", rotations);
      reloadDocument();
    } catch {
      // eslint-disable-next-line no-alert -- rotation persists annotations via merge+write
      window.alert("Could not rotate this page.");
    }
  };

  const undoLastPenStroke = (): void => {
    penUndoHandlersRef.current[currentPage - 1]?.();
  };

  const printPdf = async (): Promise<void> => {
    if (!url || count === 0) return;

    try {
      const buf = await readFile(url);
      const blob = new Blob([new Uint8Array(buf)], {
        type: "application/pdf",
      });
      const blobUrl = URL.createObjectURL(blob);
      const iframe = document.createElement("iframe");

      iframe.setAttribute(
        "style",
        "position:fixed;width:0;height:0;border:0;right:0;bottom:0;"
      );
      iframe.src = blobUrl;
      document.body.append(iframe);

      iframe.addEventListener(
        "load",
        () => {
          iframe.contentWindow?.focus();
          iframe.contentWindow?.print();
          globalThis.setTimeout(() => {
            iframe.remove();
            URL.revokeObjectURL(blobUrl);
          }, 120_000);
        },
        { once: true }
      );
    } catch {
      try {
        const { default: printJs } = await import("print-js");

        printJs({
          base64: true,
          printable: (await readFile(url)).toString("base64"),
          type: "pdf",
        });
      } catch {
        // eslint-disable-next-line no-alert -- last-resort feedback
        window.alert("Could not open the print dialog.");
      }
    }
  };

  return (
    <StyledControls ref={navRef}>
      <div className="side-menu">
        <span>{subTitle || basename(url)}</span>
      </div>
      <ol>
        {count !== 0 && (
          <li className="pages">
            <input
              enterKeyHint="go"
              onChange={({ target }) => {
                const newPage = Number(target.value);

                if (Number.isNaN(newPage) || newPage < 1 || newPage > count) {
                  return;
                }

                argument(id, "page", newPage);
                scrollMainPageIntoView(newPage);
              }}
              value={currentPage}
            />{" "}
            / {count}
          </li>
        )}
        <li className="scale">
          <Button
            className="subtract"
            disabled={rendering || scale === 0.25 || count === 0}
            onClick={() =>
              argument(id, "scale", scales[scales.indexOf(scale) - 1])
            }
            {...label("Zoom out")}
          >
            <Subtract />
          </Button>
          <input
            disabled={rendering || count === 0}
            enterKeyHint="done"
            onChange={({ target }) => {
              if (
                !target.value.endsWith("%") ||
                target.value.length > 4 ||
                target.value.length < 2
              ) {
                return;
              }

              const newScale = Number(target.value.replace("%", "")) / 100;

              if (
                Number.isNaN(newScale) ||
                newScale > scales[scales.length - 1] ||
                newScale < scales[0]
              ) {
                return;
              }

              argument(
                id,
                "scale",
                scales[scales.findIndex((s) => s >= newScale)]
              );
            }}
            value={`${Math.round(scale * 100)}%`}
          />
          <Button
            className="add"
            disabled={rendering || scale === 5 || count === 0}
            onClick={() =>
              argument(id, "scale", scales[scales.indexOf(scale) + 1])
            }
            {...label("Zoom in")}
          >
            <Add />
          </Button>
        </li>
        <li className="pdf-icon-tools">
          <Button
            className={`icon-tool${pdfCropMode ? " active" : ""}`}
            disabled={count === 0 || rendering}
            onClick={toggleCrop}
            {...label("Crop page")}
          >
            <Crop />
          </Button>
          <Button
            className="icon-tool"
            disabled={count === 0 || rendering}
            onClick={runEnhancePreview}
            {...label("Enhance scan")}
          >
            <Enhance />
          </Button>
          <Button
            className={`icon-tool${pdfEditMode ? " active" : ""}`}
            disabled={count === 0 || rendering}
            onClick={toggleEdit}
            {...label("Annotate")}
          >
            <Pencil />
          </Button>
          {compactToolbar ? undefined : (
            <>
              <Button
                className={`icon-tool${pdfTool === "hand" ? " active" : ""}`}
                disabled={!pdfEditMode || rendering || count === 0}
                onClick={() => argument(id, "pdfTool", "hand")}
                {...label("Hand (scroll)")}
              >
                <Hand />
              </Button>
              <Button
                className={`icon-tool${pdfTool === "pen" ? " active" : ""}`}
                disabled={!pdfEditMode || rendering || count === 0}
                onClick={() => argument(id, "pdfTool", "pen")}
                {...label("Pen")}
              >
                ✎
              </Button>
              <Button
                className={`icon-tool${pdfTool === "text" ? " active" : ""}`}
                disabled={!pdfEditMode || rendering || count === 0}
                onClick={() => argument(id, "pdfTool", "text")}
                {...label("Text")}
              >
                T
              </Button>
              <Button
                className="icon-tool"
                disabled={!pdfEditMode || rendering || count === 0}
                onClick={undoLastPenStroke}
                {...label("Undo last pen stroke")}
              >
                <Undo />
              </Button>
              <Button
                className="icon-tool"
                disabled={count === 0 || rendering}
                onClick={() => {
                  rotatePage().catch(() => {
                    // surfaced via alert inside rotatePage
                  });
                }}
                {...label("Rotate page")}
              >
                <RotateCw />
              </Button>
            </>
          )}
          <Button
            className="icon-tool"
            disabled={count === 0 || rendering}
            onClick={() => {
              onSave().catch(() => {
                // Errors surfaced via alert in onSave
              });
            }}
            {...label("Save")}
          >
            <SaveDisk />
          </Button>
          {compactToolbar ? (
            <span ref={moreWrapRef} className="more-menu-wrap">
              <Button
                className={`icon-tool${moreOpen ? " active" : ""}`}
                disabled={count === 0 || rendering}
                onClick={() => setMoreOpen((open) => !open)}
                {...label("More tools")}
              >
                <More />
              </Button>
              {moreOpen ? (
                <div className="more-dropdown">
                  <button
                    className="more-dd-row"
                    disabled={!pdfEditMode || rendering || count === 0}
                    onClick={() => {
                      argument(id, "pdfTool", "hand");
                      setMoreOpen(false);
                    }}
                    type="button"
                  >
                    <span className="more-dd-icon">
                      <Hand />
                    </span>
                    <span>Hand</span>
                  </button>
                  <button
                    className="more-dd-row"
                    disabled={!pdfEditMode || rendering || count === 0}
                    onClick={() => {
                      argument(id, "pdfTool", "pen");
                      setMoreOpen(false);
                    }}
                    type="button"
                  >
                    Pen
                  </button>
                  <button
                    className="more-dd-row"
                    disabled={!pdfEditMode || rendering || count === 0}
                    onClick={() => {
                      argument(id, "pdfTool", "text");
                      setMoreOpen(false);
                    }}
                    type="button"
                  >
                    Text
                  </button>
                  <button
                    className="more-dd-row"
                    disabled={!pdfEditMode || rendering || count === 0}
                    onClick={() => {
                      undoLastPenStroke();
                      setMoreOpen(false);
                    }}
                    type="button"
                  >
                    <span className="more-dd-icon">
                      <Undo />
                    </span>
                    <span>Undo stroke</span>
                  </button>
                  <button
                    className="more-dd-row"
                    disabled={count === 0 || rendering}
                    onClick={() => {
                      rotatePage().catch(() => {
                        // surfaced via alert inside rotatePage
                      });
                      setMoreOpen(false);
                    }}
                    type="button"
                  >
                    <span className="more-dd-icon">
                      <RotateCw />
                    </span>
                    <span>Rotate page</span>
                  </button>
                </div>
              ) : undefined}
            </span>
          ) : undefined}
        </li>
      </ol>
      <div className="side-menu">
        <Button
          className="download"
          disabled={count === 0}
          onClick={async () => {
            const link = document.createElement("a");

            link.href = bufferToUrl(await readFile(url));
            link.download = basename(url);

            link.click();
          }}
          {...label("Download")}
        >
          <Download />
        </Button>
        <Button
          disabled={count === 0}
          onClick={() => {
            printPdf().catch(() => {
              // surfaced via alert inside printPdf
            });
          }}
          {...label("Print")}
        >
          <Print />
        </Button>
      </div>
    </StyledControls>
  );
};

export default memo(Controls);
