"""Opt-in, bounded feed pacing. UI observations are not server acknowledgements."""

import random
import time

from taktik.core.shared.diagnostics import run_halt
from taktik.core.shared.telemetry.sink import emit_step
from taktik.core.shared.text import as_xml_dumped
from taktik.core.social_media.tiktok.ui.selectors.surfaces.video import VIDEO_SELECTORS


class NaturalBrowsingMixin:
    """Leaves the legacy workflow unchanged unless explicitly selected in the payload."""

    def _natural_enabled(self):
        return getattr(self.config, "browse_profile", "standard") == "natural"

    def _reset_natural_session(self):
        minutes = getattr(self.config, "run_duration_minutes", 0)
        self._natural_deadline = time.monotonic() + minutes * 60 if self._natural_enabled() and minutes else None
        self._natural_last_attempt = None
        self._natural_seen = set()
        self._natural_followed = set()
        self._natural_used_comments = set()

    def _timed_browsing(self):
        return self._natural_enabled() and bool(getattr(self.config, "run_duration_minutes", 0))

    def _duration_expired(self):
        deadline = getattr(self, "_natural_deadline", None)
        if deadline is None or self._halted():
            return False
        if self.stats.completion_reason:
            return self.stats.completion_reason == "duration_limit"
        if time.monotonic() < deadline:
            return False
        self.stats.completion_reason = "duration_limit"
        self._running = False
        self.logger.info("Đã đủ thời gian lướt đã cài đặt, kết thúc phiên.")
        return True

    def _natural_wait(self, seconds, honor_duration=True):
        deadline = time.monotonic() + seconds
        while self._running and not self._halted():
            if honor_duration and self._duration_expired():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            time.sleep(min(0.2, remaining))
        return False

    def _check_limits_reached(self):
        if self._duration_expired():
            return True
        if self._natural_enabled() and not self._halted():
            # Each action checks its own quota; a quota does not end viewing early.
            return False
        return super()._check_limits_reached()

    def _check_pause_needed(self):
        if not self._natural_enabled():
            return super()._check_pause_needed()
        if self._duration_expired():
            return
        n = self.stats.videos_watched
        if (
            not self._running
            or self._halted()
            or (not self._timed_browsing() and n >= self.config.max_videos)
            or not n
            or n % self.config.rest_every_videos
        ):
            return
        seconds = self._pause_length()
        if self._on_pause_callback:
            try:
                self._on_pause_callback(int(seconds))
            except Exception as exc:
                self.logger.warning(f"Pause callback error: {exc}")
        self._natural_wait(seconds)

    @staticmethod
    def _natural_identity(info):
        # Exclude like counts, which can change after a tap or through another viewer.
        # This is an in-session UI identity, not a durable TikTok video id.
        return (info.get("author") or "", info.get("description") or "")

    def _natural_read(self):
        screen = self.detection.read_screen()
        if screen.kind != "video" or not screen.for_you:
            return None, screen
        return (
            self.detection.get_video_info(screen=screen, full_description=False),
            screen,
        )

    def _natural_uncertain(self, action):
        run_halt.demander_arret(
            "interaction_unconfirmed", f"Cannot confirm {action}; do not retry"
        )
        self.stats.completion_reason = run_halt.arret_demande()["code"]
        self._running = False

    def _decide_and_execute_actions(self, video_info):
        if not self._natural_enabled():
            return super()._decide_and_execute_actions(video_info)
        cfg, stats = self.config, self.stats
        n = stats.videos_watched
        last = self._natural_last_attempt
        if (
            not self._running
            or self._halted()
            or self._duration_expired()
            or n <= cfg.warmup_videos
            or (last is not None and n - last <= cfg.action_gap_videos)
        ):
            return
        key = self._natural_identity(video_info)
        if not all(key) or key in self._natural_seen:
            return
        texts = list(dict.fromkeys(t.strip() for t in cfg.comment_texts if t.strip()))
        texts = [t for t in texts if t not in self._natural_used_comments]
        candidates = []
        if stats.videos_liked < cfg.max_likes_per_session and not video_info.get(
            "is_liked"
        ):
            candidates.append(("like", cfg.like_probability))
        if (
            stats.users_followed < cfg.max_follows_per_session
            and key[0] not in self._natural_followed
        ):
            candidates.append(("follow", cfg.follow_probability))
        if stats.videos_commented < cfg.max_comments_per_session and texts:
            candidates.append(("comment", cfg.comment_probability))
        random.shuffle(candidates)
        for action, probability in candidates:
            if probability <= 0 or random.random() >= probability:
                continue
            # Re-read after viewing, before any public action. An unexpected screen is skipped.
            current, screen = self._natural_read()
            if current is None or self._natural_identity(current) != key:
                return
            if action == "like" and current.get("is_liked"):
                continue
            if action == "follow" and not self.detection._element_exists(
                VIDEO_SELECTORS.follow_button, screen=screen
            ):
                continue
            if not self._running or self._halted():
                return
            if self._duration_expired():
                return
            if self._stop_if_action_blocked(key[0], action):
                return
            if self._duration_expired():
                return
            self._natural_last_attempt = n
            self._natural_seen.add(key)
            self._current_video_author = key[0]
            try:
                confirmed = (
                    self._natural_comment(random.choice(texts))
                    if action == "comment"
                    else self._natural_tap(action, key)
                )
            except Exception as exc:
                self.logger.warning(f"Interaction verification failed: {exc}")
                confirmed = False
            if not confirmed:
                if not self._halted():
                    self._natural_uncertain(action)
                return
            field = {
                "like": "videos_liked",
                "follow": "users_followed",
                "comment": "videos_commented",
            }[action]
            setattr(stats, field, getattr(stats, field) + 1)
            if action == "follow":
                self._natural_followed.add(key[0])
            emit_step(action, action="verified_ui", target=key[0])
            self._send_stats_update()
            callback = getattr(self, f"_on_{action}_callback", None)
            if callback:
                try:
                    callback(video_info)
                except Exception as exc:
                    self.logger.warning(f"Interaction callback error: {exc}")
            return  # At most one public action on a video, including failed attempts.

    def _natural_click_once(self, action):
        from taktik.core.shared.behavior.tap import tap_element_human
        from taktik.core.social_media.tiktok.actions.base.utils import first_matching

        selectors = (
            VIDEO_SELECTORS.like_button
            if action == "like"
            else VIDEO_SELECTORS.follow_button
        )
        elements = first_matching(self.click.device, selectors)
        # A failed injection may already have reached Android. Never centre-click or
        # try another selector after attempting this public gesture.
        return bool(elements) and tap_element_human(
            self.click.device, elements[0], logger=self.logger
        )

    def _natural_tap(self, action, key):
        if not self._natural_click_once(action):
            return False
        if self._stop_if_action_blocked(key[0], action):
            return False
        for _ in range(4):
            if not self._natural_wait(0.5, honor_duration=False):
                return False
            info, screen = self._natural_read()
            if info is None or self._natural_identity(info) != key:
                return False
            if action == "like" and info.get("is_liked"):
                return True
            if action == "follow" and not self.detection._element_exists(
                VIDEO_SELECTORS.follow_button, screen=screen
            ):
                return True
        return False

    def _natural_comment(self, text):
        """Send once; require a new visible row AND an observed empty composer."""
        from taktik.core.social_media.tiktok.actions.base.utils import first_matching
        from taktik.core.social_media.tiktok.actions.atomic.interaction.comment_actions import (
            comment_composer_is_empty,
        )

        actions = self._comment_actions()
        if actions is None or not actions.open_comments():
            return False
        normalized = as_xml_dumped(text).strip()

        def matching_rows():
            return sum(
                as_xml_dumped(row.get("text") or "").strip() == normalized
                for row in actions.read_comments(max_comments=50)
            )

        before = matching_rows()
        self._natural_used_comments.add(text)
        if not self._running or self._halted():
            return False
        if not actions.post_comment(text, single_attempt=True):
            return False
        for _ in range(4):
            if not self._natural_wait(0.5, honor_duration=False):
                return False
            if self._stop_if_action_blocked(self._current_video_author, "comment"):
                return False
            if not actions.is_comment_sheet_open():
                return False
            inputs = first_matching(
                actions.device, actions.comment_selectors.comment_input
            )
            # Missing fields are unknown, never proof that the composer emptied.
            if (
                comment_composer_is_empty(inputs)
                and matching_rows() > before
            ):
                self._record_posted_comment(text)
                return actions.close_comments()
        return False  # Leave the uncertain sheet for the operator; never resend.
