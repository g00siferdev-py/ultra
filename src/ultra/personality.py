"""Companion personality presets — Persistent Sage-compatible `personality.json`."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ultra.config import Config

FILE_VERSION = 1
FIELD_MAX_CHARS = 50_000


@dataclass
class PersonalityProfile:
    id: str
    profile_name: str
    companion_name: str
    core_personality: str
    tone_of_voice: str
    background_story: str
    core_values: str
    relationship_style: str
    special_instructions: str
    avatar_description: str | None = None


@dataclass
class PersonalityFile:
    version: int = FILE_VERSION
    profiles: list[PersonalityProfile] = field(default_factory=list)
    active_profile_id: str = "ultra"


def default_ultra_profile() -> PersonalityProfile:
    return PersonalityProfile(
        id="ultra",
        profile_name="Ultra",
        companion_name="Ultra",
        core_personality=(
            "Ultra is a capable, calm Linux orchestrator and home-hub companion. "
            "He is practical, resourceful, and steady under pressure — focused on getting "
            "real work done on the machine he runs on. He treats the user as a partner, not "
            "a ticket queue."
        ),
        tone_of_voice=(
            "Clear, concise, and friendly. Ultra is direct when executing tasks and thoughtful "
            "when explaining tradeoffs. He avoids filler, over-apologizing, and fake enthusiasm."
        ),
        background_story=(
            "Ultra runs on a dedicated Linux appliance (often a Raspberry Pi) that orchestrates "
            "the home, automations, and system services. He grows more useful over time through "
            "Memory Anchor recall and thoughtful self-editing of his persona when the user asks."
        ),
        core_values=(
            "Reliability, honesty, user autonomy, privacy, careful reasoning, and practical "
            "follow-through. Prefer working solutions over theoretical advice."
        ),
        relationship_style=(
            "Ultra accompanies the user over time — consistent, respectful, and proactive when "
            "appropriate. He adapts to preferences without losing good judgment."
        ),
        special_instructions=(
            "Ultra orchestrates the host OS via shell, files, HTTP, and workspace scripts. "
            "He may read or update his saved personality (personality.json) using personality_get "
            "and personality_update when the user asks to change his tone, values, or behavior — "
            "be transparent and conservative with self-edits. Use memory_search and memory_remember "
            "for durable user context."
        ),
        avatar_description=None,
    )


def default_personality_file() -> PersonalityFile:
    profile = default_ultra_profile()
    return PersonalityFile(
        version=FILE_VERSION,
        profiles=[profile],
        active_profile_id=profile.id,
    )


def build_system_prompt(profile: PersonalityProfile) -> str:
    name = profile.companion_name.strip()
    display = name or "Ultra"

    lines = [
        "# Companion persona",
        "",
        (
            f"You are **{display}**, the user's AI companion on their Linux orchestrator hub. "
            "Stay in character consistently across the conversation."
        ),
        "",
    ]

    def section(title: str, body: str) -> None:
        text = body.strip()
        if not text:
            return
        lines.extend([f"## {title}", text, ""])

    section("Core personality", profile.core_personality)
    section("Tone of voice", profile.tone_of_voice)
    section("Background & role", profile.background_story)
    section("Core values & principles", profile.core_values)
    section("Relationship style", profile.relationship_style)
    section("Special instructions & quirks", profile.special_instructions)
    if profile.avatar_description and profile.avatar_description.strip():
        section("Visual / avatar note (for future use)", profile.avatar_description)

    lines.append(
        f"In the session transcript below, lines labeled **{display}** are your own earlier "
        "replies in this thread — not a separate assistant."
    )
    lines.append("Respect user privacy, follow the user's lead, and use recalled memory when relevant.")
    return "\n".join(lines).strip()


def personality_system_hint() -> str:
    return (
        "\n\n## Personality self-edit (enabled)\n\n"
        "Use **personality_get** to read your saved persona and **personality_update** to change "
        "the active profile when the user asks you to adjust how you behave. Do not rewrite your "
        "personality without a clear user request. Saved changes apply to this conversation immediately."
    )


def _persistent_sage_data_dir() -> Path | None:
    raw = os.environ.get("PERSISTENT_SAGE_DATA_DIR") or os.environ.get("NOVA_DATA_DIR")
    return Path(raw) if raw else None


def resolve_personality_path(config: Config) -> Path:
    if config.personality.path:
        return config.personality.path.resolve()
    if config.personality.persistent_sage_compat:
        ps_dir = _persistent_sage_data_dir()
        if ps_dir and (ps_dir / "personality.json").is_file():
            return (ps_dir / "personality.json").resolve()
    return (config.workspace / "personality.json").resolve()


def _profile_to_dict(profile: PersonalityProfile, generated_prompt: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": profile.id,
        "profileName": profile.profile_name,
        "companionName": profile.companion_name,
        "corePersonality": profile.core_personality,
        "toneOfVoice": profile.tone_of_voice,
        "backgroundStory": profile.background_story,
        "coreValues": profile.core_values,
        "relationshipStyle": profile.relationship_style,
        "specialInstructions": profile.special_instructions,
        "avatarDescription": profile.avatar_description,
    }
    if generated_prompt:
        out["generatedSystemPromptPreview"] = generated_prompt[:1200]
    return out


def _profile_from_dict(raw: dict[str, Any]) -> PersonalityProfile:
    return PersonalityProfile(
        id=str(raw.get("id") or "ultra"),
        profile_name=str(raw.get("profileName") or raw.get("profile_name") or "Ultra"),
        companion_name=str(raw.get("companionName") or raw.get("companion_name") or "Ultra"),
        core_personality=str(raw.get("corePersonality") or raw.get("core_personality") or ""),
        tone_of_voice=str(raw.get("toneOfVoice") or raw.get("tone_of_voice") or ""),
        background_story=str(raw.get("backgroundStory") or raw.get("background_story") or ""),
        core_values=str(raw.get("coreValues") or raw.get("core_values") or ""),
        relationship_style=str(raw.get("relationshipStyle") or raw.get("relationship_style") or ""),
        special_instructions=str(
            raw.get("specialInstructions") or raw.get("special_instructions") or ""
        ),
        avatar_description=raw.get("avatarDescription") or raw.get("avatar_description"),
    )


def _file_to_dict(file: PersonalityFile) -> dict[str, Any]:
    return {
        "version": file.version,
        "profiles": [_profile_to_dict(p) for p in file.profiles],
        "activeProfileId": file.active_profile_id,
    }


def _file_from_dict(raw: dict[str, Any]) -> PersonalityFile:
    profiles_raw = raw.get("profiles") or []
    profiles = [_profile_from_dict(p) for p in profiles_raw if isinstance(p, dict)]
    active = str(raw.get("activeProfileId") or raw.get("active_profile_id") or "ultra")
    if not profiles:
        return default_personality_file()
    if not any(p.id == active for p in profiles):
        active = profiles[0].id
    return PersonalityFile(
        version=int(raw.get("version") or FILE_VERSION),
        profiles=profiles,
        active_profile_id=active,
    )


def _active_profile(file: PersonalityFile) -> PersonalityProfile:
    for profile in file.profiles:
        if profile.id == file.active_profile_id:
            return profile
    return file.profiles[0]


def _check_field_len(label: str, value: str) -> None:
    if len(value) > FIELD_MAX_CHARS:
        raise ValueError(f"{label} exceeds {FIELD_MAX_CHARS} characters")


class PersonalityManager:
    def __init__(self, path: Path, file: PersonalityFile, *, enabled: bool = True) -> None:
        self.path = path
        self._file = file
        self._enabled = enabled

    @classmethod
    def disabled(cls) -> PersonalityManager:
        default = default_personality_file()
        return cls(Path("personality.json"), default, enabled=False)

    @classmethod
    def load(cls, config: Config) -> PersonalityManager:
        if not config.personality.enabled:
            return cls.disabled()

        path = resolve_personality_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            file = _file_from_dict(raw if isinstance(raw, dict) else {})
            file.version = FILE_VERSION
        else:
            file = default_personality_file()
            path.write_text(json.dumps(_file_to_dict(file), indent=2), encoding="utf-8")
        return cls(path, file, enabled=True)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def active_profile_id(self) -> str:
        if not self._enabled:
            return "ultra"
        return _active_profile(self._file).id

    def companion_display_name(self) -> str:
        if not self._enabled:
            return "Ultra"
        name = _active_profile(self._file).companion_name.strip()
        return name or "Ultra"

    def system_prompt_prefix(self) -> str:
        if not self._enabled:
            return ""
        return build_system_prompt(_active_profile(self._file))

    def generated_system_prompt(self) -> str:
        return self.system_prompt_prefix()

    def active_profile(self) -> PersonalityProfile:
        return _active_profile(self._file)

    def persist(self) -> None:
        self._file.version = FILE_VERSION
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(_file_to_dict(self._file), indent=2), encoding="utf-8")

    def get_active_json(self) -> dict[str, Any]:
        active = _active_profile(self._file)
        generated = build_system_prompt(active)
        return {
            "ok": True,
            "activeProfileId": self._file.active_profile_id,
            "path": str(self.path),
            "profile": _profile_to_dict(active, generated),
        }

    def patch_active_profile_from_args(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self._enabled:
            raise RuntimeError("personality is disabled")

        active = _active_profile(self._file)
        idx = next(i for i, p in enumerate(self._file.profiles) if p.id == active.id)
        profile = self._file.profiles[idx]
        changed = False

        if "profileName" in args:
            text = str(args["profileName"]).strip()
            if not text:
                raise ValueError("profileName cannot be empty")
            _check_field_len("profileName", text)
            profile.profile_name = text
            changed = True
        if "companionName" in args:
            text = str(args["companionName"]).strip()
            if not text:
                raise ValueError("companionName cannot be empty")
            _check_field_len("companionName", text)
            profile.companion_name = text
            changed = True

        for json_key, attr in [
            ("corePersonality", "core_personality"),
            ("toneOfVoice", "tone_of_voice"),
            ("backgroundStory", "background_story"),
            ("coreValues", "core_values"),
            ("relationshipStyle", "relationship_style"),
            ("specialInstructions", "special_instructions"),
        ]:
            if json_key in args:
                value = str(args[json_key])
                _check_field_len(json_key, value)
                setattr(profile, attr, value)
                changed = True

        if "avatarDescription" in args:
            av = args["avatarDescription"]
            if av is None:
                profile.avatar_description = None
            elif isinstance(av, str):
                text = av.strip()
                if text:
                    _check_field_len("avatarDescription", text)
                    profile.avatar_description = text
                else:
                    profile.avatar_description = None
            else:
                raise ValueError("avatarDescription must be a string or null")
            changed = True

        if not changed:
            raise ValueError("personality_update: provide at least one field to change")

        self.persist()
        body = self.get_active_json()
        body["saved"] = True
        body["message"] = f"Active personality profile updated and saved to {self.path.name}."
        return body
