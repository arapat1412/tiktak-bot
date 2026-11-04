"""Data models for the TikTok For You workflow."""

from typing import Optional, List
from dataclasses import dataclass, field
import math


@dataclass
class ForYouConfig:
    """Configuration of the For You workflow."""

    
    # Nombre de vidéos à traiter
    max_videos: int = 50
    
    # Temps de visionnage (secondes)
    min_watch_time: float = 2.0
    max_watch_time: float = 8.0
    
    # Probabilités d'action (0.0 à 1.0)
    like_probability: float = 0.3
    follow_probability: float = 0.1
    favorite_probability: float = 0.05
    #: Commenting reached this road on 2026-08-30, through the shared `VideoCommentMixin`. Zero
    #: by default: a feed run that never asked to comment must behave exactly as it did before.
    #: Republier une video sur notre propre profil. TikTok n'a pas d'equivalent Instagram :
    #: c'est a la fois un signal fort a l'auteur et de quoi nourrir un profil qui n'a rien publie.
    #: Entrainer la For You page. Les mots decrivent la niche voulue ; une video qui n'en porte
    #: aucun recoit le seul signal negatif explicite que TikTok expose (« Pas interesse(e) »).
    #: Vide = mode inactif, et le workflow se comporte exactement comme avant.
    training_keywords: List[str] = field(default_factory=list)
    #: Rejeter explicitement, ou se contenter de passer vite. Le rejet est visible dans
    #: l'historique « pas interesse » du compte : ce n'est pas anodin sur un compte client.
    training_reject_off_niche: bool = True
    max_rejections_per_session: int = 20
    repost_probability: float = 0.0
    max_reposts_per_session: int = 5
    comment_probability: float = 0.0
    max_comments_per_session: int = 10
    #: The run's own comment texts. Empty and never defaulted to a built-in list — a generic
    #: "Nice!" under a stranger's video is the most recognisable bot signature there is.
    comment_texts: List[str] = field(default_factory=list)
    
    # Filtres
    min_likes: Optional[int] = None  # Minimum likes required to interact
    max_likes: Optional[int] = None  # Maximum likes allowed to interact
    required_hashtags: List[str] = field(default_factory=list)  # Hashtags requis
    excluded_hashtags: List[str] = field(default_factory=list)  # Hashtags exclus
    
    # Limites de session
    max_likes_per_session: int = 50
    max_follows_per_session: int = 20
    
    # Pauses
    pause_after_actions: int = 10  # Pause après N actions
    pause_duration_min: float = 30.0
    pause_duration_max: float = 60.0
    
    # Comportement
    skip_already_liked: bool = True
    skip_already_followed: bool = True
    skip_ads: bool = True  # Skip the ads automatically
    follow_back_suggestions: bool = False  # When true, follow back the suggestions; otherwise mark them as not interesting

    # Append fields to preserve positional construction by existing callers.
    browse_profile: str = "standard"
    warmup_videos: int = 3
    action_gap_videos: int = 2
    rest_every_videos: int = 8
    run_duration_minutes: int = 0

    def __post_init__(self):
        if (not isinstance(self.run_duration_minutes, int)
                or isinstance(self.run_duration_minutes, bool)
                or not 0 <= self.run_duration_minutes <= 1440):
            raise ValueError("Invalid browsing duration in minutes")
        if self.run_duration_minutes and self.browse_profile != "natural":
            raise ValueError("Timed browsing requires the natural profile")
        if self.browse_profile not in ("standard", "natural"):
            raise ValueError("Unknown browse profile")
        if self.browse_profile != "natural":
            return
        for value, minimum in ((self.warmup_videos, 0), (self.action_gap_videos, 0),
                               (self.rest_every_videos, 1)):
            if not isinstance(value, int) or not minimum <= value <= 1000:
                raise ValueError("Invalid natural browsing interval")
        for low, high in ((self.min_watch_time, self.max_watch_time),
                          (self.pause_duration_min, self.pause_duration_max)):
            if not (math.isfinite(low) and math.isfinite(high) and 0.1 <= low <= high <= 3600):
                raise ValueError("Invalid natural browsing duration")
