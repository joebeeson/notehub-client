"""Stateless Notehub note operations sharing the owning client's transport."""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING

from ..compose import (
    Composer,
    NoteTarget,
    resolve_identifier,
    resolve_note_body,
    resolve_target,
)
from ..helpers import encode_path_segments

if TYPE_CHECKING:
    from ..typing import JSONObject, JSONValue
    from .base import RequestClient

LOGGER = getLogger(__name__)
_MISSING = object()


class NotesFacade:
    """Operations for the notes domain."""

    def __init__(self, client: RequestClient, *, composer: Composer | None = None) -> None:
        self._client = client
        self._composer = composer if composer is not None else Composer().copy(frozen=True)

    async def add_qi(
        self,
        project_uid: object = _MISSING,
        device_uid: object = _MISSING,
        notefile: object = _MISSING,
        body: object = _MISSING,
        *,
        target: object = _MISSING,
    ) -> JSONValue:
        """Add a queue-in note from explicit identifiers or a note target."""
        note_target, note_body = _note_input(
            project_uid,
            device_uid,
            notefile,
            _MISSING,
            body,
            target=target,
            composer=self._composer,
            require_note_id=False,
        )
        result = await self._client.request(
            "POST",
            encode_path_segments(
                "projects",
                note_target.project_uid,
                "devices",
                note_target.device_uid,
                "notes",
                note_target.notefile,
            ),
            json={"body": note_body},
        )
        LOGGER.info(
            "Notehub queue note added: project_uid=%r device_uid=%r notefile=%r",
            note_target.project_uid,
            note_target.device_uid,
            note_target.notefile,
        )
        return result

    async def add_db(
        self,
        project_uid: object = _MISSING,
        device_uid: object = _MISSING,
        notefile: object = _MISSING,
        note_id: object = _MISSING,
        body: object = _MISSING,
        *,
        target: object = _MISSING,
    ) -> JSONValue:
        """Add a database note from explicit identifiers or a note target."""
        note_target, note_body = _note_input(
            project_uid,
            device_uid,
            notefile,
            note_id,
            body,
            target=target,
            composer=self._composer,
            require_note_id=True,
        )
        note_id = _required_note_id(note_target)
        result = await self._client.request(
            "POST",
            encode_path_segments(
                "projects",
                note_target.project_uid,
                "devices",
                note_target.device_uid,
                "notes",
                note_target.notefile,
                note_id,
            ),
            json={"body": note_body},
        )
        LOGGER.info(
            "Notehub database note added: project_uid=%r device_uid=%r notefile=%r note_id=%r",
            note_target.project_uid,
            note_target.device_uid,
            note_target.notefile,
            note_id,
        )
        return result

    async def update_db(
        self,
        project_uid: object = _MISSING,
        device_uid: object = _MISSING,
        notefile: object = _MISSING,
        note_id: object = _MISSING,
        body: object = _MISSING,
        *,
        target: object = _MISSING,
    ) -> JSONValue:
        """Replace a database note from explicit identifiers or a note target."""
        note_target, note_body = _note_input(
            project_uid,
            device_uid,
            notefile,
            note_id,
            body,
            target=target,
            composer=self._composer,
            require_note_id=True,
        )
        note_id = _required_note_id(note_target)
        result = await self._client.request(
            "PUT",
            encode_path_segments(
                "projects",
                note_target.project_uid,
                "devices",
                note_target.device_uid,
                "notes",
                note_target.notefile,
                note_id,
            ),
            json={"body": note_body},
        )
        LOGGER.info(
            "Notehub database note updated: project_uid=%r device_uid=%r notefile=%r note_id=%r",
            note_target.project_uid,
            note_target.device_uid,
            note_target.notefile,
            note_id,
        )
        return result

    async def delete(
        self,
        project_uid: object = _MISSING,
        device_uid: object = _MISSING,
        notefile: object = _MISSING,
        note_id: object = _MISSING,
        *,
        target: object = _MISSING,
    ) -> JSONValue:
        """Delete a database note from explicit identifiers or a note target."""
        note_target, _ = _note_input(
            project_uid,
            device_uid,
            notefile,
            note_id,
            _MISSING,
            target=target,
            composer=self._composer,
            require_note_id=True,
            require_body=False,
        )
        note_id = _required_note_id(note_target)
        result = await self._client.request(
            "DELETE",
            encode_path_segments(
                "projects",
                note_target.project_uid,
                "devices",
                note_target.device_uid,
                "notes",
                note_target.notefile,
                note_id,
            ),
        )
        LOGGER.info(
            "Notehub database note deleted: project_uid=%r device_uid=%r notefile=%r note_id=%r",
            note_target.project_uid,
            note_target.device_uid,
            note_target.notefile,
            note_id,
        )
        return result


def _note_input(
    project_uid: object,
    device_uid: object,
    notefile: object,
    note_id: object,
    body: object,
    *,
    target: object,
    composer: Composer,
    require_note_id: bool,
    require_body: bool = True,
) -> tuple[NoteTarget, JSONObject | None]:
    if target is not _MISSING:
        if any(value is not _MISSING for value in (project_uid, device_uid, notefile, note_id)):
            raise TypeError("provide either target or explicit note identifiers")
        resolved = resolve_target(target, composer=composer)
        note_body = body
    elif notefile is _MISSING and note_id is _MISSING:
        # Additive shorthand: notes.add_*(target, body).
        if project_uid is _MISSING:
            raise TypeError("a note target or explicit identifiers are required")
        if body is _MISSING and device_uid is not _MISSING:
            note_body = device_uid
        else:
            note_body = body
        if device_uid is not _MISSING and body is not _MISSING:
            raise TypeError("too many values for target-based note operation")
        if body is _MISSING and device_uid is _MISSING:
            note_body = _MISSING
        resolved = resolve_target(project_uid, composer=composer)
    else:
        if any(value is _MISSING for value in (project_uid, device_uid, notefile)):
            raise TypeError("project_uid, device_uid, and notefile are required")
        note_id_value = (
            None
            if note_id is _MISSING
            else resolve_identifier(note_id, "note_id", composer=composer)
        )
        resolved = NoteTarget(
            resolve_identifier(project_uid, "project_uid", composer=composer),
            resolve_identifier(device_uid, "device_uid", composer=composer),
            resolve_identifier(notefile, "notefile", composer=composer),
            note_id_value,
        )
        note_body = body

    if not isinstance(resolved, NoteTarget):
        raise TypeError("note operations require a NoteTarget")
    if require_note_id and resolved.note_id is None:
        raise ValueError("this note operation requires a note_id")
    if not require_note_id and resolved.note_id is not None:
        raise ValueError("queue-in note targets cannot include a note_id")
    if not require_body:
        return resolved, None
    if note_body is _MISSING:
        raise TypeError("a note body is required")
    return resolved, resolve_note_body(note_body, composer=composer)


def _required_note_id(target: NoteTarget) -> str:
    if target.note_id is None:
        raise ValueError("this note operation requires a note_id")
    return target.note_id
