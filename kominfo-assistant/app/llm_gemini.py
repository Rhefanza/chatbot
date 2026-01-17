# app/llm_gemini.py
import time
import json
import requests
from typing import Optional, Dict, Any


class GeminiLLM:
    def __init__(self, api_key: str, model: str = "gemini-3-flash-preview"):
        self.api_key = api_key
        self.model = model

    def generate(
        self,
        prompt: str,
        *,
        timeout: int = 60,
        max_retries: int = 2,
        as_json: bool = False,
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Return plain text by default.
        If as_json=True and response_schema provided, request JSON-mode output.
        """
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )

        generation_config: Dict[str, Any] = {
            "temperature": 0.2,
            "topP": 0.9,
            "maxOutputTokens": 1024,
        }

        # ✅ JSON mode (structured output)
        if as_json and response_schema:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = response_schema

        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }

        last_err_text = ""
        for attempt in range(max_retries + 1):
            try:
                r = requests.post(url, json=payload, timeout=timeout)
                print("[gemini] status:", r.status_code)

                # ✅ retry only for overload / rate limit
                if r.status_code in (429, 503):
                    last_err_text = r.text[:1200]
                    if attempt < max_retries:
                        sleep_s = 1.5 * (attempt + 1)
                        time.sleep(sleep_s)
                        continue
                    return ""

                if r.status_code != 200:
                    try:
                        print("[gemini] body:", r.text[:1200])
                    except Exception:
                        pass
                    return ""

                try:
                    data = r.json()
                except Exception:
                    return ""

                # ✅ Debug penting: promptFeedback / candidates / finishReason
                pf = data.get("promptFeedback")
                if pf:
                    try:
                        print("[gemini] promptFeedback:", json.dumps(pf)[:600])
                    except Exception:
                        pass

                cands = data.get("candidates") or []
                if not cands:
                    # sering terjadi pada beberapa kasus safety/empty
                    try:
                        print("[gemini] empty candidates; body:", r.text[:1200])
                    except Exception:
                        pass
                    return ""

                cand0 = cands[0] or {}
                fr = cand0.get("finishReason")
                if fr:
                    print("[gemini] finishReason:", fr)

                content = cand0.get("content") or {}
                parts = content.get("parts") or []

                texts = []
                for p in parts:
                    t = p.get("text")
                    if t:
                        texts.append(t)

                out = "\n".join(texts).strip()

                # ✅ kalau JSON mode tapi model balikin non-json, tetap return apa adanya
                return out

            except Exception as e:
                last_err_text = str(e)
                if attempt < max_retries:
                    time.sleep(1.2 * (attempt + 1))
                    continue
                print("[gemini] exception:", last_err_text)
                return ""

        return ""
