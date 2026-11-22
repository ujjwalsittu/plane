/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Fragment, useRef, useState } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { Button } from "@makeplane/propel/components/button";
import { Input } from "@makeplane/propel/components/input";
import { useTranslation } from "@plane/i18n";
import type { TAskSource, TAskTurn } from "@plane/types";
import { SupervisionService } from "@/services/supervision.service";

const service = new SupervisionService();

/** The server keeps at most this many earlier turns as context. */
const MAX_HISTORY = 10;
const MAX_QUESTION = 2000;

type TExchange = { id: number; question: string; answer: string; sources: TAskSource[] };

const linkClass = "font-medium text-accent-primary hover:underline";

function SourceLink({ source, children }: { source: TAskSource; children: string }) {
  if (source.url.startsWith("/")) {
    return (
      <Link href={source.url} className={linkClass}>
        {children}
      </Link>
    );
  }
  return (
    <a href={source.url} target="_blank" rel="noopener noreferrer" className={linkClass}>
      {children}
    </a>
  );
}

/** Turns each `[ID]` the answer cites into a link to that source; anything else stays text. */
function renderAnswer(answer: string, sources: TAskSource[]) {
  const byIdentifier = new Map<string, TAskSource>();
  for (const source of sources) {
    if (source.identifier) byIdentifier.set(source.identifier.toUpperCase(), source);
  }
  let offset = 0;
  return answer.split(/(\[[^\]\n]{1,80}\])/).map((part) => {
    const key = `${offset}:${part}`;
    offset += part.length;
    const source = part.startsWith("[") ? byIdentifier.get(part.slice(1, -1).toUpperCase()) : undefined;
    return source ? (
      <SourceLink key={key} source={source}>
        {part.slice(1, -1)}
      </SourceLink>
    ) : (
      <Fragment key={key}>{part}</Fragment>
    );
  });
}

/** "Ask your workspace": a question box on the Brief, answered from what the person can see. */
export function BriefAsk({ workspaceSlug }: { workspaceSlug: string }) {
  const { t } = useTranslation();
  const [question, setQuestion] = useState("");
  const [exchanges, setExchanges] = useState<TExchange[]>([]);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nextId = useRef(0);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const text = question.trim();
    if (!text || asking) return;
    const history: TAskTurn[] = exchanges
      .flatMap((exchange): TAskTurn[] => [
        { role: "user", content: exchange.question },
        { role: "assistant", content: exchange.answer },
      ])
      .slice(-MAX_HISTORY);
    setAsking(true);
    setError(null);
    try {
      const result = await service.ask(workspaceSlug, text, history);
      const id = (nextId.current += 1);
      setExchanges((previous) => [...previous, { id, question: text, answer: result.answer, sources: result.sources }]);
      setQuestion("");
    } catch (e) {
      setError((e as { error?: string } | undefined)?.error ?? t("agents.ask.error"));
    } finally {
      setAsking(false);
    }
  };

  const reset = () => {
    setExchanges([]);
    setError(null);
  };

  return (
    <section className="flex flex-col gap-3 rounded-md border border-subtle bg-layer-1 p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-body-sm-medium text-primary">{t("agents.ask.title")}</h2>
        {exchanges.length > 0 && (
          <Button variant="ghost" size="sm" stretch="auto" label={t("agents.ask.clear")} onClick={reset} />
        )}
      </div>
      {exchanges.map((exchange) => (
        <div key={exchange.id} className="flex flex-col gap-1">
          <p className="text-body-sm-medium text-secondary">{exchange.question}</p>
          <p className="text-body-sm-regular whitespace-pre-wrap text-primary">
            {renderAnswer(exchange.answer, exchange.sources)}
          </p>
          {/* Pages and milestones have no [ID] to link in the text, so they are listed under the answer. */}
          {exchange.sources.some((source) => !source.identifier) && (
            <ul className="flex flex-wrap gap-x-3 gap-y-1 text-caption-md-regular">
              {exchange.sources
                .filter((source) => !source.identifier)
                .map((source) => (
                  <li key={`${source.kind}:${source.id}`}>
                    <SourceLink source={source}>{source.title}</SourceLink>
                  </li>
                ))}
            </ul>
          )}
        </div>
      ))}
      {asking && <p className="text-body-sm-regular text-tertiary">{t("agents.ask.thinking")}</p>}
      {error && <p className="text-body-sm-regular text-danger-primary">{error}</p>}
      <form className="flex items-center gap-2" onSubmit={(event) => void submit(event)}>
        <div className="min-w-0 flex-1">
          <Input
            size="md"
            aria-label={t("agents.ask.title")}
            placeholder={exchanges.length ? t("agents.ask.follow_up_placeholder") : t("agents.ask.placeholder")}
            autoComplete="off"
            maxLength={MAX_QUESTION}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
        </div>
        <Button
          variant="primary"
          size="md"
          stretch="auto"
          type="submit"
          loading={asking}
          disabled={!question.trim()}
          label={t("agents.ask.submit")}
        />
      </form>
      <p className="text-caption-md-regular text-tertiary">{t("agents.ask.hint")}</p>
    </section>
  );
}
