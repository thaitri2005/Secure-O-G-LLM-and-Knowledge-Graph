import { useEffect, useRef, useState } from "react";
import type { ChunkOut, PageOut } from "../api/types";
import { place } from "../lib/wording";
import { Icon } from "./Icon";
import { PageImage } from "./PageImage";
import { ReportText } from "./Passage";
import { TabList } from "./Tabs";

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
  const heading = useRef<HTMLHeadingElement>(null);
  // The page takes the evidence's place: move the keyboard and a screen reader to it, and bring it into view.
  useEffect(() => {
    heading.current?.focus();
  }, [page.file_id, page.page]);
  const citedChunks = page.chunks.filter((chunk) => chunk.chunk_id === pageChunk);
  const pageText = (chunks: ChunkOut[]) =>
    chunks.map((chunk) => (
      <div key={chunk.chunk_id} className={chunk.chunk_id === pageChunk ? "page__chunk page__chunk--cited" : "page__chunk"}>
        {chunk.section && <p className="page__section">{chunk.section}</p>}
        <ReportText text={chunk.text ?? ""} values={values} />
      </div>
    ));
  return (
    <section className="evidence card" aria-labelledby="page-title">
      <button type="button" className="back" onClick={onClose}><Icon name="arrowLeft" size={16} /> {closeLabel}</button>
      <h2 id="page-title" ref={heading} tabIndex={-1} className="evidence__title">{place(page.file_id, page.page)}</h2>
      {imageUrl && (
        <TabList
          label="Page view"
          ids={["pagetab", "pagepanel"]}
          tabs={[{ id: "image", label: "Page as printed" }, { id: "text", label: "Page text" }]}
          selected={pageTab}
          onSelect={setPageTab}
        />
      )}
      {imageUrl && pageTab === "image" ? (
        <div role="tabpanel" id="pagepanel-image" aria-labelledby="pagetab-image" tabIndex={0} className="page-view">
          <PageImage key={imageUrl} url={imageUrl} fileId={page.file_id} page={page.page} />
          <div className="page-view__passage">
            <p className="note">The part the {cited} came from, as the system read it:</p>
            <div className="page">{pageText(citedChunks.length > 0 ? citedChunks : page.chunks)}</div>
          </div>
        </div>
      ) : (
        <div role={imageUrl ? "tabpanel" : undefined} id="pagepanel-text" aria-labelledby={imageUrl ? "pagetab-text" : undefined} tabIndex={imageUrl ? 0 : undefined}>
          <p className="note">This is the text of the page as the system read it. The part the {cited} came from is highlighted in blue.</p>
          <div className="page">{pageText(page.chunks)}</div>
        </div>
      )}
    </section>
  );
}
