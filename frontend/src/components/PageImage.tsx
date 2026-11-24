import { useState } from "react";
import { CREDIT, EXPLAIN, place } from "../lib/wording";
import { Icon } from "./Icon";
import { Tip } from "./Tip";

/** One page of a report as an image, with a loading state, a way to open it at full size, and the credit line. */
export function PageImage({ url, fileId, page }: { url: string; fileId: string; page: number }) {
  const [state, setState] = useState<"loading" | "shown" | "failed">("loading");
  const where = place(fileId, page);

  if (state === "failed") {
    return (
      <p className="note page-image__failed" role="status">
        <Icon name="alert" size={16} /> The picture of this page could not be loaded. The text of the page is on the other tab.
      </p>
    );
  }

  return (
    <figure className="page-image">
      <a className="page-image__frame" href={url} target="_blank" rel="noreferrer" aria-label={`Open ${where} at full size`}>
        {state === "loading" && <span className="page-image__loading" role="status">Loading the page…</span>}
        <img
          src={url}
          alt={`${where}, as printed in the report`}
          className={state === "loading" ? "page-image__img page-image__img--hidden" : "page-image__img"}
          onLoad={() => setState("shown")}
          onError={() => setState("failed")}
        />
      </a>
      <figcaption className="page-image__caption">
        <span>
          Click the page to open it at full size. <Tip about="the page picture">{EXPLAIN.pageImage}</Tip>
        </span>
        <span className="page-image__credit">
          Report by {CREDIT.author} Published in the{" "}
          <a href={CREDIT.repository} target="_blank" rel="noreferrer">U.S. DOE Geothermal Data Repository</a> under{" "}
          <a href={CREDIT.licence} target="_blank" rel="noreferrer">CC BY 4.0</a>.
        </span>
      </figcaption>
    </figure>
  );
}
