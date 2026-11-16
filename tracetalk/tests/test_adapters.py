import io
import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from tracetalk.model import ModelClient, ModelConfig, ModelError


class AdapterContractTests(unittest.TestCase):
    """HTTP contract fixtures; these do not claim to execute Ollama itself."""
    def response(self, data):
        return io.BytesIO(json.dumps(data).encode())

    def test_ollama_request_and_actual_usage_fields(self):
        client = ModelClient(ModelConfig())
        schema = {"type":"object"}
        with patch("urllib.request.urlopen", return_value=self.response({
            "message":{"content":"{}"},"prompt_eval_count":31,"eval_count":12,"done_reason":"stop"})) as opened:
            result = client.generate([{"role":"user","content":"test"}], schema, 7, 256)
            request = opened.call_args.args[0]
            body = json.loads(request.data)
            self.assertEqual(request.full_url,"http://127.0.0.1:11434/api/chat")
            self.assertFalse(body["think"])
            self.assertFalse(body["stream"])
            self.assertEqual(body["format"],schema)
            self.assertEqual(body["options"]["seed"],7)
            self.assertEqual(body["options"]["num_predict"],256)
            self.assertEqual(result["prompt_tokens"],31)
            self.assertEqual(result["completion_tokens"],12)

    def test_openai_compatible_request(self):
        client=ModelClient(ModelConfig(provider="openai",base_url="http://127.0.0.1:8080",model="test"))
        with patch("urllib.request.urlopen",return_value=self.response({"choices":[{"message":{"content":"{}"},"finish_reason":"stop"}],"usage":{"prompt_tokens":17,"completion_tokens":3}})) as opened:
            result=client.generate([], {"type":"object"}, 3, 128)
            request=opened.call_args.args[0]
            body=json.loads(request.data)
            self.assertEqual(request.full_url,"http://127.0.0.1:8080/v1/chat/completions")
            self.assertEqual(body["response_format"]["type"],"json_schema")
            self.assertFalse(body["chat_template_kwargs"]["enable_thinking"])
            self.assertEqual(result["completion_tokens"],3)

    def test_connection_failure_is_not_replaced_with_fake_text(self):
        client=ModelClient(ModelConfig())
        with patch("urllib.request.urlopen",side_effect=URLError("fixture offline")):
            self.assertFalse(client.health()["ready"])
            with self.assertRaises(ModelError):
                client.generate([],{},0,128)

    def test_health_checks_requested_model_presence(self):
        client=ModelClient(ModelConfig())
        with patch("urllib.request.urlopen",return_value=self.response({"models":[{"name":"another:model"}]})):
            health=client.health()
            self.assertTrue(health["connected"])
            self.assertFalse(health["ready"])

    def test_untagged_ollama_model_matches_its_latest_listing(self):
        listed={"models":[{"name":"tt-roundtrip:latest"},{"name":"qwen3.5:4b-q4_K_M"}]}
        for model,ready in (("tt-roundtrip",True),("tt-roundtrip:latest",True),("tt-roundtrip:v2",False),
                            ("qwen3.5:4b-q4_K_M",True),("qwen3.5",False)):
            with patch("urllib.request.urlopen",return_value=self.response(listed)):
                self.assertEqual(ModelClient(ModelConfig(model=model)).health()["ready"],ready,model)


if __name__ == "__main__":
    unittest.main()
