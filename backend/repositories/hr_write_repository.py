"""Authoritative PostgreSQL writes for HR platform creation and cloning.

The HR dashboard still has a temporary SQLite compatibility mirror in hybrid
deployments.  Clone sources and cloned course structures must nevertheless be
resolved and written in PostgreSQL whenever the formation pipeline is backed
by PostgreSQL; otherwise the catalogue and the writer observe different data.
"""

from __future__ import annotations

from typing import Any

from database.postgres import get_postgres_connection


class CloneSourceNotFound(LookupError):
    """The source does not exist inside the caller's tenant scope."""


class CloneSourceInvalid(ValueError):
    """The source exists but is not ready to be reused."""


def _tenant_predicate(
    aliases: tuple[str, ...],
    center_account_id: int | None,
    *,
    scope_to_center: bool,
) -> tuple[str, tuple[Any, ...]]:
    if not scope_to_center:
        return "", ()
    if center_account_id is None:
        return " AND FALSE", ()
    return (
        "".join(f" AND {alias}.center_account_id = %s" for alias in aliases),
        tuple(center_account_id for _ in aliases),
    )


def _resolve_module_with_cursor(
    cur,
    module_id: int,
    center_account_id: int | None,
    *,
    scope_to_center: bool,
) -> dict[str, Any]:
    scope_sql, scope_params = _tenant_predicate(
        ("m", "pc"),
        center_account_id,
        scope_to_center=scope_to_center,
    )
    cur.execute(
        f"""
        SELECT m.id,
               m.status,
               m.voice_type,
               m.source_pipeline_job_id,
               m.source_platform_id,
               m.center_account_id,
               pc.center_account_id AS platform_center_account_id,
               COUNT(cf.id)::integer AS folder_count
        FROM formation_modules m
        JOIN platform_config pc ON pc.id = m.source_platform_id
        LEFT JOIN cours_folders cf ON cf.platform_id = m.source_platform_id
        WHERE m.id = %s
        {scope_sql}
        GROUP BY m.id, m.status, m.voice_type, m.source_pipeline_job_id,
                 m.source_platform_id, m.center_account_id, pc.center_account_id
        """,
        (module_id, *scope_params),
    )
    row = cur.fetchone()
    if row is None:
        raise CloneSourceNotFound("Module introuvable")

    source = dict(row)
    status = str(source.get("status") or "")
    if status == "archived":
        raise CloneSourceInvalid("Ce module est archivé")
    if status != "validated":
        raise CloneSourceInvalid(
            f"Ce module n'est pas validé (statut : {status or 'inconnu'})"
        )
    if source.get("voice_type") == "mock":
        raise CloneSourceInvalid(
            "Ce module a été généré en mode test silencieux. "
            "Relancez le TTS avec Edge TTS ou Fish Audio avant de créer une plateforme."
        )
    if int(source.get("folder_count") or 0) <= 0:
        raise CloneSourceInvalid("Le module n'a pas de cours générés (source vide)")
    return source


def resolve_postgres_module_clone_source(
    module_id: int,
    center_account_id: int | None = None,
    *,
    scope_to_center: bool = False,
) -> dict[str, Any]:
    """Resolve and validate a reusable module without any SQLite fallback."""
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            return _resolve_module_with_cursor(
                cur,
                int(module_id),
                center_account_id,
                scope_to_center=scope_to_center,
            )


def _resolve_formation_with_cursor(
    cur,
    formation_id: int,
    center_account_id: int | None,
    *,
    scope_to_center: bool,
) -> dict[str, Any]:
    scope_sql, scope_params = _tenant_predicate(
        ("pc",),
        center_account_id,
        scope_to_center=scope_to_center,
    )
    cur.execute(
        f"""
        SELECT j.id,
               j.status,
               j.platform_id AS source_platform_id,
               pc.center_account_id AS platform_center_account_id,
               COUNT(cf.id)::integer AS folder_count
        FROM formation_pipeline_jobs j
        JOIN platform_config pc ON pc.id = j.platform_id
        LEFT JOIN cours_folders cf ON cf.platform_id = j.platform_id
        WHERE j.id = %s
        {scope_sql}
        GROUP BY j.id, j.status, j.platform_id, pc.center_account_id
        """,
        (formation_id, *scope_params),
    )
    row = cur.fetchone()
    if row is None:
        raise CloneSourceNotFound("Formation introuvable")

    source = dict(row)
    status = str(source.get("status") or "")
    if status != "completed":
        raise CloneSourceInvalid(
            f"La formation n'est pas complétée (statut : {status or 'inconnu'})"
        )
    if int(source.get("folder_count") or 0) <= 0:
        raise CloneSourceInvalid("La formation n'a pas encore de cours générés")
    return source


def resolve_postgres_formation_clone_source(
    formation_id: int,
    center_account_id: int | None = None,
    *,
    scope_to_center: bool = False,
) -> dict[str, Any]:
    """Resolve and validate a completed pipeline formation in PostgreSQL."""
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            return _resolve_formation_with_cursor(
                cur,
                int(formation_id),
                center_account_id,
                scope_to_center=scope_to_center,
            )


def clone_postgres_course_structure(
    *,
    target_platform_id: int,
    module_id: int | None = None,
    formation_id: int | None = None,
    center_account_id: int | None = None,
    scope_to_center: bool = False,
) -> dict[str, Any]:
    """Clone folders/documents atomically and return the stable Blob ID map.

    ``course_clone_folder_map`` makes a retry reuse the exact same target
    folder IDs.  This matters because Blob object names embed both platform and
    folder IDs.  Content-generation jobs and segments are intentionally not
    copied: the historic clone only copied ``cours_folders`` and
    ``cours_documents``.
    """
    if (module_id is None) == (formation_id is None):
        raise ValueError("Fournir exactement une source module_id ou formation_id")

    target_platform_id = int(target_platform_id)
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"hr-course-clone:{target_platform_id}",),
            )

            if module_id is not None:
                module_id = int(module_id)
                source = _resolve_module_with_cursor(
                    cur,
                    module_id,
                    center_account_id,
                    scope_to_center=scope_to_center,
                )
                source_kind = "module"
                source_id = module_id
            else:
                formation_id = int(formation_id)
                source = _resolve_formation_with_cursor(
                    cur,
                    formation_id,
                    center_account_id,
                    scope_to_center=scope_to_center,
                )
                source_kind = "formation"
                source_id = formation_id

            target_scope_sql, target_scope_params = _tenant_predicate(
                ("pc",),
                center_account_id,
                scope_to_center=scope_to_center,
            )
            cur.execute(
                f"""
                SELECT pc.id, pc.center_account_id, pc.status,
                       pc.source_formation_id, pc.source_module_id
                FROM platform_config pc
                WHERE pc.id = %s
                {target_scope_sql}
                FOR UPDATE
                """,
                (target_platform_id, *target_scope_params),
            )
            target = cur.fetchone()
            if target is None:
                raise CloneSourceNotFound("Plateforme cible introuvable")
            target = dict(target)

            if module_id is not None:
                if target.get("source_module_id") != module_id:
                    raise CloneSourceInvalid(
                        "La plateforme cible n'est pas liée au module demandé"
                    )
            elif target.get("source_formation_id") != formation_id:
                raise CloneSourceInvalid(
                    "La plateforme cible n'est pas liée à la formation demandée"
                )

            source_platform_id = int(source["source_platform_id"])
            if source_platform_id == target_platform_id:
                raise CloneSourceInvalid("La source et la cible du clone sont identiques")

            cur.execute(
                """
                SELECT id, name, position
                FROM cours_folders
                WHERE platform_id = %s
                ORDER BY position, id
                """,
                (source_platform_id,),
            )
            source_folders = [dict(row) for row in cur.fetchall()]
            if not source_folders:
                # Re-check inside the same transaction even though the source
                # resolver already counted the folders.
                raise CloneSourceInvalid("La source ne contient aucun dossier de cours")

            source_folder_ids = [int(row["id"]) for row in source_folders]
            cur.execute(
                """
                SELECT folder_id, filename, original_name, status,
                       audio_filename, doc_type
                FROM cours_documents
                WHERE folder_id = ANY(%s)
                ORDER BY folder_id, id
                """,
                (source_folder_ids,),
            )
            documents_by_folder: dict[int, list[dict[str, Any]]] = {
                folder_id: [] for folder_id in source_folder_ids
            }
            for row in cur.fetchall():
                document = dict(row)
                documents_by_folder[int(document["folder_id"])].append(document)

            cur.execute(
                """
                SELECT source_folder_id, target_folder_id
                FROM course_clone_folder_map
                WHERE target_platform_id = %s
                  AND source_platform_id = %s
                """,
                (target_platform_id, source_platform_id),
            )
            folder_id_map = {
                int(row["source_folder_id"]): int(row["target_folder_id"])
                for row in cur.fetchall()
            }

            for folder in source_folders:
                source_folder_id = int(folder["id"])
                if source_folder_id in folder_id_map:
                    continue
                cur.execute(
                    """
                    INSERT INTO cours_folders (platform_id, name, position)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (target_platform_id, folder["name"], folder["position"]),
                )
                inserted = cur.fetchone()
                target_folder_id = int(inserted["id"])
                folder_id_map[source_folder_id] = target_folder_id

                for document in documents_by_folder[source_folder_id]:
                    cur.execute(
                        """
                        INSERT INTO cours_documents (
                            folder_id, filename, original_name, status,
                            audio_filename, doc_type
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            target_folder_id,
                            document["filename"],
                            document["original_name"],
                            document.get("status") or "uploaded",
                            document.get("audio_filename"),
                            document.get("doc_type") or "source",
                        ),
                    )

                cur.execute(
                    """
                    INSERT INTO course_clone_folder_map (
                        target_platform_id, source_platform_id,
                        source_folder_id, target_folder_id
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        target_platform_id,
                        source_platform_id,
                        source_folder_id,
                        target_folder_id,
                    ),
                )

            return {
                "source_kind": source_kind,
                "source_id": source_id,
                "source_platform_id": source_platform_id,
                "target_platform_id": target_platform_id,
                "folder_id_map": folder_id_map,
            }


def set_postgres_platform_status(
    platform_id: int,
    status: str,
    center_account_id: int | None = None,
    *,
    scope_to_center: bool = False,
) -> None:
    """Update authoritative clone status; never falls back to SQLite."""
    if status not in {"pending", "ready", "error"}:
        raise ValueError(f"Statut plateforme non autorisé : {status}")
    scope_sql, scope_params = _tenant_predicate(
        ("platform_config",),
        center_account_id,
        scope_to_center=scope_to_center,
    )
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE platform_config
                SET status = %s, updated_at = NOW()
                WHERE id = %s
                {scope_sql}
                RETURNING id
                """,
                (status, int(platform_id), *scope_params),
            )
            if cur.fetchone() is None:
                raise CloneSourceNotFound("Plateforme cible introuvable")


def create_postgres_manual_formation_module(
    *,
    platform_id: int,
    tp_name: str,
    center_account_id: int | None,
) -> dict[str, Any]:
    """Idempotently expose a manually-authored platform in the PG catalogue."""
    platform_id = int(platform_id)
    module_name = str(tp_name or "").strip()
    if not module_name:
        raise ValueError("Le nom du module manuel est requis")

    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"manual-module:{center_account_id or 0}:{platform_id}",),
            )
            cur.execute(
                """
                SELECT id
                FROM platform_config
                WHERE id = %s
                  AND center_account_id IS NOT DISTINCT FROM %s
                FOR UPDATE
                """,
                (platform_id, center_account_id),
            )
            if cur.fetchone() is None:
                raise CloneSourceNotFound("Plateforme du module manuel introuvable")

            cur.execute(
                """
                SELECT id, rncp_code, tp_name, version, status,
                       source_pipeline_job_id, source_platform_id,
                       center_account_id, validated_at
                FROM formation_modules
                WHERE source_platform_id = %s
                  AND source_pipeline_job_id IS NULL
                  AND version LIKE 'manuel-v%%'
                ORDER BY id
                LIMIT 1
                """,
                (platform_id,),
            )
            existing = cur.fetchone()
            if existing is not None:
                return dict(existing)

            cur.execute(
                """
                SELECT COUNT(*)::integer AS module_count
                FROM formation_modules
                WHERE source_pipeline_job_id IS NULL
                  AND center_account_id IS NOT DISTINCT FROM %s
                  AND version LIKE 'manuel-v%%'
                """,
                (center_account_id,),
            )
            count_row = cur.fetchone()
            version = f"manuel-v{int(count_row['module_count']) + 1}"
            cur.execute(
                """
                INSERT INTO formation_modules (
                    center_account_id, rncp_code, tp_name, version, status,
                    source_pipeline_job_id, source_platform_id, validated_at
                )
                VALUES (%s, NULL, %s, %s, 'validated', NULL, %s, NOW())
                RETURNING id, rncp_code, tp_name, version, status,
                          source_pipeline_job_id, source_platform_id,
                          center_account_id, validated_at
                """,
                (center_account_id, module_name, version, platform_id),
            )
            return dict(cur.fetchone())
