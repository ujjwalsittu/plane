/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import type { TFilterProperty, TIssueType, TMilestone, TSupportedOperators } from "@plane/types";
import { EQUALITY_OPERATOR, COLLECTION_OPERATOR } from "@plane/types";
// local imports
import type { TCreateFilterConfigParams, IFilterIconConfig, TCreateFilterConfig } from "../../../rich-filters";
import { createFilterConfig, getMultiSelectConfig, createOperatorConfigEntry } from "../../../rich-filters";

export type TCreateMilestoneFilterParams = TCreateFilterConfigParams &
  IFilterIconConfig<TMilestone> & {
    milestones: TMilestone[];
  };

export const getMilestoneMultiSelectConfig = (
  params: TCreateMilestoneFilterParams,
  singleValueOperator: TSupportedOperators
) =>
  getMultiSelectConfig<TMilestone, string, TMilestone>(
    {
      items: params.milestones,
      getId: (milestone) => milestone.id,
      getLabel: (milestone) => milestone.title,
      getValue: (milestone) => milestone.id,
      getIconData: (milestone) => milestone,
    },
    {
      singleValueOperator,
      ...params,
    },
    {
      ...params,
    }
  );

export const getMilestoneFilterConfig =
  <P extends TFilterProperty>(key: P): TCreateFilterConfig<P, TCreateMilestoneFilterParams> =>
  (params: TCreateMilestoneFilterParams) =>
    createFilterConfig<P>({
      id: key,
      label: "Milestone",
      ...params,
      icon: params.filterIcon,
      supportedOperatorConfigsMap: new Map([
        createOperatorConfigEntry(COLLECTION_OPERATOR.IN, params, (updatedParams) =>
          getMilestoneMultiSelectConfig(updatedParams, EQUALITY_OPERATOR.EXACT)
        ),
      ]),
    });

export type TCreateIssueTypeFilterParams = TCreateFilterConfigParams &
  IFilterIconConfig<TIssueType> & {
    issueTypes: TIssueType[];
  };

export const getIssueTypeMultiSelectConfig = (
  params: TCreateIssueTypeFilterParams,
  singleValueOperator: TSupportedOperators
) =>
  getMultiSelectConfig<TIssueType, string, TIssueType>(
    {
      items: params.issueTypes,
      getId: (issueType) => issueType.id,
      getLabel: (issueType) => issueType.name,
      getValue: (issueType) => issueType.id,
      getIconData: (issueType) => issueType,
    },
    {
      singleValueOperator,
      ...params,
    },
    {
      ...params,
    }
  );

export const getIssueTypeFilterConfig =
  <P extends TFilterProperty>(key: P): TCreateFilterConfig<P, TCreateIssueTypeFilterParams> =>
  (params: TCreateIssueTypeFilterParams) =>
    createFilterConfig<P>({
      id: key,
      label: "Type",
      ...params,
      icon: params.filterIcon,
      supportedOperatorConfigsMap: new Map([
        createOperatorConfigEntry(COLLECTION_OPERATOR.IN, params, (updatedParams) =>
          getIssueTypeMultiSelectConfig(updatedParams, EQUALITY_OPERATOR.EXACT)
        ),
      ]),
    });
