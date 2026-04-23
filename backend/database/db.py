# db.py - Gestion de la base de données
import sqlite3
from datetime import datetime
from config import DB_PATH, FRANCE_TZ
from utils.logger import get_logger

logger = get_logger(__name__)


def get_db_connection():
    """Retourne une connexion à la base de données SQLite"""
    return sqlite3.connect(DB_PATH)


def init_database():
    """Initialise la base de données avec les tables nécessaires"""
    logger.info("🗄️ Initialisation de la base de données...")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        logger.info("✅ Connexion à la base de données réussie")

        # Table des logs existante
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT,
            prenom TEXT,
            arrivee TEXT,
            depart TEXT
        )
        """
        )
        logger.info("✅ Table logs créée/vérifiée")

        # Table pour suivre les visites de /video
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS video_visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_id INTEGER,
                timestamp TEXT
            )
            """
        )
        logger.info("✅ Table video_visits créée/vérifiée")

        # Table pour stocker l'heure de début du cours
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS cours_config (
                id INTEGER PRIMARY KEY,
                heure_debut TEXT NOT NULL
            )
            """
        )
        logger.info("✅ Table cours_config créée/vérifiée")

        # Insérer une heure par défaut si la table est vide
        cursor.execute("SELECT COUNT(*) FROM cours_config")
        count = cursor.fetchone()[0]
        logger.info(f"📊 Nombre d'entrées dans cours_config: {count}")

        if count == 0:
            # Heure par défaut en heure française
            heure_defaut_naive = datetime(2025, 5, 28, 16, 35, 0)
            heure_defaut = FRANCE_TZ.localize(heure_defaut_naive).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            cursor.execute(
                "INSERT INTO cours_config (id, heure_debut) VALUES (1, ?)",
                (heure_defaut,),
            )
            logger.info(f"✅ Heure par défaut insérée: {heure_defaut}")
        else:
            logger.info("ℹ️ Configuration cours déjà présente")

        # Table de configuration par plateforme (3 lignes fixes)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_config (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                upload_locked INTEGER DEFAULT 1,
                pdf_filename TEXT,
                pdf_uploaded_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        logger.info("✅ Table platform_config créée/vérifiée")

        # Table des demandes de suppression des contributeurs
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS deletion_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                requester_name TEXT NOT NULL,
                reason TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                resolved_at TEXT
            )
            """
        )
        logger.info("✅ Table deletion_requests créée/vérifiée")

        # Seed plateformes si la table est vide
        cursor.execute("SELECT COUNT(*) FROM platform_config")
        pc_count = cursor.fetchone()[0]
        if pc_count == 0:
            now_str = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
            cursor.executemany(
                "INSERT INTO platform_config (id, name, upload_locked, updated_at) VALUES (?, ?, 1, ?)",
                [
                    (1, "Formation 1 TP CRCD", now_str),
                    (2, "Formation 2 TP EC", now_str),
                    (3, "Formation 3 TP EC", now_str),
                    (4, "Formation Courte", now_str),
                ],
            )
            logger.info("✅ 4 plateformes insérées dans platform_config")
        else:
            logger.info("ℹ️ platform_config déjà peuplée")

        # Migration des noms de plateformes
        cursor.executemany(
            "UPDATE platform_config SET name = ? WHERE id = ?",
            [
                ("Formation 1 TP CRCD", 1),
                ("Formation 2 TP EC", 2),
                ("Formation 3 TP EC", 3),
            ],
        )

        # Migration : ajouter P4 si absent
        cursor.execute("SELECT COUNT(*) FROM platform_config WHERE id = 4")
        if cursor.fetchone()[0] == 0:
            now_str = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "INSERT INTO platform_config (id, name, upload_locked, updated_at) VALUES (?, ?, 1, ?)",
                (4, "Formation Courte", now_str),
            )
            logger.info("✅ Plateforme 4 (Formation Courte) insérée dans platform_config")

        # Migration : ajout colonne playlist_mode si absente
        cursor.execute("PRAGMA table_info(platform_config)")
        columns = [col[1] for col in cursor.fetchall()]
        if "playlist_mode" not in columns:
            cursor.execute("ALTER TABLE platform_config ADD COLUMN playlist_mode TEXT DEFAULT NULL")
            logger.info("✅ Colonne playlist_mode ajoutée à platform_config")

        # Migration multi-tenant : colonnes containers dans platform_config
        cursor.execute("PRAGMA table_info(platform_config)")
        pc_columns = [col[1] for col in cursor.fetchall()]
        if "audio_container" not in pc_columns:
            cursor.execute("ALTER TABLE platform_config ADD COLUMN audio_container TEXT")
            cursor.execute("ALTER TABLE platform_config ADD COLUMN pdf_container TEXT")
            cursor.execute("ALTER TABLE platform_config ADD COLUMN archive_container TEXT")
            cursor.execute("ALTER TABLE platform_config ADD COLUMN audio_base_url TEXT")
            cursor.execute("ALTER TABLE platform_config ADD COLUMN slug TEXT")
            # Peupler les valeurs par défaut pour les plateformes existantes
            cursor.execute("UPDATE platform_config SET audio_container = 'formationaudio-dev', pdf_container = 'formationpdf', archive_container = 'formationaudio-archives', slug = 'formation-1' WHERE id = 1")
            cursor.execute("UPDATE platform_config SET audio_container = 'formationaudio-p2', pdf_container = 'formationpdf-p2', archive_container = 'formationaudio-archives-p2', slug = 'formation-2' WHERE id = 2")
            cursor.execute("UPDATE platform_config SET audio_container = 'formationaudio-p3', pdf_container = 'formationpdf-p3', archive_container = 'formationaudio-p3-archives', slug = 'formation-3' WHERE id = 3")
            cursor.execute("UPDATE platform_config SET audio_container = 'formationaudio-p4', pdf_container = 'formationpdf-p4', archive_container = 'formationaudio-p4-archives', slug = 'formation-courte' WHERE id = 4")
            logger.info("✅ Colonnes multi-tenant ajoutées à platform_config")

        # Migration multi-tenant : platform_id dans logs
        cursor.execute("PRAGMA table_info(logs)")
        logs_columns = [col[1] for col in cursor.fetchall()]
        if "platform_id" not in logs_columns:
            cursor.execute("ALTER TABLE logs ADD COLUMN platform_id INTEGER DEFAULT 1")
            logger.info("✅ Colonne platform_id ajoutée à logs")

        # Migration multi-tenant : platform_id dans video_visits
        cursor.execute("PRAGMA table_info(video_visits)")
        vv_columns = [col[1] for col in cursor.fetchall()]
        if "platform_id" not in vv_columns:
            cursor.execute("ALTER TABLE video_visits ADD COLUMN platform_id INTEGER DEFAULT 1")
            logger.info("✅ Colonne platform_id ajoutée à video_visits")

        # Migration multi-tenant : cours_config avec platform_id
        cursor.execute("PRAGMA table_info(cours_config)")
        cc_columns = [col[1] for col in cursor.fetchall()]
        if "platform_id" not in cc_columns:
            # Ajouter platform_id et copier la config existante pour toutes les plateformes
            cursor.execute("ALTER TABLE cours_config ADD COLUMN platform_id INTEGER")
            cursor.execute("UPDATE cours_config SET platform_id = 1 WHERE id = 1")
            # Créer une entrée par défaut pour chaque plateforme existante
            cursor.execute("SELECT heure_debut FROM cours_config WHERE id = 1")
            default_row = cursor.fetchone()
            if default_row:
                default_heure = default_row[0]
                for pid in [2, 3, 4]:
                    cursor.execute("SELECT COUNT(*) FROM cours_config WHERE platform_id = ?", (pid,))
                    if cursor.fetchone()[0] == 0:
                        cursor.execute("INSERT INTO cours_config (id, heure_debut, platform_id) VALUES (?, ?, ?)", (pid, default_heure, pid))
            logger.info("✅ cours_config migrée en multi-platform")

        # Table des dossiers de cours
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS cours_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        )
        # Migration : ajouter la colonne position si elle n'existe pas encore
        try:
            cursor.execute("ALTER TABLE cours_folders ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
            logger.info("✅ Colonne position ajoutée à cours_folders")
            # Initialiser les positions existantes par ordre de création
            cursor.execute("""
                UPDATE cours_folders SET position = (
                    SELECT COUNT(*) FROM cours_folders cf2
                    WHERE cf2.platform_id = cours_folders.platform_id
                    AND cf2.created_at <= cours_folders.created_at
                    AND cf2.id <= cours_folders.id
                ) - 1
            """)
        except Exception:
            pass  # Colonne déjà présente
        logger.info("✅ Table cours_folders créée/vérifiée")

        # Table des documents de cours (PDFs + audios générés)
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS cours_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            status TEXT DEFAULT 'uploaded',
            audio_filename TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (folder_id) REFERENCES cours_folders(id)
        )
        """
        )
        logger.info("✅ Table cours_documents créée/vérifiée")

        # Table des jobs de génération de contenu TTS-direct
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS content_generation_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL UNIQUE,
            platform_id INTEGER NOT NULL,
            program_text TEXT NOT NULL,
            program_title TEXT DEFAULT '',
            sub_parts TEXT DEFAULT '[]',
            status TEXT DEFAULT 'idle',
            current_sub_part INTEGER DEFAULT 0,
            current_passe INTEGER DEFAULT 1,
            total_words INTEGER DEFAULT 0,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (folder_id) REFERENCES cours_folders(id)
        )
        """)
        logger.info("✅ Table content_generation_jobs créée/vérifiée")

        # Table des segments générés (checkpointing)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS content_generation_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            sub_part_index INTEGER NOT NULL,
            sub_part_name TEXT NOT NULL,
            passe INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            text_content TEXT DEFAULT '',
            word_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES content_generation_jobs(id),
            UNIQUE(job_id, sub_part_index, passe)
        )
        """)
        logger.info("✅ Table content_generation_segments créée/vérifiée")

        # Migration : ajouter colonne dirty si elle n'existe pas
        try:
            cursor.execute("ALTER TABLE content_generation_segments ADD COLUMN dirty INTEGER DEFAULT 0")
            logger.info("✅ Colonne dirty ajoutée à content_generation_segments")
        except Exception:
            pass  # Colonne déjà présente

        # Migration : ajouter colonnes from_scratch + module_contents (pipeline formation)
        cursor.execute("PRAGMA table_info(content_generation_jobs)")
        cg_columns = [col[1] for col in cursor.fetchall()]
        if "from_scratch" not in cg_columns:
            cursor.execute("ALTER TABLE content_generation_jobs ADD COLUMN from_scratch INTEGER DEFAULT 0")
            logger.info("✅ Colonne from_scratch ajoutée à content_generation_jobs")
        if "module_contents" not in cg_columns:
            cursor.execute("ALTER TABLE content_generation_jobs ADD COLUMN module_contents TEXT DEFAULT '{}'")
            logger.info("✅ Colonne module_contents ajoutée à content_generation_jobs")

        # Table des jobs pipeline formation automatisé
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS formation_pipeline_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL DEFAULT 1,
            tp_name TEXT NOT NULL,
            rncp_code TEXT,
            total_hours INTEGER NOT NULL,
            nb_days INTEGER NOT NULL,
            reac_text TEXT,
            global_program TEXT,
            global_program_validated INTEGER DEFAULT 0,
            daily_programs TEXT DEFAULT '[]',
            daily_programs_validated INTEGER DEFAULT 0,
            status TEXT DEFAULT 'init',
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        logger.info("✅ Table formation_pipeline_jobs créée/vérifiée")

        # Migration : colonnes rc_text + rome_text
        cursor.execute("PRAGMA table_info(formation_pipeline_jobs)")
        fpj_cols = [col[1] for col in cursor.fetchall()]
        if "rc_text" not in fpj_cols:
            cursor.execute("ALTER TABLE formation_pipeline_jobs ADD COLUMN rc_text TEXT")
            logger.info("✅ Colonne rc_text ajoutée à formation_pipeline_jobs")
        if "rome_text" not in fpj_cols:
            cursor.execute("ALTER TABLE formation_pipeline_jobs ADD COLUMN rome_text TEXT")
            logger.info("✅ Colonne rome_text ajoutée à formation_pipeline_jobs")

        # ─── Couche 1 : Knowledge Base enrichie depuis REAC ──────────────────
        # Chaque compétence du REAC est enrichie par Claude avec définition
        # pédagogique, études de cas, pièges, vocabulaire, contexte terrain,
        # liens connexes. Objectif : passer le matériau source de ~15k mots
        # (REAC brut) à ~120-150k mots exploitables pour la génération du
        # programme de formation. Checkpointing + flag dirty permettent de
        # régénérer sélectivement une compétence éditée.
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS formation_knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            competence_index INTEGER NOT NULL,
            competence_key TEXT NOT NULL,
            competence_title TEXT NOT NULL,
            bloc TEXT,
            raw_source TEXT,
            definition_pedagogique TEXT DEFAULT '',
            etudes_de_cas TEXT DEFAULT '[]',
            pieges_frequents TEXT DEFAULT '[]',
            vocabulaire_metier TEXT DEFAULT '{}',
            contexte_terrain TEXT DEFAULT '',
            liens_connexes TEXT DEFAULT '[]',
            status TEXT DEFAULT 'pending',
            dirty INTEGER DEFAULT 0,
            error_message TEXT,
            total_words INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES formation_pipeline_jobs(id),
            UNIQUE(job_id, competence_index)
        )
        """)
        logger.info("✅ Table formation_knowledge_base créée/vérifiée")

        conn.commit()
        conn.close()
        logger.info("✅ Base de données initialisée avec succès")

    except Exception as e:
        logger.error(f"❌ Erreur lors de l'initialisation de la base: {e}")
        raise
