/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo } from "react";
import { Avatar } from "@makeplane/propel/components/avatar";
import { getFileURL } from "@plane/utils";
import { useMember } from "@/hooks/store/use-member";

export const getTeamsKey = (workspaceSlug: string) => `TEAMS_${workspaceSlug}`;
export const getTeamKey = (teamId: string) => `TEAM_${teamId}`;

export type TMemberOption = { id: string; name: string; avatar: string };

/** Active workspace members as select options, by display name. */
export function useMemberOptions(): TMemberOption[] {
  const {
    workspace: { workspaceMemberIds, getWorkspaceMemberDetails },
  } = useMember();
  return useMemo(
    () =>
      (workspaceMemberIds ?? [])
        .map((id) => getWorkspaceMemberDetails(id)?.member)
        .filter((m): m is NonNullable<typeof m> => !!m)
        .map((m) => ({
          id: m.id,
          name: m.display_name || m.first_name || m.id,
          avatar: m.avatar_url ?? "",
        }))
        .sort((a, b) => a.name.localeCompare(b.name)),
    [workspaceMemberIds, getWorkspaceMemberDetails]
  );
}

export function MemberAvatar({ member, size = "sm" }: { member?: TMemberOption; size?: "2xs" | "xs" | "sm" }) {
  if (!member) return null;
  return (
    <Avatar
      alt={member.name}
      fallback={member.name[0]?.toUpperCase()}
      src={getFileURL(member.avatar)}
      size={size}
      tooltip={member.name}
    />
  );
}
