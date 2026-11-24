import type { AnswerOut, ChunkOut, PageOut } from "../api/types";
import { reportName } from "../lib/wording";
import { DayStrips } from "./DayStrips";

function where(chunk: ChunkOut): string {
  const page = chunk.page === null ? "" : `, page ${chunk.page}`;
  return `${reportName(chunk.file_id)}${page}`;
}

/** A passage of a report. Report text is set in the serif face everywhere, so it is never mistaken for the app's words. */
function Passage({ chunk, cited, onOpenPage }: { chunk: ChunkOut; cited: boolean; onOpenPage: (chunk: ChunkOut) => void }) {
  return (
    <article className={cited ? "passage passage--cited" : "passage"}>
      <header className="passage__where">
        <span>{where(chunk)}{chunk.section ? `: ${chunk.section}` : ""}</span>
        {cited && <span className="passage__flag">Cited in the answer</span>}
      </header>
      {chunk.text === null ? (
        <p className="passage__missing">This report is not loaded on this machine, so its text cannot be shown.</p>
      ) : (
        <p className="report-text">{chunk.text}</p>
      )}
      {chunk.page !== null && chunk.text !== null && (
        <button type="button" className="link" onClick={() => onOpenPage(chunk)}>Read the whole page</button>
      )}
    </article>
  );
}

interface Props {
  answer: AnswerOut;
  page: PageOut | null;
  pageChunk: string | null;
  onOpenPage: (chunk: ChunkOut) => void;
  onClosePage: () => void;
}

/** Everything the answer rests on, in the order it was used: computed operations, checked facts, passages read. */
export function Evidence({ answer, page, pageChunk, onOpenPage, onClosePage }: Props) {
  const { computed, facts, passages } = answer.evidence;
  const cited = new Set(answer.citations.map((c) => c.chunk_id));

  if (page) {
    return (
      <section className="evidence" aria-label="Evidence">
        <button type="button" className="link" onClick={onClosePage}>Back to the evidence</button>
        <h2>{reportName(page.file_id)}, page {page.page}</h2>
        <p className="note">The page as the report’s text was read. The page image is not available yet.</p>
        {page.chunks.map((chunk) => (
          <div key={chunk.chunk_id} className={chunk.chunk_id === pageChunk ? "page-chunk page-chunk--cited" : "page-chunk"}>
            {chunk.section && <p className="page-chunk__section">{chunk.section}</p>}
            <p className="report-text">{chunk.text}</p>
          </div>
        ))}
      </section>
    );
  }

  return (
    <section className="evidence" aria-label="Evidence">
      {computed && (
        <>
          <h2>Operations behind this number</h2>
          <p className="note">{computed.text}</p>
          <DayStrips events={computed.events} />
          <table className="data" aria-label="Operations">
            <thead>
              <tr><th>Date</th><th>From</th><th>To</th><th className="num">Hours</th><th>Code</th><th>Non-productive</th><th>Description</th></tr>
            </thead>
            <tbody>
              {computed.events.map((event, index) => (
                <tr key={index}>
                  <td>{event.date}</td><td>{event.start}</td><td>{event.end}</td><td className="num">{event.hours}</td>
                  <td>{event.code}</td><td>{event.npt_code ?? ""}</td><td className="report-text">{event.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {facts.length > 0 && (
        <>
          <h2>Checked facts the model was given</h2>
          <p className="note">Read from the reports’ tables and text, then checked in code: each value is written in its source passage.</p>
          <table className="data" aria-label="Checked facts">
            <thead>
              <tr><th>Well</th><th>Property</th><th className="num">Value</th><th>Applies to</th><th>Read by</th></tr>
            </thead>
            <tbody>
              {facts.map((fact, index) => (
                <tr key={index}>
                  <td>{fact.well}</td>
                  <td>{fact.property.replace(/_/g, " ")}{fact.qualifier !== "actual" && fact.qualifier !== "none" ? ` (${fact.qualifier})` : ""}</td>
                  <td className="num">{fact.value}{fact.unit ? ` ${fact.unit}` : ""}</td>
                  <td>{fact.context ? Object.entries(fact.context).map(([key, value]) => `${key.replace(/_/g, " ")} ${value}`).join(", ") : ""}</td>
                  <td>{fact.source === "table_mapping" ? "Table rule" : "Model, then checked"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {passages.length > 0 && (
        <>
          <h2>{answer.status === "answered" && !computed ? "Passages the model read" : computed ? "Passages holding these operations" : "Closest passages"}</h2>
          {passages.map((chunk) => (
            <Passage key={chunk.chunk_id} chunk={chunk} cited={cited.has(chunk.chunk_id)} onOpenPage={onOpenPage} />
          ))}
        </>
      )}

      {!computed && facts.length === 0 && passages.length === 0 && <p className="note">Nothing in the loaded reports matched this question.</p>}
    </section>
  );
}
