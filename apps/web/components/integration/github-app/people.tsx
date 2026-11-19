/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
import { InputField } from "@makeplane/propel/components/input-field";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import { useMember } from "@/hooks/store/use-member";
import { GitHubAppService } from "@/services/github-app.service";

const service = new GitHubAppService();

/** Each workspace member's GitHub login, so assignees sync between GitHub issues and work items. */
export const GitHubPeople = observer(function GitHubPeople({ workspaceSlug }: { workspaceSlug: string }) {
  const { t } = useTranslation();
  const {
    workspace: { workspaceMemberIds, getWorkspaceMemberDetails, fetchWorkspaceMembers },
  } = useMember();
  useSWR(`GITHUB_PEOPLE_MEMBERS_${workspaceSlug}`, () => fetchWorkspaceMembers(workspaceSlug));
  const { data: mappings, mutate } = useSWR(`GITHUB_PEOPLE_${workspaceSlug}`, () => service.listPeople(workspaceSlug));

  if (!mappings || !workspaceMemberIds) return null;
  const loginFor = (userId: string) => mappings.find((mapping) => mapping.user === userId)?.github_login ?? "";

  const save = async (userId: string, login: string) => {
    if (login.trim().replace(/^@/, "") === loginFor(userId)) return;
    try {
      await mutate(await service.setPerson(workspaceSlug, userId, login), { revalidate: false });
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error;
      setToast({ type: "error", title: message ?? t("github_app.save_error") });
    }
  };

  return (
    <section className="flex flex-col gap-3">
      <div>
        <h3 className="text-h5-medium text-primary">{t("github_app.people.title")}</h3>
        <p className="text-body-xs-regular text-tertiary">{t("github_app.people.description")}</p>
      </div>
      <div className="divide-y divide-subtle rounded-lg border border-subtle">
        {workspaceMemberIds.map((userId) => {
          const member = getWorkspaceMemberDetails(userId)?.member;
          if (!member) return null;
          return (
            <PersonRow
              key={`${userId}:${loginFor(userId)}`}
              name={member.display_name || member.first_name || member.email || userId}
              login={loginFor(userId)}
              onSave={(login) => void save(userId, login)}
            />
          );
        })}
      </div>
    </section>
  );
});

function PersonRow({ name, login, onSave }: { name: string; login: string; onSave: (login: string) => void }) {
  const { t } = useTranslation();
  const [value, setValue] = useState(login);
  return (
    <div className="flex flex-wrap items-center gap-3 px-4 py-2">
      <span className="min-w-40 flex-1 truncate text-body-sm-regular text-primary">{name}</span>
      <div className="w-64">
        <InputField
          size="md"
          orientation="vertical"
          value={value}
          maxLength={255}
          onChange={(e) => setValue(e.target.value)}
          onBlur={() => onSave(value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onSave(value);
          }}
          aria-label={t("github_app.people.login", { name })}
          placeholder={t("github_app.people.placeholder")}
        />
      </div>
    </div>
  );
}
