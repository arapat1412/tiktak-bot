"""L'orchestration de la détection de langue, une fois pour les deux plateformes.

`language_engine` porte déjà le moteur de scoring — c'est la moitié qui avait été mutualisée.
L'autre moitié, l'orchestration autour de lui, était restée **en double** : sept fonctions dans
`instagram/ui/language.py` et sept dans `tiktok/ui/language.py`, dont quatre identiques caractère
pour caractère.

Ce qui différait légitimement était de la **donnée** — les vocabulaires `_FR_WORDS` / `_EN_WORDS`,
propres à chaque application. C'est exactement la distinction que l'invariant du projet énonce :
une différence de plateforme est une donnée, pas une branche de code.

**Trois leçons avaient été apprises d'un seul côté**, et la fusion les porte aux deux :

1. TikTok **dérivait** la liste des catalogues à optimiser depuis le barrel ; Instagram en tenait
   une liste **écrite à la main**. Mesuré avant de fusionner : la liste manuelle **ratait trois
   catalogues** (`DISCOVER_PEOPLE`, `FEED_SUGGESTIONS`, `SETTINGS`), dont les sélecteurs de l'autre
   langue n'étaient donc jamais filtrés — et elle en optimisait un **deux fois**, `POST_SELECTORS`
   étant un alias de `POST_DETAIL_SELECTORS`.
2. Instagram acceptait `override` contre `available_locales()` ; TikTok contre un `("en", "fr")`
   figé, qui aurait rejeté toute nouvelle locale.
3. Instagram enregistrait la langue forcée dans son état ; TikTok ne le faisait pas, si bien que
   `get_detected_language()` rendait `None` après un override.

**Le piège de ce regroupement, et sa réponse.** Chaque module portait son propre `_detected_lang`
global. Ils doivent rester **séparés** : un même téléphone peut afficher Instagram en français et
TikTok en anglais. L'état vit donc dans l'**instance** — une par plateforme — et non dans le
module. Une variable partagée aurait fait passer la langue d'une application à l'autre.
"""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from loguru import logger

from taktik.core.shared.ui import language_engine as engine

log = logger.bind(module="shared.ui.language")

#: Une langue FAUSSE est pire que pas de langue : elle retire les bons sélecteurs, là où
#: « unknown » les garde tous. D'où un plancher de score ET une marge de ratio — une avance d'un
#: point à bas niveau ne suffit pas à trancher.
DEFAULT_MIN_SCORE = 3.0
DEFAULT_MIN_RATIO = 2.0

#: The detection of each platform, by platform in lower case ("instagram"): one instance each.
_detections: Dict[str, "LanguageDetection"] = {}


def base_language(code: str) -> str:
    """'en-GB' -> 'en'. The detection answers in base codes, an app's language picker in regional
    ones: a language change compares the two through this."""
    return (code or "").split("-")[0].lower()


def detected_language(platform: str) -> Optional[str]:
    """The language the detection of `platform` found in this process, or None when it has not
    run (or `platform` has no detection)."""
    detection = _detections.get(platform.lower())
    return detection.get_detected_language() if detection else None


class LanguageDetection:
    """La détection de langue d'UNE plateforme, avec son vocabulaire et son état propre."""

    def __init__(
        self,
        platform: str,
        fr_words: Sequence[str],
        en_words: Sequence[str],
        *,
        min_score: float = DEFAULT_MIN_SCORE,
        min_ratio: float = DEFAULT_MIN_RATIO,
        additional_vocabularies: Optional[Mapping[str, Sequence[str]]] = None,
    ) -> None:
        self.platform = platform
        self.fr_words = fr_words
        self.en_words = en_words
        self.min_score = min_score
        self.min_ratio = min_ratio
        self._fr_patterns = engine.compile_vocabulary(fr_words)
        self._en_patterns = engine.compile_vocabulary(en_words)
        # Langues supplémentaires : seulement des DONNÉES de plus, jamais un second moteur.
        # Une clé vide, ou « fr »/« en » (déjà couvertes), est ignorée plutôt que fusionnée.
        self._extra_words: Dict[str, Set[str]] = {
            code.lower(): set(words)
            for code, words in (additional_vocabularies or {}).items()
            if code and code.lower() not in ("fr", "en")
        }
        self._extra_patterns: Dict[str, Tuple[engine.WordPattern, ...]] = {
            code: engine.compile_vocabulary(words)
            for code, words in self._extra_words.items()
        }
        # Par INSTANCE, jamais par module : voir l'en-tête.
        self._detected_lang: Optional[str] = None
        _detections[platform.lower()] = self

    # ── État ──────────────────────────────────────────────────────────────────

    def get_detected_language(self) -> Optional[str]:
        """La langue détectée, ou None tant que la détection n'a pas tourné."""
        return self._detected_lang

    def reset(self) -> None:
        """Remet l'état à zéro — ce qui compte entre deux comptes sur le même appareil."""
        self._detected_lang = None

    # ── Détection ─────────────────────────────────────────────────────────────

    def detect_language(self, device) -> str:
        """Détecte la langue de l'application depuis un seul dump. Rend la langue retenue ou 'unknown'."""
        try:
            xml = engine.read_dump(device)
            if not xml:
                log.warning(f"No usable UI dump for {self.platform} language detection")
                self._detected_lang = "unknown"
                return self._detected_lang

            language, scores, matched, values_seen = self._analyze(xml)
            self._detected_lang = language

            score_line = ", ".join(f"{code.upper()}={score}" for code, score in scores.items())
            log.info(f"🌐 {self.platform} language detected: {self._detected_lang} ({score_line})")
            if self._detected_lang == "unknown":
                detail = "; ".join(
                    f"{code.upper()} matched {matched[code][:6] or 'nothing'}"
                    for code in scores
                )
                log.info(
                    f"🌐 {self.platform} language undecided on this screen — keeping all locales "
                    f"({values_seen} visible strings; {detail})."
                )
            return self._detected_lang

        except Exception as exc:  # noqa: BLE001 — une détection ratée rend 'unknown', pas une erreur
            log.error(f"{self.platform} language detection failed: {exc}")
            self._detected_lang = "unknown"
            return self._detected_lang

    def _patterns_by_language(self) -> Iterable[Tuple[str, Tuple[engine.WordPattern, ...]]]:
        """(code, vocabulaire compilé), en/fr d'abord: l'ordre des logs et des arbitrages.

        Les langues supplémentaires passent par la MÊME notation que fr/en — `visible_strings`
        puis `score_patterns` — pour qu'aucune ne puisse gagner par un chemin plus indulgent.
        """
        yield "fr", self._fr_patterns
        yield "en", self._en_patterns
        for code, patterns in self._extra_patterns.items():
            yield code, patterns

    def _analyze(self, xml: str) -> Tuple[str, Dict[str, float], Dict[str, List[str]], int]:
        """Note toutes les langues du dump une fois, puis ne tranche que si le vainqueur
        devance CHACUNE des autres du facteur `min_ratio`."""
        values = engine.visible_strings(xml)
        scores: Dict[str, float] = {}
        matched: Dict[str, List[str]] = {}
        for code, patterns in self._patterns_by_language():
            scores[code], matched[code] = engine.score_patterns(patterns, values)
        return self._choose_language(scores), scores, matched, len(values)

    def _choose_language(self, scores: Dict[str, float]) -> str:
        """Le gagnant, ou 'unknown' : plancher, avance sur TOUTES les autres, et aucun ex aequo."""
        if not self._extra_patterns:
            # Chemin historique à l'identique quand aucune langue supplémentaire n'est fournie.
            fr_score, en_score = scores["fr"], scores["en"]
            if fr_score >= self.min_score and fr_score >= en_score * self.min_ratio:
                return "fr"
            if en_score >= self.min_score and en_score >= fr_score * self.min_ratio:
                return "en"
            return "unknown"

        best = max(scores.values(), default=0.0)
        if best < self.min_score:
            return "unknown"
        leaders = [code for code, score in scores.items() if score == best]
        if len(leaders) != 1:
            return "unknown"  # ex aequo: aucune langue ne l'emporte
        winner = leaders[0]
        if any(best < score * self.min_ratio for code, score in scores.items() if code != winner):
            return "unknown"
        return winner

    def redetect_if_unknown(self, device, optimize: Callable[[Any], str]) -> Optional[str]:
        """Retente la détection, mais SEULEMENT si la langue est encore indécise.

        La détection tourne une fois, sur l'écran que l'application montrait. Une langue déjà
        tranchée n'est jamais rouverte : un écran plus tardif ne pourrait que transformer une
        bonne réponse en une moins bonne. À l'inverse, un seul dump indécis laissait toute la
        session en mode union — d'où cette seconde chance, et elle seule.
        """
        if self._detected_lang not in (None, "unknown"):
            return self._detected_lang
        log.info(f"🌐 {self.platform} language still undecided — retrying on the current screen")
        return optimize(device)

    # ── Sélecteurs ────────────────────────────────────────────────────────────

    def classify_selector(self, xpath: str) -> str:
        base = engine.classify_selector(xpath, self.fr_words, self.en_words)
        if not self._extra_words:
            return base

        # Une langue supplémentaire n'est reconnue que si SES mots sont dans un vrai attribut
        # textuel (le moteur ignore les resource-id). Mélangée à fr/en ou à une autre langue
        # supplémentaire, l'expression reste « neutral » : on la garde plutôt que de trancher.
        hits = [
            code for code, words in self._extra_words.items()
            if engine.classify_selector(xpath, words, set()) != "neutral"
        ]
        if not hits:
            return base
        has_base_language = any(
            engine.classify_selector(xpath, words, set()) != "neutral"
            for words in (self.fr_words, self.en_words)
        )
        if len(hits) == 1 and not has_base_language:
            return hits[0]
        return "neutral"

    def filter_selectors(self, selectors: List[str], lang: str) -> List[str]:
        """Retire les sélecteurs visant l'autre langue. Une langue indécise les garde tous."""
        if lang not in self._extra_words:
            return engine.filter_selectors(selectors, lang, self.fr_words, self.en_words)

        # Langue supplémentaire : on ne retire QUE ce qui est clairement d'une seule AUTRE
        # langue. Neutre (resource-id seul), mélangé, et surtout tout sélecteur de la langue
        # visée sont conservés — les chaînes de la langue cible ne disparaissent jamais.
        return [
            selector for selector in selectors
            if self.classify_selector(selector) in ("neutral", lang)
        ]

    def optimize_selector_dataclass(self, instance, lang: str) -> int:
        """Filtre en place chaque champ liste d'une dataclass de sélecteurs. Rend le compte retiré."""
        if lang in self._extra_words:
            removed = 0
            for name in getattr(instance, "__dataclass_fields__", {}):
                value = getattr(instance, name, None)
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    continue
                kept = self.filter_selectors(value, lang)
                removed += len(value) - len(kept)
                if len(kept) != len(value):
                    setattr(instance, name, kept)
            return removed
        return engine.optimize_selector_dataclass(instance, lang, self.fr_words, self.en_words)

    # ── Point d'entrée ────────────────────────────────────────────────────────

    def detect_and_optimize(
        self,
        device,
        override: Optional[str],
        *,
        barrel,
        set_active_locale: Callable[[Optional[str]], Any],
        available_locales: Optional[Callable[[], Iterable[str]]] = None,
    ) -> str:
        """Détecte (ou force) la langue, puis optimise tous les catalogues de sélecteurs.

        À appeler une fois, tôt dans un workflow, après connexion et ouverture de l'application ;
        n'importe quel écran montrant la navigation du bas suffit.
        """
        if override:
            allowed = tuple(available_locales()) if available_locales else ("en", "fr")
            lang = override if override in allowed else "unknown"
            # Enregistré dans l'état : sans cela `get_detected_language()` rendait None après un
            # override, et un appelant croyait la détection jamais lancée.
            self._detected_lang = lang
            log.info(f"🌐 {self.platform} language override: {override!r} -> {lang}")
        else:
            lang = self.detect_language(device)

        # La surcouche : les sélecteurs migrés lisent leurs fragments dans la locale active.
        set_active_locale(lang if lang != "unknown" else None)

        if lang == "unknown":
            log.info(f"{self.platform}: language unknown — overlay union + no in-place filtering")
            return lang

        total = 0
        for name, instance in self._selector_singletons(barrel):
            try:
                removed = self.optimize_selector_dataclass(instance, lang)
                if removed:
                    log.debug(f"  • {name}: removed {removed} wrong-language selector(s)")
                total += removed
            except Exception as exc:  # noqa: BLE001 — un catalogue récalcitrant n'arrête pas le run
                log.warning(f"  • {name}: optimization failed ({exc})")

        log.info(
            f"✅ {self.platform} selectors optimized for '{lang}' "
            f"({total} wrong-language selector(s) removed)"
        )
        return lang

    @staticmethod
    def _selector_singletons(barrel) -> List[tuple]:
        """Les catalogues à optimiser, DÉRIVÉS du barrel plutôt qu'énumérés.

        Une liste écrite à la main est une seconde description des mêmes objets, à côté du `__all__`
        du barrel. Celle d'Instagram avait vieilli exactement comme on s'y attend : trois catalogues
        absents, et un compté deux fois parce qu'il est un alias d'un autre.

        Les façades sont écartées par construction : `is_dataclass` est faux pour elles, et
        optimiser une façade passerait par son `__getattr__` sur un attribut fantôme.
        """
        out: List[tuple] = []
        seen: set = set()
        for name in getattr(barrel, "__all__", ()):
            if not name.endswith("SELECTORS"):
                continue
            obj = getattr(barrel, name, None)
            if obj is None or not is_dataclass(obj) or id(obj) in seen:
                continue
            seen.add(id(obj))
            out.append((type(obj).__name__, obj))
        return out


__all__ = ["LanguageDetection", "DEFAULT_MIN_SCORE", "DEFAULT_MIN_RATIO", "base_language", "detected_language"]
