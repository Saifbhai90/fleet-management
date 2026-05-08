import { memo, useEffect, useRef, type FC } from "react";

type PdfThumbnailProps = {
  canvas: HTMLCanvasElement;
  onClick: () => void;
  selected: boolean;
};

const PdfThumbnail: FC<PdfThumbnailProps> = ({
  canvas,
  onClick,
  selected,
}) => {
  const holderRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    holderRef.current?.replaceChildren(canvas);

    return () => {
      canvas.remove();
    };
  }, [canvas]);

  return (
    <button
      className={`thumb-button${selected ? " active" : ""}`}
      onClick={onClick}
      type="button"
    >
      <span ref={holderRef} />
    </button>
  );
};

export default memo(PdfThumbnail);
