import unittest
from unittest.mock import MagicMock, patch

from services.azure_blob_service import get_blob_size


class AzureBlobServiceTests(unittest.TestCase):
    def test_get_blob_size_reads_blob_properties(self):
        service = MagicMock()
        blob_client = service.get_blob_client.return_value
        blob_client.get_blob_properties.return_value.size = 123456

        with patch(
            "services.azure_blob_service._get_blob_service_client",
            return_value=service,
        ):
            size = get_blob_size("audiostts", "platform-1/folder-3/playlist/cours.mp3")

        self.assertEqual(size, 123456)
        service.get_blob_client.assert_called_once_with(
            container="audiostts",
            blob="platform-1/folder-3/playlist/cours.mp3",
        )


if __name__ == "__main__":
    unittest.main()
