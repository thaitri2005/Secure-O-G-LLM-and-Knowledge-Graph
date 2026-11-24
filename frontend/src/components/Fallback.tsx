import { Component, type ReactNode } from "react";

/** Whatever goes wrong while drawing the application, the person sees a message and a way out, never a blank page. */
export class Fallback extends Component<{ children: ReactNode }, { broken: boolean }> {
  state = { broken: false };

  static getDerivedStateFromError() {
    return { broken: true };
  }

  render() {
    if (!this.state.broken) return this.props.children;
    return (
      <main className="start" role="alert">
        <div className="card start__loaded">
          <h1>Something went wrong on this page</h1>
          <p className="note">Your questions are not lost. Reload the page to continue; if the problem stays, tell the person who shared this link.</p>
          <button type="button" className="button" onClick={() => window.location.reload()}>Reload the page</button>
        </div>
      </main>
    );
  }
}
