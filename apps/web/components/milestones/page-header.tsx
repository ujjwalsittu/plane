/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { Breadcrumbs } from "@plane/blocks/breadcrumb";
import { Header } from "@plane/blocks/layout";
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
import { CommonProjectBreadcrumbs } from "@/components/breadcrumbs/common";
import { useProjectCrumbProps } from "@/components/breadcrumbs/use-project-crumb-props";
import { useProject } from "@/hooks/store/use-project";

type Props = {
  label: string;
  icon: ReactNode;
  /** Path under the project, e.g. "milestones". */
  section: string;
  /** Extra crumb after the section (e.g. a milestone title). */
  current?: string;
  rightItem?: ReactNode;
};

/** Project-level page header with breadcrumbs, for the Milestones and Epics pages. */
export const ProjectSectionHeader = observer(function ProjectSectionHeader(props: Props) {
  const { label, icon, section, current, rightItem } = props;
  const { workspaceSlug, projectId } = useParams();
  const projectCrumb = useProjectCrumbProps(workspaceSlug?.toString(), projectId?.toString());
  const { loader } = useProject();

  return (
    <Header>
      <Header.LeftItem>
        <Breadcrumbs isLoading={loader === "init-loader"}>
          <CommonProjectBreadcrumbs
            workspaceSlug={workspaceSlug?.toString()}
            projectId={projectId?.toString()}
            {...projectCrumb}
          />
          <Breadcrumbs.Item
            component={
              <BreadcrumbLink
                label={label}
                href={`/${workspaceSlug}/projects/${projectId}/${section}/`}
                icon={icon}
                isLast={!current}
              />
            }
            isLast={!current}
          />
          {current && <Breadcrumbs.Item component={<BreadcrumbLink label={current} isLast />} isLast />}
        </Breadcrumbs>
      </Header.LeftItem>
      {rightItem && <Header.RightItem>{rightItem}</Header.RightItem>}
    </Header>
  );
});
