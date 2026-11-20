# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from .asset import urlpatterns as asset_patterns
from .cycle import urlpatterns as cycle_patterns
from .intake import urlpatterns as intake_patterns
from .label import urlpatterns as label_patterns
from .member import urlpatterns as member_patterns
from .module import urlpatterns as module_patterns
from .project import urlpatterns as project_patterns
from .state import urlpatterns as state_patterns
from .user import urlpatterns as user_patterns
from .work_item import urlpatterns as work_item_patterns
from .invite import urlpatterns as invite_patterns
from .sticky import urlpatterns as sticky_patterns
from .estimate import urlpatterns as estimate_patterns
from .work_item_relation import urlpatterns as work_item_relation_patterns
from .milestone import urlpatterns as milestone_patterns
from .page import urlpatterns as page_patterns
from .issue_property import urlpatterns as issue_property_patterns
from .work_log import urlpatterns as work_log_patterns
from .github import urlpatterns as github_patterns
from .initiative import urlpatterns as initiative_patterns
from .release import urlpatterns as release_patterns
from .template import urlpatterns as template_patterns
from .teamspace import urlpatterns as teamspace_patterns
from .work_item_count import urlpatterns as work_item_count_patterns

urlpatterns = [
    *work_item_count_patterns,
    *asset_patterns,
    *cycle_patterns,
    *intake_patterns,
    *label_patterns,
    *member_patterns,
    *module_patterns,
    *project_patterns,
    *state_patterns,
    *user_patterns,
    *work_item_patterns,
    *invite_patterns,
    *sticky_patterns,
    *estimate_patterns,
    *work_item_relation_patterns,
    *milestone_patterns,
    *page_patterns,
    *issue_property_patterns,
    *work_log_patterns,
    *github_patterns,
    *initiative_patterns,
    *release_patterns,
    *template_patterns,
    *teamspace_patterns,
]
