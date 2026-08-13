import unittest
from unittest.mock import Mock, patch

from services.formation_pipeline_service import get_rncp_certification


class RncpCertificationLookupTest(unittest.TestCase):
    @patch("services.formation_pipeline_service._http.get")
    def test_reads_the_exact_official_title_status_and_reac(self, http_get):
        response = Mock(status_code=200)
        response.text = """
            <h2 class="title--page--generic">TP - Employé commercial</h2>
            <span class="tag--fcpt-certification__status font-bold">RNCP37099</span>
            <span>Etat :</span>
            <span class="tag--fcpt-certification__status font-bold">Active</span>
            <a href="/wp-json/api/v1/activity/export/12/34"
               title="Référentiel d’activité, de compétences et d’évaluation">REAC</a>
        """
        http_get.return_value = response

        result = get_rncp_certification("RNCP37099")

        self.assertEqual(result["title"], "TP - Employé commercial")
        self.assertTrue(result["active"])
        self.assertTrue(result["reac_available"])
        self.assertEqual(
            result["source_url"],
            "https://www.francecompetences.fr/recherche/rncp/37099/",
        )

    @patch("services.formation_pipeline_service._http.get")
    def test_marks_an_inactive_record_without_reac_as_unavailable(self, http_get):
        response = Mock(status_code=200)
        response.text = """
            <h2 class="title--page--generic">Ancien titre</h2>
            <span class="tag--fcpt-certification__status">RNCP12345</span>
            <span>Etat :</span>
            <span class="tag--fcpt-certification__status">Inactive</span>
        """
        http_get.return_value = response

        result = get_rncp_certification("12345")

        self.assertFalse(result["active"])
        self.assertFalse(result["reac_available"])

    @patch("services.formation_pipeline_service._http.get")
    def test_returns_none_when_the_official_page_does_not_identify_the_code(self, http_get):
        response = Mock(status_code=200, text="<html>Certification introuvable</html>")
        http_get.return_value = response

        self.assertIsNone(get_rncp_certification("12345"))


if __name__ == "__main__":
    unittest.main()
