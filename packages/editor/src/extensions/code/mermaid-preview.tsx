/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useId, useRef, useState } from "react";

type MermaidApi = typeof import("mermaid").default;

let mermaidPromise: Promise<MermaidApi> | null = null;
let initializedTheme: string | null = null;

/** Mermaid is large, so it loads only when a page has a Mermaid block. */
const loadMermaid = () => {
  mermaidPromise ??= import("mermaid").then((module) => module.default);
  return mermaidPromise;
};

const currentTheme = () => {
  if (typeof document === "undefined") return "default";
  const root = document.documentElement;
  const dark =
    root.classList.contains("dark") ||
    root.dataset.theme?.includes("dark") ||
    (!root.dataset.theme && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  return dark ? "dark" : "default";
};

type Props = {
  code: string;
};

/** Renders a Mermaid diagram from source; shows the error inline if it doesn't parse. */
export function MermaidPreview({ code }: Props) {
  const reactId = useId();
  const id = `mermaid-${reactId.replace(/[^a-zA-Z0-9]/g, "")}`;
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const source = code.trim();
    if (!source) {
      if (containerRef.current) containerRef.current.innerHTML = "";
      setError(null);
      return;
    }
    let cancelled = false;
    const draw = async () => {
      try {
        const mermaid = await loadMermaid();
        const theme = currentTheme();
        if (initializedTheme !== theme) {
          // strict: no scripts or click handlers in diagrams; output is sanitised.
          mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme });
          initializedTheme = theme;
        }
        const { svg } = await mermaid.render(id, source);
        if (cancelled || !containerRef.current) return;
        containerRef.current.innerHTML = svg;
        setError(null);
      } catch (err: unknown) {
        // Mermaid leaves an error node in the body when render fails.
        document.getElementById(`d${id}`)?.remove();
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    };
    // Debounced so typing doesn't re-render on every keystroke.
    const timer = setTimeout(() => void draw(), 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [code, id]);

  return (
    <div className="mermaid-preview" contentEditable={false}>
      <div ref={containerRef} className="flex justify-center overflow-x-auto [&_svg]:h-auto [&_svg]:max-w-full" />
      {error && (
        <p className="font-mono mt-2 rounded-md bg-layer-2 px-3 py-2 text-caption-sm-regular whitespace-pre-wrap text-danger-primary">
          {error}
        </p>
      )}
    </div>
  );
}
