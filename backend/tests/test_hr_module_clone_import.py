"""Le clonage d'un module Postgres ne plante plus avec une NameError.

`_clone_formation_async` (définie dans `create_hr_blueprint`, lancée dans un
thread par `create_platform`) appelle `ensure_module_asset_manifest`, qui
n'était pas importée : l'exception était avalée par le thread et la plateforme
passait au statut « error ».
"""

import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from routes import hr_routes
from services import teacher_asset_service


def _clone_function():
    app = Flask(__name__)
    app.register_blueprint(hr_routes.create_hr_blueprint())
    view = app.view_functions["hr.create_platform"]
    for cell in view.__closure__ or ():
        if getattr(cell.cell_contents, "__name__", "") == "_clone_formation_async":
            return cell.cell_contents
    raise AssertionError("_clone_formation_async introuvable dans create_platform")


class ModuleCloneImportTest(unittest.TestCase):
    def test_manifest_helper_is_imported_in_hr_routes(self):
        self.assertIs(
            hr_routes.ensure_module_asset_manifest,
            teacher_asset_service.ensure_module_asset_manifest,
        )

    def test_postgres_module_clone_reaches_ready(self):
        clone = _clone_function()
        with patch.object(
            hr_routes,
            "clone_postgres_course_structure",
            return_value={"source_platform_id": 3, "folder_id_map": {10: 20, 11: 21}},
        ), patch.object(
            # patch.object sans create=True : échoue si le nom n'est pas importé.
            hr_routes, "ensure_module_asset_manifest", return_value={"registered": 4}
        ) as manifest, patch.object(
            hr_routes, "set_platform_asset_binding_mode"
        ) as binding, patch.object(
            hr_routes, "set_postgres_platform_status"
        ) as set_status, patch.object(
            hr_routes, "get_db_connection", return_value=MagicMock()
        ):
            clone(
                3,
                42,
                None,
                source_module_id=5,
                postgres_clone=True,
                center_account_id=7,
                scope_to_center=True,
            )

        manifest.assert_called_once()
        self.assertEqual(manifest.call_args.kwargs["module_id"], 5)
        self.assertEqual(manifest.call_args.kwargs["center_account_id"], 7)
        binding.assert_called_once_with(42, "shared")
        statuses = [call.args[1] for call in set_status.call_args_list]
        self.assertEqual(statuses, ["ready"])


if __name__ == "__main__":
    unittest.main()
