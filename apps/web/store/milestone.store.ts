/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { sortBy } from "lodash-es";
import { action, makeObservable, observable, runInAction } from "mobx";
import { computedFn } from "mobx-utils";
import type { TIssueType, TIssueTypeFormData, TMilestone, TMilestoneFormData } from "@plane/types";
import { MilestoneService } from "@/services/milestone.service";
import type { CoreRootStore } from "./root.store";

export interface IMilestoneStore {
  // observables
  milestoneMap: Record<string, TMilestone>;
  issueTypeMap: Record<string, TIssueType>;
  projectMilestoneIds: Record<string, string[]>;
  projectIssueTypeIds: Record<string, string[]>;
  // getters
  getMilestoneById: (milestoneId: string | null | undefined) => TMilestone | undefined;
  getProjectMilestones: (projectId: string | null | undefined) => TMilestone[] | undefined;
  getIssueTypeById: (issueTypeId: string | null | undefined) => TIssueType | undefined;
  getProjectIssueTypes: (projectId: string | null | undefined) => TIssueType[] | undefined;
  getProjectEpicTypeIds: (projectId: string | null | undefined) => string[];
  // milestone actions
  fetchMilestones: (workspaceSlug: string, projectId: string) => Promise<TMilestone[]>;
  ensureMilestones: (workspaceSlug: string, projectId: string) => Promise<void>;
  ensureIssueTypes: (workspaceSlug: string, projectId: string) => Promise<void>;
  fetchMilestone: (workspaceSlug: string, projectId: string, milestoneId: string) => Promise<TMilestone>;
  createMilestone: (workspaceSlug: string, projectId: string, data: Partial<TMilestoneFormData>) => Promise<TMilestone>;
  updateMilestone: (
    workspaceSlug: string,
    projectId: string,
    milestoneId: string,
    data: Partial<TMilestoneFormData>
  ) => Promise<TMilestone>;
  deleteMilestone: (workspaceSlug: string, projectId: string, milestoneId: string) => Promise<void>;
  // issue type actions
  fetchIssueTypes: (workspaceSlug: string, projectId: string) => Promise<TIssueType[]>;
  createIssueType: (workspaceSlug: string, projectId: string, data: Partial<TIssueTypeFormData>) => Promise<TIssueType>;
  updateIssueType: (
    workspaceSlug: string,
    projectId: string,
    issueTypeId: string,
    data: Partial<TIssueType>
  ) => Promise<TIssueType>;
  deleteIssueType: (workspaceSlug: string, projectId: string, issueTypeId: string) => Promise<void>;
}

export class MilestoneStore implements IMilestoneStore {
  milestoneMap: Record<string, TMilestone> = {};
  issueTypeMap: Record<string, TIssueType> = {};
  projectMilestoneIds: Record<string, string[]> = {};
  projectIssueTypeIds: Record<string, string[]> = {};
  service = new MilestoneService();
  rootStore: CoreRootStore;
  // In-flight loads, so many dropdowns mounting at once share one request.
  private pendingLoads = new Map<string, Promise<void>>();

  constructor(rootStore: CoreRootStore) {
    makeObservable(this, {
      milestoneMap: observable,
      issueTypeMap: observable,
      projectMilestoneIds: observable,
      projectIssueTypeIds: observable,
      fetchMilestones: action,
      fetchMilestone: action,
      createMilestone: action,
      updateMilestone: action,
      deleteMilestone: action,
      fetchIssueTypes: action,
      createIssueType: action,
      updateIssueType: action,
      deleteIssueType: action,
    });
    this.rootStore = rootStore;
  }

  // getters
  getMilestoneById = computedFn((milestoneId: string | null | undefined) =>
    milestoneId ? this.milestoneMap[milestoneId] : undefined
  );

  getProjectMilestones = computedFn((projectId: string | null | undefined) => {
    if (!projectId || !this.projectMilestoneIds[projectId]) return undefined;
    const milestones = this.projectMilestoneIds[projectId]
      .map((id) => this.milestoneMap[id])
      .filter((milestone): milestone is TMilestone => !!milestone);
    return sortBy(milestones, [(m) => m.sort_order, (m) => m.target_date ?? "9999", (m) => m.created_at]);
  });

  getIssueTypeById = computedFn((issueTypeId: string | null | undefined) =>
    issueTypeId ? this.issueTypeMap[issueTypeId] : undefined
  );

  getProjectIssueTypes = computedFn((projectId: string | null | undefined) => {
    if (!projectId || !this.projectIssueTypeIds[projectId]) return undefined;
    return this.projectIssueTypeIds[projectId]
      .map((id) => this.issueTypeMap[id])
      .filter((issueType): issueType is TIssueType => !!issueType);
  });

  getProjectEpicTypeIds = computedFn((projectId: string | null | undefined) =>
    (this.getProjectIssueTypes(projectId) ?? []).filter((t) => t.is_epic).map((t) => t.id)
  );

  // helpers
  private upsertMilestone(projectId: string, milestone: TMilestone) {
    this.milestoneMap[milestone.id] = milestone;
    const ids = this.projectMilestoneIds[projectId] ?? [];
    if (!ids.includes(milestone.id)) this.projectMilestoneIds[projectId] = [...ids, milestone.id];
  }

  private upsertIssueType(projectId: string, issueType: TIssueType) {
    this.issueTypeMap[issueType.id] = issueType;
    const ids = this.projectIssueTypeIds[projectId] ?? [];
    if (!ids.includes(issueType.id)) this.projectIssueTypeIds[projectId] = [...ids, issueType.id];
  }

  private loadOnce(key: string, load: () => Promise<unknown>) {
    let pending = this.pendingLoads.get(key);
    if (!pending) {
      pending = load()
        .then(() => undefined)
        .finally(() => this.pendingLoads.delete(key));
      this.pendingLoads.set(key, pending);
    }
    return pending;
  }

  /** Loads a project's milestones unless they are already in the store. */
  ensureMilestones = async (workspaceSlug: string, projectId: string) => {
    if (this.projectMilestoneIds[projectId]) return;
    await this.loadOnce(`milestones:${projectId}`, () => this.fetchMilestones(workspaceSlug, projectId));
  };

  /** Loads a project's work item types unless they are already in the store. */
  ensureIssueTypes = async (workspaceSlug: string, projectId: string) => {
    if (this.projectIssueTypeIds[projectId]) return;
    await this.loadOnce(`issue-types:${projectId}`, () => this.fetchIssueTypes(workspaceSlug, projectId));
  };

  // milestone actions
  fetchMilestones = async (workspaceSlug: string, projectId: string) => {
    const milestones = await this.service.list(workspaceSlug, projectId);
    runInAction(() => {
      milestones.forEach((m) => (this.milestoneMap[m.id] = m));
      this.projectMilestoneIds[projectId] = milestones.map((m) => m.id);
    });
    return milestones;
  };

  fetchMilestone = async (workspaceSlug: string, projectId: string, milestoneId: string) => {
    const milestone = await this.service.retrieve(workspaceSlug, projectId, milestoneId);
    runInAction(() => this.upsertMilestone(projectId, milestone));
    return milestone;
  };

  createMilestone = async (workspaceSlug: string, projectId: string, data: Partial<TMilestoneFormData>) => {
    const milestone = await this.service.create(workspaceSlug, projectId, data);
    runInAction(() => this.upsertMilestone(projectId, milestone));
    return milestone;
  };

  updateMilestone = async (
    workspaceSlug: string,
    projectId: string,
    milestoneId: string,
    data: Partial<TMilestoneFormData>
  ) => {
    const milestone = await this.service.update(workspaceSlug, projectId, milestoneId, data);
    runInAction(() => this.upsertMilestone(projectId, milestone));
    return milestone;
  };

  deleteMilestone = async (workspaceSlug: string, projectId: string, milestoneId: string) => {
    await this.service.remove(workspaceSlug, projectId, milestoneId);
    runInAction(() => {
      delete this.milestoneMap[milestoneId];
      this.projectMilestoneIds[projectId] = (this.projectMilestoneIds[projectId] ?? []).filter(
        (id) => id !== milestoneId
      );
    });
  };

  // issue type actions
  fetchIssueTypes = async (workspaceSlug: string, projectId: string) => {
    const issueTypes = await this.service.listIssueTypes(workspaceSlug, projectId);
    runInAction(() => {
      issueTypes.forEach((t) => (this.issueTypeMap[t.id] = t));
      this.projectIssueTypeIds[projectId] = issueTypes.map((t) => t.id);
    });
    return issueTypes;
  };

  createIssueType = async (workspaceSlug: string, projectId: string, data: Partial<TIssueTypeFormData>) => {
    const issueType = await this.service.createIssueType(workspaceSlug, projectId, data);
    runInAction(() => this.upsertIssueType(projectId, issueType));
    return issueType;
  };

  updateIssueType = async (
    workspaceSlug: string,
    projectId: string,
    issueTypeId: string,
    data: Partial<TIssueType>
  ) => {
    const issueType = await this.service.updateIssueType(workspaceSlug, projectId, issueTypeId, data);
    runInAction(() => {
      this.upsertIssueType(projectId, issueType);
      if (issueType.is_default)
        (this.projectIssueTypeIds[projectId] ?? []).forEach((id) => {
          const other = this.issueTypeMap[id];
          if (other && id !== issueType.id && other.is_default) this.issueTypeMap[id] = { ...other, is_default: false };
        });
    });
    return issueType;
  };

  deleteIssueType = async (workspaceSlug: string, projectId: string, issueTypeId: string) => {
    await this.service.deleteIssueType(workspaceSlug, projectId, issueTypeId);
    runInAction(() => {
      delete this.issueTypeMap[issueTypeId];
      this.projectIssueTypeIds[projectId] = (this.projectIssueTypeIds[projectId] ?? []).filter(
        (id) => id !== issueTypeId
      );
    });
  };
}
