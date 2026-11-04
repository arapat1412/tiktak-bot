"""One reading of a TikTok For You payload, for the bridge and the Agent handler alike.

Two readers used to exist. The bridge read what the page sends; the Agent handler, which the CLI
runs, read an older subset: no comments, no reposts, no feed training, and a percentage of 1 read
as 100 %. The same config commented from the desktop and not from the CLI.

The settings every video workflow shares are read by `workflows/common/video_payload.py` (units by
vocabulary, defaults); this module adds the feed's own: training and follow-back suggestions.
"""

from __future__ import annotations

from typing import Any, Mapping

from taktik.core.social_media.tiktok.workflows.common.video_payload import (
    as_bool,
    as_int,
    first_given,
    keyword_list,
    video_settings_from_payload,
)

from taktik.core.social_media.tiktok.workflows.automation.for_you.models import ForYouConfig


def for_you_config_from_payload(payload: Mapping[str, Any]) -> ForYouConfig:
    """Build the workflow config from a bridge or Agent payload."""
    return ForYouConfig(
        **video_settings_from_payload(payload),
        browse_profile=payload.get("browseProfile", "standard"),
        run_duration_minutes=payload.get("runDurationMinutes", 0),
        warmup_videos=as_int(payload.get("warmupVideos"), 3),
        action_gap_videos=as_int(payload.get("actionGapVideos"), 2),
        rest_every_videos=as_int(payload.get("restEveryVideos"), 8),
        training_keywords=keyword_list(
            first_given(payload.get("trainingKeywords"), payload.get("training_keywords"))
        ),
        training_reject_off_niche=as_bool(
            first_given(payload.get("trainingRejectOffNiche"), payload.get("training_reject_off_niche")), True
        ),
        max_rejections_per_session=as_int(
            first_given(payload.get("maxRejectionsPerSession"), payload.get("max_rejections_per_session")), 20
        ),
        follow_back_suggestions=as_bool(
            first_given(payload.get("followBackSuggestions"), payload.get("follow_back_suggestions")), False
        ),
    )


__all__ = ["for_you_config_from_payload"]
