import base64
import io
import tempfile
import unittest
from unittest.mock import Mock, patch
from PIL import Image
from tools import posters
from tools.correction_task import correct_library


def png(width, height):
    output = io.BytesIO()
    Image.new("RGB", (width, height), "green").save(output, "PNG")
    return output.getvalue()


class PosterTests(unittest.TestCase):
    def test_validation_and_lossless_snapshot(self):
        data = png(200, 300)
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"BANGUMI_KOMGA_DATA_DIR": root}):
            info = posters.store(data)
            self.assertEqual(posters.read(info["id"])[0], data)
            self.assertEqual((info["width"], info["height"]), (200, 300))
            self.assertEqual(posters.decode_upload(base64.b64encode(data).decode()), data)
            with self.assertRaises(ValueError):
                posters.decode_upload(base64.b64encode(b"<svg/>").decode())
            with self.assertRaises(ValueError):
                posters.read("../secret")

    def test_replacement_only_higher_resolution_and_lock_policy(self):
        client = Mock()
        item = {"id": "s", "metadata": {}}
        with patch.object(posters, "protected", return_value=True), patch.object(posters, "offline_candidate") as candidate:
            result, reason = posters.replace_offline(client, item, "series", {}, False, False)
            self.assertIsNone(result)
            candidate.assert_not_called()
        with patch.object(posters, "protected", return_value=False), \
             patch.object(posters, "offline_candidate", return_value=(png(100, 150), "")), \
             patch.object(posters, "capture", return_value={"id": "old", "width": 200, "height": 300}), \
             patch.object(posters, "upload") as upload:
            self.assertIsNone(posters.replace_offline(client, item, "series", {}, False, True)[0])
            upload.assert_not_called()
        with patch.object(posters, "protected", return_value=False), \
             patch.object(posters, "offline_candidate", return_value=(png(400, 600), "")), \
             patch.object(posters, "capture", return_value={"id": "old", "width": 200, "height": 300}), \
             patch.object(posters, "upload", return_value={"id": "new", "width": 400, "height": 600}), \
             patch.object(posters, "local_lock") as lock:
            result, _ = posters.replace_offline(client, item, "series", {}, False, True)
            self.assertEqual(result[1]["thumbnail"]["id"], "new")
            lock.assert_called_once_with(client, "s", "series", True)

    def test_official_archive_without_posters_skips(self):
        with tempfile.TemporaryDirectory() as root, patch("bangumi_archive.sqlite_store.ArchiveStore") as archive:
            archive.return_value.get.return_value = {"id": 123}
            data, reason = posters.offline_candidate({"metadata":{"links":[{"url":"https://bgm.tv/subject/123"}]}},
                                                    {"ARCHIVE_FILES_DIR":root})
            self.assertIsNone(data)
            self.assertIn("官方归档不含图片", reason)

    def test_correction_poster_only_records_snapshots(self):
        client = Mock()
        item = {"id": "s", "name": "Book", "metadata": {"title": "Book"}}
        client.iter_library_series.return_value = [item]
        client.get_specific_series.return_value = item
        update = Mock()
        snapshots = ({"thumbnail":{"id":"old"}}, {"thumbnail":{"id":"new"}})
        with patch.object(posters, "replace_offline", return_value=(snapshots, "")), \
             patch("tools.correction_task.record_outcome"):
            counts = correct_library(client, "lib", {}, update, Mock(), [], ["replace_poster"],
                                     include_volumes=False)
        self.assertEqual(counts["updated"], 1)
        self.assertEqual(update.call_args.args[0]["metadata_after"]["thumbnail"]["id"], "new")
        client.update_series_metadata.assert_not_called()


if __name__ == "__main__":
    unittest.main()
