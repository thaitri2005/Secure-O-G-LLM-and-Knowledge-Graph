import { useState } from "react";
import type { ChunkOut, PageOut } from "../api/types";
import { place } from "../lib/wording";
import { Icon } from "./Icon";
import { PageImage } from "./PageImage";
import { ReportText } from "./Passage";

interface Props {
  page: PageOut;
  /** The passage on the page that was cited, marked in blue. */
  pageChunk: string | null;
  /** Values to highlight in the text. */
  values: string[];
  onClose: () => void;
  closeLabel: string;
  /** What the cited part is the source of: "answer" or "fact". */
  cited?: string;
}

/** One page of a report: the printed page beside the cited text when an image exists, and the page's text. */
export function PageView({ page, pageChunk, values, onClose, closeLabel, cited = "answer" }: Props) {
  const [pageTab, setPageTab] = useState<"image" | "text">("image");
  const imageUrl = page.image_url ?? null;
  const citedChunks = page.chunks.filter((chunk) => chunk.chunk_id === pageChunk);
  const pageText = (chunks: ChunkOut[]) =>
    chunks.map((chunk) => (
      <div key={chunk.chunk_id} className={chunk.chunk_id === pageChunk ? "page__chunk page__chunk--cited" : "page__chunk"}>
        {chunk.section && <p className="page__section">{chunk.section}</p>}
        <ReportText text={chunk.text ?? ""} values={values} />
      </div>
    ));
  return (
    <section className="evidence card" aria-label="Evidence">
      <button type="button" className="back" onClick={onClose}><Icon name="arrowLeft" size={16} /> {closeLabel}</button>
      <h2 className="evidence__title">{place(page.file_id, page.page)}</h2>
      {imageUrl && (
        <div className="tabs" role="tablist" aria-label="Page view">
          {(["image", "text"] as const).map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              id={`pagetab-${id}`}
              aria-selected={pageTab === id}
              aria-controls={`pagepanel-${id}`}
              className="tabs__tab"
              onClick={() => setPageTab(id)}
            >
              {id === "image" ? "Page as printed" : "Page text"}
            </button>
          ))}
        </div>
      )}
      {imageUrl && pageTab === "image" ? (
        <div role="tabpanel" id="pagepanel-image" aria-labelledby="pagetab-image" className="page-view">
          <PageImage key={imageUrl} url={imageUrl} fileId={page.file_id} page={page.page} />
          <div className="page-view__passage">
            <p className="note">The part the {cited} came from, as the system read it:</p>
            <div className="page">{pageText(citedChunks.length > 0 ? citedChunks : page.chunks)}</div>
          </div>
        </div>
      ) : (
        <div role="tabpanel" id="pagepanel-text" aria-labelledby="pagetab-text">
          <p className="note">This is the text of the page as the system read it. The part the {cited} came from is highlighted in blue.</p>
          <div className="page">{pageText(page.chunks)}</div>
        </div>
      )}
    </section>
  );
}
