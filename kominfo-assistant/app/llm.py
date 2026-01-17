class LLMClient:
    def generate(self, prompt: str) -> str:
        raise NotImplementedError
class DummyLLM(LLMClient):
    def generate(self, prompt: str) -> str:
        return "Ringkasan dummy (LLM belum diaktifkan)."
