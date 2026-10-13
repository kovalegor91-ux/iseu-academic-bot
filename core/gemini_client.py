import re
import json
import logging
import asyncio
import aiohttp
from typing import Dict, Any, Optional, List
from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

class GeminiClient:
    """
    Asynchronous Google Gemini API client supporting text, structured JSON,
    automatic JSON syntax repair, truncation recovery, and reference-guided generation.
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
        max_output_tokens: int = 65536,
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
        temperature: float = 0.35,
        max_output_tokens: int = 65536,
        model_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate and parse structured JSON from Gemini with automatic repair and retry."""
        last_err = None
        for attempt in range(2):
            temp = temperature if attempt == 0 else 0.2
            payload = self._build_payload(
                prompt=prompt,
                system_instruction=system_instruction,
                temperature=temp,
                max_output_tokens=max_output_tokens,
                json_mode=True
            )
            raw_text = await self._call_api(payload, model_override=model_override)
            try:
                return self._parse_json(raw_text)
            except Exception as e:
                logger.warning(f"JSON parse failed on attempt {attempt + 1}: {e}. Retrying...")
                last_err = e
        raise last_err

    def _build_payload(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.5,
        max_output_tokens: int = 65536,
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
            "thinkingConfig": {
                "thinkingBudget": -1  # High reasoning effort
            }
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

        primary = model_override or self.model or "gemini-3.8-flash"
        models_to_try = [
            primary,
            "gemini-3.8-flash",
            "gemini-flash-latest"
        ]
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
                            timeout=aiohttp.ClientTimeout(total=180)
                        ) as response:
                            if response.status == 200:
                                data = await response.json()
                                candidates = data.get("candidates", [])
                                if not candidates:
                                    raise ValueError("Gemini вернул пустой список кандидатов.")
                                parts = candidates[0].get("content", {}).get("parts", [])
                                if not parts:
                                    raise ValueError("Ответ Gemini не содержит текстовых блоков.")
                                return "".join(p.get("text", "") for p in parts if not p.get("thought", False))
                            elif response.status == 400 and payload.get("generationConfig", {}).get("maxOutputTokens", 0) > 8192:
                                # Fallback for models that only allow 8192 maxOutputTokens
                                payload["generationConfig"]["maxOutputTokens"] = 8192
                                continue
                            elif response.status in (429, 503):
                                logger.warning(f"Status {response.status} on model {model}, attempt {attempt+1}/3. Waiting...")
                                await asyncio.sleep(1.5 * (attempt + 1))
                                continue
                            elif response.status == 404:
                                logger.warning(f"Model {model} returned 404. Skipping to fallback model...")
                                break
                            else:
                                error_text = await response.text()
                                logger.warning(f"Error {response.status} from {model}: {error_text}")
                                last_error = f"HTTP {response.status}: {error_text}"
                                break
                except Exception as e:
                    logger.warning(f"Connection exception on {model}, attempt {attempt+1}: {e}")
                    last_error = str(e)
                    await asyncio.sleep(1.5)

        raise RuntimeError(f"Не удалось получить ответ от Gemini API: {last_error}")

    @classmethod
    def _fix_line_inner_quotes(cls, text: str) -> str:
        """
        Fix unescaped straight double quotes inside JSON string values on a line-by-line basis.
        E.g. '  "text": "Закон "Об охране природы" РБ",' -> '  "text": "Закон «Об охране природы» РБ",'
        """
        fixed_lines = []
        # Pattern 1: "key": "value"[,]
        kv_pattern = re.compile(r'^(\s*"[^"]+"\s*:\s*")(.*)("(\s*,?\s*))$')
        # Pattern 2: array string item "value"[,]
        arr_pattern = re.compile(r'^(\s*")(?!\s*[,\]\}])(.*)("(\s*,?\s*))$')

        for line in text.splitlines():
            m_kv = kv_pattern.match(line)
            if m_kv:
                prefix, inner, suffix = m_kv.group(1), m_kv.group(2), m_kv.group(3)
                # Only fix if inner isn't actually multiple JSON tokens like "a", "b"
                if '"' in inner and not re.search(r'"\s*,\s*"', inner):
                    inner_clean = re.sub(r'(?<!\\)"', '«', inner)
                    line = f"{prefix}{inner_clean}{suffix}"
                fixed_lines.append(line)
                continue

            m_arr = arr_pattern.match(line)
            if m_arr and ":" not in line[:25]:
                prefix, inner, suffix = m_arr.group(1), m_arr.group(2), m_arr.group(3)
                if '"' in inner and not re.search(r'"\s*,\s*"', inner):
                    inner_clean = re.sub(r'(?<!\\)"', '«', inner)
                    line = f"{prefix}{inner_clean}{suffix}"
                fixed_lines.append(line)
                continue

            fixed_lines.append(line)
        return "\n".join(fixed_lines)

    @classmethod
    def _fix_missing_and_trailing_commas(cls, text: str) -> str:
        """Insert missing commas between JSON lines and remove trailing commas before ] or }."""
        # Remove trailing commas before closing brackets
        text = re.sub(r',(\s*[}\]])', r'\1', text)

        # Insert missing comma when a line ends with a complete value (" / } / ] / true / false / null / digit)
        # and the next line starts with a key or new element (" / { / [)
        text = re.sub(
            r'(["}\]\d]|true|false|null)[ \t]*\n(\s*["{\[])',
            r'\1,\n\2',
            text
        )
        return text

    @classmethod
    def _close_truncated_json(cls, text: str) -> str:
        """
        Safely close a truncated JSON string by tracking string state and bracket stack.
        """
        in_str = False
        esc = False
        stack: List[str] = []
        last_safe_idx = 0

        for i, ch in enumerate(text):
            if in_str:
                if esc:
                    esc = False
                elif ch == '\\':
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == '{':
                    stack.append('}')
                elif ch == '[':
                    stack.append(']')
                elif ch in ('}', ']'):
                    if stack and stack[-1] == ch:
                        stack.pop()
                    last_safe_idx = i + 1
                elif ch == ',':
                    last_safe_idx = i

        if not stack and not in_str:
            return text

        # If cut off mid-string, close the string or rewind to last safe comma/bracket
        repaired = text
        if in_str:
            repaired += '"'

        # Strip any dangling colon or comma at the very end
        repaired = repaired.rstrip()
        while repaired and repaired[-1] in (',', ':'):
            if repaired[-1] == ':':
                repaired += ' ""'
                break
            repaired = repaired[:-1].rstrip()

        # Append remaining closing brackets in reverse order
        repaired += "".join(reversed(stack))
        return repaired

    @classmethod
    def _iterative_repair(cls, text: str) -> Dict[str, Any]:
        """Iteratively repair JSON using Python's JSONDecodeError position feedback."""
        curr = text
        for _ in range(30):
            try:
                return json.loads(curr, strict=False)
            except json.JSONDecodeError as e:
                pos = e.pos
                msg = e.msg

                if "Expecting ',' delimiter" in msg:
                    if pos >= len(curr):
                        curr = cls._close_truncated_json(curr)
                        continue
                    # Check if a comma is missing before pos or an unescaped quote closed the string early
                    before = curr[:pos].rstrip()
                    after = curr[pos:].lstrip()
                    if before.endswith(('"', '}', ']', 'true', 'false', 'null')) and after.startswith(('"', '{', '[')):
                        # Insert missing comma
                        insert_at = len(curr[:pos].rstrip())
                        curr = curr[:insert_at] + "," + curr[insert_at:]
                        continue
                    else:
                        # An unescaped quote just before pos prematurely ended the string!
                        last_quote = curr.rfind('"', 0, pos)
                        if last_quote != -1:
                            curr = curr[:last_quote] + '«' + curr[last_quote + 1:]
                            continue

                elif "Expecting ':' delimiter" in msg:
                    # Usually caused by an unescaped quote inside a string that looked like a key inside an object
                    last_quote = curr.rfind('"', 0, pos)
                    if last_quote != -1:
                        curr = curr[:last_quote] + '«' + curr[last_quote + 1:]
                        continue

                elif "Invalid \\escape" in msg:
                    curr = curr[:pos] + "\\" + curr[pos:]
                    continue

                elif "Unterminated string" in msg or "Expecting value" in msg or "Expecting property name" in msg:
                    curr = re.sub(r',(\s*[}\]])', r'\1', curr)
                    curr = cls._close_truncated_json(curr)
                    try:
                        return json.loads(curr, strict=False)
                    except Exception:
                        break
                break

        return json.loads(curr, strict=False)

    def _parse_json(self, raw_text: str) -> Dict[str, Any]:
        """Strip markdown fences and parse JSON with multi-stage automatic repair."""
        text = raw_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        start_idx = text.find("{")
        if start_idx > 0:
            text = text[start_idx:]

        # Stage 1: Direct parse with strict=False (allows literal control chars)
        try:
            return json.loads(text, strict=False)
        except json.JSONDecodeError:
            pass

        # Stage 2: Line-level inner quote repair + missing/trailing comma fix + truncation closure
        repaired = self._fix_line_inner_quotes(text)
        repaired = self._fix_missing_and_trailing_commas(repaired)
        repaired = self._close_truncated_json(repaired)

        try:
            return json.loads(repaired, strict=False)
        except json.JSONDecodeError:
            pass

        # Stage 3: Iterative position-guided repair
        return self._iterative_repair(repaired)
