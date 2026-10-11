import aiohttp
import json
import logging
import asyncio
from typing import Dict, Any, Optional, List
from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

class GeminiClient:
    """
    Asynchronous Google Gemini API client supporting text, structured JSON,
    and reference-guided generation.
    """
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model = model or GEMINI_MODEL
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    async def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_output_tokens: int = 8192,
        model_override: Optional[str] = None
    ) -> str:
        """Generate plain text or formatted markdown response from Gemini."""
        payload = self._build_payload(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            json_mode=False
        )
        return await self._call_api(payload, model_override=model_override)

    async def generate_json(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.4,
        max_output_tokens: int = 8192,
        model_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate and parse structured JSON from Gemini."""
        payload = self._build_payload(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            json_mode=True
        )
        raw_text = await self._call_api(payload, model_override=model_override)
        return self._parse_json(raw_text)

    def _build_payload(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.6,
        max_output_tokens: int = 8192,
        json_mode: bool = False
    ) -> Dict[str, Any]:
        contents = [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ]
        generation_config = {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        }
        if json_mode:
            generation_config["responseMimeType"] = "application/json"

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config
        }

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        return payload

    async def _call_api(self, payload: Dict[str, Any], model_override: Optional[str] = None) -> str:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY не установлен. Укажите ключ в файле .env")

        models_to_try = [
            model_override or self.model,
            "gemini-flash-latest",
            "gemini-3.8-flash",
            "gemini-pro-latest",
            "gemini-3.7-flash",
            "gemini-3.5-flash"
        ]
        # Remove duplicates while preserving order
        unique_models = list(dict.fromkeys(models_to_try))

        last_error = None
        for model in unique_models:
            url = f"{self.base_url}/{model}:generateContent?key={self.api_key}"
            for attempt in range(3):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            url,
                            headers={"Content-Type": "application/json"},
                            json=payload,
                            timeout=aiohttp.ClientTimeout(total=120)
                        ) as response:
                            if response.status == 200:
                                data = await response.json()
                                candidates = data.get("candidates", [])
                                if not candidates:
                                    raise ValueError("Gemini вернул пустой список кандидатов.")
                                parts = candidates[0].get("content", {}).get("parts", [])
                                if not parts:
                                    raise ValueError("Ответ Gemini не содержит текстовых блоков.")
                                return "".join(p.get("text", "") for p in parts)
                            elif response.status in (429, 503):
                                logger.warning(f"Status {response.status} on model {model}, attempt {attempt+1}. Falling back to next model...")
                                if attempt == 0:
                                    await asyncio.sleep(1)
                                    continue
                                break
                            else:
                                error_text = await response.text()
                                logger.warning(f"Error {response.status} from {model}: {error_text}")
                                last_error = f"HTTP {response.status}: {error_text}"
                                break
                except Exception as e:
                    logger.warning(f"Connection exception on {model}, attempt {attempt+1}: {e}")
                    last_error = str(e)
                    await asyncio.sleep(1)

        raise RuntimeError(f"Не удалось получить ответ от Gemini API: {last_error}")

    def _parse_json(self, raw_text: str) -> Dict[str, Any]:
        """Strip markdown fences and parse json safely."""
        text = raw_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            # If JSON has trailing characters or minor errors
            start_idx = text.find("{")
            end_idx = text.rfind("}")
            if start_idx != -1 and end_idx != -1:
                return json.loads(text[start_idx:end_idx+1])
            raise e
