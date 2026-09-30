import copy
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from database import db as database_db
from repositories import day_schedule_repository as repo
from services.dynamic_day_schedule_service import ScheduleValidationError


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _make_database() -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE training_center_accounts (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL
        );
        CREATE TABLE platform_config (
            id INTEGER PRIMARY KEY,
            center_account_id INTEGER
        );
        CREATE TABLE formation_pipeline_jobs (
            id INTEGER PRIMARY KEY,
            platform_id INTEGER NOT NULL,
            nb_days INTEGER NOT NULL,
            schedule_schema_version INTEGER NOT NULL DEFAULT 1,
            schedule_snapshot_json TEXT,
            schedule_hash TEXT,
            schedule_locked_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE formation_modules (
            id INTEGER PRIMARY KEY,
            center_account_id INTEGER,
            nb_days INTEGER,
            schedule_schema_version INTEGER NOT NULL DEFAULT 1,
            schedule_hash TEXT,
            schedule_locked_at TEXT
        );
        CREATE TABLE day_schedule_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            center_account_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            schedule_schema_version INTEGER NOT NULL DEFAULT 2,
            blocks_snapshot_json TEXT NOT NULL DEFAULT '[]',
            blocks_hash TEXT NOT NULL,
            block_count INTEGER NOT NULL DEFAULT 0,
            total_duration_minutes INTEGER NOT NULL DEFAULT 0,
            course_duration_minutes INTEGER NOT NULL DEFAULT 0,
            used_at TEXT,
            locked_at TEXT,
            deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE day_schedule_template_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            block_key TEXT NOT NULL,
            position INTEGER NOT NULL,
            block_type TEXT NOT NULL,
            pause_kind TEXT,
            start_minute INTEGER NOT NULL,
            end_minute INTEGER NOT NULL,
            duration_minutes INTEGER NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(template_id, position),
            UNIQUE(template_id, block_key)
        );
        CREATE TABLE formation_module_days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module_id INTEGER NOT NULL,
            center_account_id INTEGER NOT NULL,
            day_index INTEGER NOT NULL,
            source_template_id INTEGER,
            template_name TEXT NOT NULL,
            schedule_schema_version INTEGER NOT NULL DEFAULT 2,
            schedule_hash TEXT NOT NULL,
            blocks_snapshot_json TEXT NOT NULL,
            block_count INTEGER NOT NULL,
            total_duration_minutes INTEGER NOT NULL,
            course_duration_minutes INTEGER NOT NULL,
            immutable INTEGER NOT NULL DEFAULT 1,
            locked_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(module_id, day_index)
        );
        CREATE TABLE cours_folders (
            id INTEGER PRIMARY KEY,
            platform_id INTEGER NOT NULL,
            formation_job_id INTEGER,
            module_day_id INTEGER,
            position INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE course_sessions (
            id INTEGER PRIMARY KEY,
            platform_id INTEGER NOT NULL,
            session_index INTEGER NOT NULL,
            module_day_id INTEGER
        );
        INSERT INTO training_center_accounts VALUES
            (1, 'centre-1'), (2, 'centre-2');
        INSERT INTO platform_config VALUES (10, 1), (20, 2);
        INSERT INTO formation_modules (
            id, center_account_id, schedule_schema_version
        ) VALUES (100, 1, 1), (200, 2, 1);
        INSERT INTO formation_pipeline_jobs (
            id, platform_id, nb_days, schedule_schema_version,
            schedule_snapshot_json, schedule_hash, schedule_locked_at, updated_at
        ) VALUES (
            500, 10, 1, 2,
            '{"schema_version":2,"days":[{"day_index":1,"blocks":[]}]}',
            'job-hash', '2026-07-01 12:00:00', '2026-07-01 12:00:00'
        ), (
            501, 10, 1, 1, NULL, NULL, NULL, '2026-07-01 12:00:00'
        );
        INSERT INTO cours_folders (
            id, platform_id, formation_job_id, position
        ) VALUES (900, 10, 500, 0);
        INSERT INTO course_sessions (
            id, platform_id, session_index, module_day_id
        ) VALUES (800, 10, 1, NULL);
        """
    )
    canonical_blocks = repo._validated_canonical_blocks(_blocks())
    schedule_hash = repo._module_schedule_fingerprint(
        [{"blocks": canonical_blocks}]
    )
    conn.execute(
        """
        UPDATE formation_pipeline_jobs
        SET schedule_snapshot_json = ?, schedule_hash = ?
        WHERE id = 500
        """,
        (
            json.dumps(
                {
                    "schema_version": 2,
                    "day_count": 1,
                    "schedule_hash": schedule_hash,
                    "days": [{"day_index": 1, "blocks": canonical_blocks}],
                }
            ),
            schedule_hash,
        ),
    )
    conn.commit()
    conn.close()
    return tmp.name


def _blocks(course_end=585):
    durations = (
        ("course", None, course_end - 540),
        ("qa", None, 15),
        ("pause", "short", 15),
        ("course", None, 65),
        ("qa", None, 15),
        ("pause", "lunch", 60),
        ("course", None, 65),
        ("qa", None, 15),
        ("pause", "short", 15),
        ("course", None, 65),
        ("qa", None, 15),
    )
    cursor = 540
    blocks = []
    for index, (block_type, pause_kind, duration) in enumerate(
        durations,
        start=1,
    ):
        block = {
            "block_key": f"{block_type}-{index}",
            "type": block_type,
            "start_minute": cursor,
            "duration_min": duration,
            "end_minute": cursor + duration,
        }
        if pause_kind is not None:
            block["subtype"] = pause_kind
        blocks.append(block)
        cursor += duration
    return blocks


class DayScheduleRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.db_path = _make_database()
        self.patches = (
            patch.object(repo, "day_schedule_store_is_postgres", return_value=False),
            patch.object(
                repo,
                "get_db_connection",
                side_effect=lambda: sqlite3.connect(self.db_path),
            ),
        )
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self):
        for active_patch in reversed(self.patches):
            active_patch.stop()
        os.unlink(self.db_path)

    def test_library_is_tenant_scoped_and_unused_template_can_be_updated(self):
        first = repo.create_template(1, "Journée standard", _blocks())
        second = repo.create_template(2, "Template autre centre", _blocks())

        self.assertEqual([item["id"] for item in repo.list_templates(1)], [first["id"]])
        self.assertIsNone(repo.get_template(1, second["id"]))
        self.assertEqual(first["block_count"], 11)
        self.assertEqual(first["course_duration_minutes"], 240)

        updated = repo.update_template(
            1,
            first["id"],
            name="Journée standard corrigée",
            blocks=_blocks(course_end=600),
        )
        self.assertEqual(updated["name"], "Journée standard corrigée")
        self.assertEqual(updated["course_duration_minutes"], 255)
        self.assertEqual(updated["blocks"][0]["duration_minutes"], 60)

    def test_repository_rejects_template_outside_the_complete_v2_contract(self):
        invalid_blocks = _blocks()[:3]
        with self.assertRaises(ScheduleValidationError):
            repo.create_template(
                1,
                "Journée incomplète",
                invalid_blocks,
            )
        canonical_invalid = repo._canonicalize_blocks(invalid_blocks)
        invalid_hash = repo._module_schedule_fingerprint(
            [{"blocks": canonical_invalid}]
        )
        with self.assertRaises(ScheduleValidationError):
            repo.lock_pipeline_schedule_snapshot(
                1,
                501,
                {
                    "schema_version": 2,
                    "schedule_hash": invalid_hash,
                    "day_count": 1,
                    "days": [
                        {"day_index": 1, "blocks": canonical_invalid}
                    ],
                },
            )

        fractional = copy.deepcopy(_blocks())
        fractional[0]["start_minute"] = 540.5
        with self.assertRaisesRegex(ValueError, "minute entière"):
            repo.create_template(1, "Minutes fractionnaires", fractional)

    def test_used_template_is_immutable_but_can_be_soft_deleted(self):
        template = repo.create_template(1, "Journée utilisée", _blocks())
        self.assertIsNone(
            repo.mark_template_used(
                1,
                template["id"],
                expected_blocks_hash="0" * 64,
            )
        )
        used = repo.mark_template_used(
            1,
            template["id"],
            expected_blocks_hash=template["blocks_hash"],
            used_at=datetime(2026, 7, 1, 12, 0),
        )
        self.assertIsNotNone(used["used_at"])
        self.assertIsNotNone(used["locked_at"])

        with self.assertRaises(repo.TemplateImmutableError):
            repo.update_template(1, template["id"], name="Modification interdite")

        self.assertTrue(repo.soft_delete_template(1, template["id"]))
        self.assertIsNone(repo.get_template(1, template["id"]))
        deleted = repo.get_template(1, template["id"], include_deleted=True)
        self.assertEqual(deleted["status"], "deleted")
        self.assertEqual(len(deleted["blocks"]), 11)

    def test_module_day_snapshots_are_self_contained_immutable_and_idempotent(self):
        template = repo.create_template(1, "Journée A", _blocks())
        days = [
            {"day_index": 1, "template_id": template["id"]},
            {"day_index": 2, "template_id": template["id"]},
        ]
        created = repo.create_module_day_snapshots(
            1,
            100,
            days,
            locked_at=datetime(2026, 7, 2, 9, 0),
        )
        self.assertEqual([day["day_index"] for day in created], [1, 2])
        self.assertEqual(created[0]["blocks"][0]["block_type"], "course")
        self.assertTrue(created[0]["immutable"])

        repeated = repo.create_module_day_snapshots(1, 100, days)
        self.assertEqual(
            [day["schedule_hash"] for day in repeated],
            [day["schedule_hash"] for day in created],
        )
        with self.assertRaises(repo.ImmutableModuleScheduleError):
            repo.create_module_day_snapshots(
                1,
                100,
                [
                    {
                        "day_index": 1,
                        "template_id": template["id"],
                        "blocks": _blocks(course_end=600),
                    },
                    {"day_index": 2, "template_id": template["id"]},
                ],
            )

        conn = sqlite3.connect(self.db_path)
        module = conn.execute(
            """
            SELECT nb_days, schedule_schema_version, schedule_hash,
                   schedule_locked_at
            FROM formation_modules
            WHERE id = 100
            """
        ).fetchone()
        template_lock = conn.execute(
            "SELECT used_at, locked_at FROM day_schedule_templates WHERE id = ?",
            (template["id"],),
        ).fetchone()
        conn.close()
        self.assertEqual(module[0:2], (2, 2))
        self.assertTrue(module[2])
        self.assertTrue(module[3])
        self.assertTrue(template_lock[0])
        self.assertTrue(template_lock[1])

    def test_folder_reads_prefer_module_day_and_offer_job_snapshot_fallback(self):
        template = repo.create_template(1, "Journée A", _blocks())
        day = repo.create_module_day_snapshots(
            1,
            100,
            [{"day_index": 1, "template_id": template["id"]}],
        )[0]
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE cours_folders SET module_day_id = ? WHERE id = 900",
            (day["id"],),
        )
        conn.commit()
        conn.close()

        resolved = repo.get_module_day_for_folder(900, center_account_id=1)
        self.assertEqual(resolved["day_index"], 1)
        self.assertEqual(resolved["folder_position"], 0)
        self.assertEqual(resolved["schedule_schema_version"], 2)
        self.assertEqual(len(resolved["blocks"]), 11)
        self.assertIsNone(repo.get_module_day_for_folder(900, center_account_id=2))

        fallback = repo.get_schedule_snapshot_for_folder(900, center_account_id=1)
        self.assertEqual(fallback["schedule_schema_version"], 2)
        self.assertEqual(
            fallback["schedule_hash"],
            fallback["schedule_snapshot_json"]["schedule_hash"],
        )
        self.assertEqual(fallback["folder_position"], 0)
        self.assertEqual(fallback["schedule_snapshot_json"]["days"][0]["day_index"], 1)

    def test_module_day_reads_reject_changed_hash_or_mutable_snapshot(self):
        template = repo.create_template(1, "Journée intègre", _blocks())
        day = repo.create_module_day_snapshots(
            1,
            100,
            [{"day_index": 1, "template_id": template["id"]}],
        )[0]
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE cours_folders SET module_day_id = ? WHERE id = 900",
            (day["id"],),
        )
        conn.execute(
            "UPDATE formation_module_days SET schedule_hash = ? WHERE id = ?",
            ("corrompu", day["id"]),
        )
        conn.commit()
        conn.close()

        with self.assertRaisesRegex(
            repo.ImmutableModuleScheduleError,
            "hash",
        ):
            repo.get_module_day_for_folder(900, center_account_id=1)

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            UPDATE formation_module_days
            SET schedule_hash = ?, immutable = 0
            WHERE id = ?
            """,
            (day["schedule_hash"], day["id"]),
        )
        conn.commit()
        conn.close()
        with self.assertRaisesRegex(
            repo.ImmutableModuleScheduleError,
            "plus marqué immuable",
        ):
            repo.get_module_day_for_folder(900, center_account_id=1)

    def test_module_day_read_rejects_invalid_grammar_even_with_matching_hash(self):
        template = repo.create_template(1, "Journée complète", _blocks())
        day = repo.create_module_day_snapshots(
            1,
            100,
            [{"day_index": 1, "template_id": template["id"]}],
        )[0]
        invalid_blocks = repo._canonicalize_blocks(_blocks()[:3])
        matching_hash = repo._module_schedule_fingerprint(
            [{"blocks": invalid_blocks}]
        )
        metrics = repo._block_metrics(invalid_blocks)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            UPDATE formation_module_days
            SET blocks_snapshot_json = ?,
                schedule_hash = ?,
                block_count = ?,
                total_duration_minutes = ?,
                course_duration_minutes = ?
            WHERE id = ?
            """,
            (
                json.dumps(invalid_blocks),
                matching_hash,
                metrics["block_count"],
                metrics["total_duration_minutes"],
                metrics["course_duration_minutes"],
                day["id"],
            ),
        )
        conn.commit()
        conn.close()

        with self.assertRaisesRegex(
            repo.ImmutableModuleScheduleError,
            "illisible",
        ):
            repo.list_module_days(100, center_account_id=1)

    def test_pipeline_snapshot_lock_is_tenant_scoped_immutable_and_idempotent(self):
        canonical_blocks = repo._canonicalize_blocks(_blocks())
        schedule_hash = repo._module_schedule_fingerprint(
            [{"blocks": canonical_blocks}]
        )
        snapshot = {
            "schema_version": 2,
            "schedule_hash": schedule_hash,
            "day_count": 1,
            "days": [{"day_number": 1, "blocks": _blocks()}],
        }
        locked = repo.lock_pipeline_schedule_snapshot(
            1,
            501,
            snapshot,
            locked_at=datetime(2026, 7, 1, 13, 0),
        )
        self.assertEqual(locked["nb_days"], 1)
        self.assertEqual(locked["schedule_hash"], schedule_hash)
        self.assertEqual(
            locked["schedule_snapshot_json"]["days"][0]["day_index"],
            1,
        )

        repeated = repo.lock_pipeline_schedule_snapshot(1, 501, snapshot)
        self.assertEqual(repeated["schedule_hash"], schedule_hash)
        self.assertIsNone(repo.get_pipeline_schedule_snapshot(2, 501))
        self.assertEqual(
            repo.get_pipeline_schedule_snapshot(1, 501)["schedule_hash"],
            schedule_hash,
        )

        changed_blocks = _blocks(course_end=600)
        changed_hash = repo._module_schedule_fingerprint(
            [{"blocks": repo._canonicalize_blocks(changed_blocks)}]
        )
        with self.assertRaises(repo.ImmutablePipelineScheduleError):
            repo.lock_pipeline_schedule_snapshot(
                1,
                501,
                {
                    "schema_version": 2,
                    "schedule_hash": changed_hash,
                    "day_count": 1,
                    "days": [{"day_index": 1, "blocks": changed_blocks}],
                },
            )

    def test_locked_pipeline_snapshot_read_revalidates_lock_and_hash(self):
        canonical_blocks = repo._validated_canonical_blocks(_blocks())
        schedule_hash = repo._module_schedule_fingerprint(
            [{"blocks": canonical_blocks}]
        )
        snapshot = {
            "schema_version": 2,
            "schedule_hash": schedule_hash,
            "day_count": 1,
            "days": [{"day_index": 1, "blocks": canonical_blocks}],
        }
        repo.lock_pipeline_schedule_snapshot(1, 501, snapshot)

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE formation_pipeline_jobs SET schedule_hash = ? WHERE id = 501",
            ("corrompu",),
        )
        conn.commit()
        conn.close()
        with self.assertRaisesRegex(
            repo.ImmutablePipelineScheduleError,
            "hash",
        ):
            repo.get_pipeline_schedule_snapshot(1, 501)

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            UPDATE formation_pipeline_jobs
            SET schedule_hash = ?, schedule_locked_at = NULL
            WHERE id = 501
            """,
            (schedule_hash,),
        )
        conn.commit()
        conn.close()
        with self.assertRaisesRegex(
            repo.ImmutablePipelineScheduleError,
            "pas verrouillé",
        ):
            repo.get_pipeline_schedule_snapshot(1, 501)

    def test_module_days_bind_to_the_matching_folder_and_session_idempotently(self):
        template = repo.create_template(1, "Journée reliée", _blocks())
        day = repo.create_module_day_snapshots(
            1,
            100,
            [{"day_index": 1, "template_id": template["id"]}],
        )[0]

        bindings = repo.bind_module_days_to_platform(1, 100, 10, [900])
        repeated = repo.bind_module_days_to_platform(1, 100, 10, [900])

        self.assertEqual(bindings, repeated)
        self.assertEqual(bindings[0]["module_day_id"], day["id"])
        conn = sqlite3.connect(self.db_path)
        folder_day = conn.execute(
            "SELECT module_day_id FROM cours_folders WHERE id = 900"
        ).fetchone()[0]
        session_day = conn.execute(
            "SELECT module_day_id FROM course_sessions WHERE id = 800"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(folder_day, day["id"])
        self.assertEqual(session_day, day["id"])

        with self.assertRaisesRegex(ValueError, "nombre de dossiers"):
            repo.bind_module_days_to_platform(1, 100, 10, [])

    def test_module_day_binding_requires_exactly_one_course_session(self):
        template = repo.create_template(1, "Journée sans occurrence", _blocks())
        repo.create_module_day_snapshots(
            1,
            100,
            [{"day_index": 1, "template_id": template["id"]}],
        )
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM course_sessions WHERE id = 800")
        conn.commit()
        conn.close()

        with self.assertRaisesRegex(
            repo.ImmutableModuleScheduleError,
            "Aucune occurrence compatible",
        ):
            repo.bind_module_days_to_platform(1, 100, 10, [900])

        conn = sqlite3.connect(self.db_path)
        folder_day = conn.execute(
            "SELECT module_day_id FROM cours_folders WHERE id = 900"
        ).fetchone()[0]
        conn.close()
        self.assertIsNone(folder_day)


class DayScheduleBackendSelectionTest(unittest.TestCase):
    def test_pipeline_postgres_is_authoritative_in_hybrid_mode(self):
        with patch.object(repo, "DATABASE_BACKEND", "hybrid"), patch.object(
            repo,
            "PIPELINE_DATABASE_BACKEND",
            "postgres",
        ):
            self.assertTrue(repo.day_schedule_store_is_postgres())

    def test_hybrid_sqlite_mode_keeps_the_whole_aggregate_in_sqlite(self):
        with patch.object(repo, "DATABASE_BACKEND", "hybrid"), patch.object(
            repo,
            "PIPELINE_DATABASE_BACKEND",
            "sqlite",
        ):
            self.assertFalse(repo.day_schedule_store_is_postgres())


class DayScheduleSchemaContractTest(unittest.TestCase):
    def test_additive_sqlite_guards_protect_pre_v2_tables(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE formation_module_days (id INTEGER PRIMARY KEY);
            CREATE TABLE course_sessions (
                id INTEGER PRIMARY KEY,
                module_day_id INTEGER
            );
            CREATE TABLE cours_folders (
                id INTEGER PRIMARY KEY,
                module_day_id INTEGER
            );
            INSERT INTO formation_module_days VALUES (7);
            """
        )
        database_db._install_module_day_fk_guards(conn.cursor())
        conn.execute(
            "INSERT INTO course_sessions (id, module_day_id) VALUES (1, 7)"
        )
        conn.execute(
            "INSERT INTO cours_folders (id, module_day_id) VALUES (1, 7)"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO course_sessions (id, module_day_id) VALUES (2, 999)"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE cours_folders SET module_day_id = 999 WHERE id = 1"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM formation_module_days WHERE id = 7")
        conn.close()

    def test_postgres_schema_has_v2_tables_columns_indexes_and_rls(self):
        schema = (BACKEND_DIR / "database" / "postgres_schema.sql").read_text(
            encoding="utf-8"
        )
        for table in (
            "day_schedule_templates",
            "day_schedule_template_blocks",
            "formation_module_days",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", schema)
            self.assertIn(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY", schema)
        for column in (
            "schedule_schema_version",
            "schedule_snapshot_json",
            "schedule_hash",
            "schedule_locked_at",
        ):
            self.assertIn(
                f"ADD COLUMN IF NOT EXISTS {column}",
                schema,
            )
        self.assertIn("ADD COLUMN IF NOT EXISTS reusable_at", schema)
        self.assertIn("ADD COLUMN IF NOT EXISTS module_day_id", schema)
        self.assertIn("ADD COLUMN IF NOT EXISTS local_date", schema)
        self.assertIn("course_sessions_module_day_fkey", schema)
        self.assertIn("cours_folders_module_day_fkey", schema)

    def test_sqlite_bootstrap_declares_v2_storage(self):
        source = (BACKEND_DIR / "database" / "db.py").read_text(encoding="utf-8")
        for table in (
            "day_schedule_templates",
            "day_schedule_template_blocks",
            "formation_module_days",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", source)
        self.assertIn('"schedule_snapshot_json": "TEXT"', source)
        self.assertIn('"reusable_at": "TIMESTAMP"', source)
        self.assertIn('"module_day_id": "INTEGER"', source)
        self.assertIn('conn.execute("PRAGMA foreign_keys=ON")', source)
        self.assertIn("trg_course_sessions_module_day_insert", source)
        self.assertIn("trg_cours_folders_module_day_update", source)


if __name__ == "__main__":
    unittest.main()
