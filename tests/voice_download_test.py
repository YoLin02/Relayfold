import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from voice_models import Artifact, fetch_artifact, part_path, transfer_range


class VoiceDownloadTest(unittest.IsolatedAsyncioTestCase):
    async def test_resumes_partial_download_and_falls_back_to_second_source(self):
        payload = b"0123456789"
        artifact = Artifact("model.safetensors", len(payload), hashlib.sha256(payload).hexdigest())
        requests = []

        def serve(request):
            start, end = map(int, request.headers["range"].removeprefix("bytes=").split("-"))
            requests.append((request.url.host, start, end))
            if request.url.host == "first.test":
                return httpx.Response(503)
            return httpx.Response(206, headers={"Content-Range": f"bytes {start}-{end}/{len(payload)}"},
                                  content=payload[start:end + 1])

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / artifact.name
            part = part_path(target)
            part.write_bytes(payload[:3])
            async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
                with patch("voice_models.RANGE_BYTES", 4):
                    await fetch_artifact(client, ("https://first.test/model", "https://second.test/model"),
                                         target, artifact, lambda _: None)
            self.assertEqual(target.read_bytes(), payload)
            self.assertFalse(part.exists())
            self.assertEqual(requests, [("first.test", 3, 6), ("second.test", 3, 6),
                                        ("first.test", 7, 9), ("second.test", 7, 9)])

    async def test_invalid_range_cannot_extend_a_partial_file(self):
        async def serve(_):
            return httpx.Response(206, headers={"Content-Range": "bytes 0-9/10"}, content=b"0123456789")

        with tempfile.TemporaryDirectory() as directory:
            part = Path(directory) / "model.part"
            part.write_bytes(b"012")
            async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
                with self.assertRaisesRegex(ValueError, "分段范围"):
                    await transfer_range(client, "https://example.test/model", part, 10, lambda _: None)
            self.assertEqual(part.read_bytes(), b"012")

    async def test_checksum_failure_never_publishes_a_file(self):
        artifact = Artifact("model", 3, hashlib.sha256(b"abc").hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / artifact.name
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"bad"))) as client:
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    await fetch_artifact(client, ("https://example.test/model",), target, artifact, lambda _: None)
            self.assertFalse(target.exists())
            self.assertFalse(part_path(target).exists())
