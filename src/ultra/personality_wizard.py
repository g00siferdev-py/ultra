"""Interactive personality customization wizard."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any

import click

from ultra.config import Config
from ultra.personality import PersonalityManager, default_ultra_profile


class FieldResult(Enum):
    KEEP = auto()
    BACK = auto()
    VALUE = auto()


@dataclass(frozen=True)
class PersonalityField:
    attr: str
    json_key: str
    title: str
    hint: str
    multiline: bool = True
    required: bool = False


PERSONALITY_FIELDS: tuple[PersonalityField, ...] = (
    PersonalityField(
        "profile_name",
        "profileName",
        "Profile name",
        "Preset label (e.g. Ultra, Home hub, Work mode).",
        multiline=False,
        required=True,
    ),
    PersonalityField(
        "companion_name",
        "companionName",
        "Companion name",
        "Name shown in chat (e.g. Ultra, Sage, Nova).",
        multiline=False,
        required=True,
    ),
    PersonalityField(
        "core_personality",
        "corePersonality",
        "Core personality",
        "Who they are — traits, demeanor, role.",
    ),
    PersonalityField(
        "tone_of_voice",
        "toneOfVoice",
        "Tone of voice",
        "How they speak — warm, concise, formal, playful, etc.",
    ),
    PersonalityField(
        "background_story",
        "backgroundStory",
        "Background & role",
        "Where they live in the stack, purpose, context.",
    ),
    PersonalityField(
        "core_values",
        "coreValues",
        "Core values & principles",
        "What they prioritize when making decisions.",
    ),
    PersonalityField(
        "relationship_style",
        "relationshipStyle",
        "Relationship style",
        "How they relate to you over time.",
    ),
    PersonalityField(
        "special_instructions",
        "specialInstructions",
        "Special instructions",
        "Quirks, boundaries, tool usage notes.",
    ),
    PersonalityField(
        "avatar_description",
        "avatarDescription",
        "Avatar / visual note (optional)",
        "For future voice/UI — can be left blank.",
        required=False,
    ),
)


def _preview(text: str | None, *, limit: int = 280) -> str:
    if not text or not str(text).strip():
        return "(empty)"
    t = str(text).strip().replace("\r\n", "\n")
    if len(t) <= limit:
        return t
    return t[: limit - 3] + "..."


def _prompt_choice(
    *,
    title: str,
    options: list[tuple[str, str]],
    default: str = "",
) -> str | None:
    """Return option key, or None on back (0 / Ctrl+C)."""
    click.echo("")
    click.echo(title)
    click.echo("-" * len(title))
    for key, label in options:
        click.echo(f"  {key}) {label}")
    click.echo("  0) Back")
    click.echo("  ?) Help")

    while True:
        try:
            raw = click.prompt("Choice", default=default, show_default=bool(default)).strip().lower()
        except (EOFError, KeyboardInterrupt):
            click.echo("")
            return None

        if raw in {"?", "help", "h"}:
            click.echo("  Enter a number from the menu.  0 or Ctrl+C = go back.")
            continue
        if raw in {"0", "back", "b"}:
            return None
        for key, _ in options:
            if raw == key:
                return key
        click.echo("Invalid choice.")


def edit_personality_field(field: PersonalityField, current: str | None) -> tuple[FieldResult, str | None]:
    """Edit one personality field. Enter=keep, e=editor, c=clear (optional), 0=back."""
    cur = (current or "").strip()
    click.echo("")
    click.echo(f"=== {field.title} ===")
    click.echo(field.hint)
    click.echo("")
    click.echo(f"Current:\n{_preview(cur)}\n")
    click.echo("  Enter     Keep current value")
    click.echo("  e         Open text editor (best for long sections)")
    if field.multiline:
        click.echo("  t         Type here (single paragraph)")
    if not field.required:
        click.echo("  c         Clear / leave blank")
    click.echo("  0         Back without changing this field")

    while True:
        try:
            action = click.prompt("Action", default="", show_default=False).strip().lower()
        except (EOFError, KeyboardInterrupt):
            click.echo("")
            return FieldResult.BACK, None

        if action in {"", "keep", "k"}:
            return FieldResult.KEEP, None
        if action in {"0", "back", "b"}:
            return FieldResult.BACK, None
        if action == "c" and not field.required:
            return FieldResult.VALUE, ""
        if action == "e":
            try:
                edited = click.edit(
                    cur if cur else f"# {field.title}\n",
                    extension=".txt",
                    require_save=False,
                )
            except click.ClickException:
                edited = None
            if edited is None:
                click.echo("Editor cancelled — no change.")
                continue
            value = edited.strip()
            if field.required and not value:
                click.echo("This field cannot be empty.")
                continue
            return FieldResult.VALUE, value
        if action == "t" and field.multiline:
            click.echo("Enter text. End with a blank line:")
            lines: list[str] = []
            try:
                while True:
                    line = input()
                    if line == "":
                        break
                    lines.append(line)
            except (EOFError, KeyboardInterrupt):
                click.echo("")
                return FieldResult.BACK, None
            value = "\n".join(lines).strip()
            if field.required and not value:
                click.echo("This field cannot be empty.")
                continue
            return FieldResult.VALUE, value
        if not field.multiline and action not in {"e", "c", "t"}:
            if field.required and not action:
                continue
            return FieldResult.VALUE, action
        click.echo("Invalid action. Use Enter, e, c, t, or 0.")


def _field_by_key(key: str) -> PersonalityField | None:
    for idx, field in enumerate(PERSONALITY_FIELDS, start=1):
        if key == str(idx):
            return field
    return None


def _apply_field(mgr: PersonalityManager, field: PersonalityField, value: str | None) -> None:
    if value is None:
        return
    args: dict[str, Any] = {field.json_key: value}
    if field.attr == "avatar_description" and value == "":
        args[field.json_key] = None
    mgr.patch_active_profile_from_args(args)


def run_personality_customize(config: Config, *, mode: str = "walkthrough") -> bool:
    """
    Interactive personality editor.
    mode: walkthrough (all fields in order) | pick (choose one field)
    Returns True if saved any changes.
    """
    mgr = PersonalityManager.load(config)
    if not mgr.enabled:
        click.echo("Personality is disabled in config (personality.enabled: false).")
        return False

    click.echo("")
    click.echo(f"Editing: {mgr.path}")
    click.echo(f"Companion: {mgr.companion_display_name()}")
    click.echo("")
    click.echo("Navigation: Enter = keep  |  e = editor  |  c = clear  |  0 / Ctrl+C = back")

    from ultra.personality import PersonalityManager

    profile = mgr.active_profile()
    saved = False

    if mode == "pick":
        options = [(str(i), f.title) for i, f in enumerate(PERSONALITY_FIELDS, start=1)]
        key = _prompt_choice(title="Edit one section", options=options)
        if key is None:
            return False
        field = _field_by_key(key)
        if field is None:
            return False
        current = getattr(profile, field.attr)
        result, value = edit_personality_field(field, current)
        if result == FieldResult.BACK:
            return False
        if result == FieldResult.VALUE:
            _apply_field(mgr, field, value)
            saved = True
            click.echo(f"\nSaved {field.title}.")
        return saved

    # walkthrough all fields
    index = 0
    while index < len(PERSONALITY_FIELDS):
        field = PERSONALITY_FIELDS[index]
        current = getattr(profile, field.attr)
        click.echo(f"\n--- Section {index + 1} of {len(PERSONALITY_FIELDS)} ---")
        result, value = edit_personality_field(field, current)

        if result == FieldResult.BACK:
            if index == 0:
                click.echo("Leaving customize (no changes this step).")
                return saved
            index -= 1
            click.echo("Previous section.")
            continue

        if result == FieldResult.VALUE:
            _apply_field(mgr, field, value)
            setattr(profile, field.attr, value if value is not None else None)
            saved = True

        index += 1

    if saved:
        click.echo(f"\nPersonality saved to {mgr.path}")
        if click.confirm("Preview generated system prompt?", default=False):
            click.echo("\n" + mgr.generated_system_prompt())
    else:
        click.echo("\nNo changes made.")
    return saved


def run_personality_menu(config: Config, *, config_path: Path | None = None) -> None:
    """Personality submenu with customize flows."""
    from ultra import cli as cli_module

    cfg_opt: dict[str, Any] = {"config_path": config_path}

    def go_show() -> None:
        cli_module.personality_show.callback(**cfg_opt, prompt=False)

    def go_prompt() -> None:
        cli_module.personality_show.callback(**cfg_opt, prompt=True)

    def go_path() -> None:
        cli_module.personality_path.callback(**cfg_opt)

    def go_walkthrough() -> None:
        run_personality_customize(config, mode="walkthrough")

    def go_pick() -> None:
        run_personality_customize(config, mode="pick")

    def go_reset() -> None:
        mgr = PersonalityManager.load(config)
        if not mgr.enabled:
            click.echo("Personality is disabled.")
            return
        if not click.confirm("Reset active profile to Linux Ultra defaults?", default=False):
            return
        default = default_ultra_profile()
        mgr.patch_active_profile_from_args(
            {
                "profileName": default.profile_name,
                "companionName": default.companion_name,
                "corePersonality": default.core_personality,
                "toneOfVoice": default.tone_of_voice,
                "backgroundStory": default.background_story,
                "coreValues": default.core_values,
                "relationshipStyle": default.relationship_style,
                "specialInstructions": default.special_instructions,
                "avatarDescription": None,
            }
        )
        click.echo("Reset to defaults.")

    while True:
        choice = _prompt_choice(
            title="Personality",
            options=[
                ("1", "Show active profile"),
                ("2", "Show generated system prompt"),
                ("3", "Show personality.json path"),
                ("4", "Customize — walk through all sections"),
                ("5", "Edit one section"),
                ("6", "Reset to Ultra defaults"),
            ],
            default="0",
        )
        if choice is None:
            return
        actions = {
            "1": go_show,
            "2": go_prompt,
            "3": go_path,
            "4": go_walkthrough,
            "5": go_pick,
            "6": go_reset,
        }
        fn = actions.get(choice)
        if fn:
            click.echo("")
            fn()
            if choice in {"1", "2", "3", "6"}:
                try:
                    click.prompt("\nPress Enter to continue", default="", show_default=False)
                except (EOFError, KeyboardInterrupt):
                    return
