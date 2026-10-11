import aiohttp
import asyncio
import hashlib
import logging
import urllib.parse
from io import BytesIO
from pathlib import Path
from typing import Optional
from PIL import Image
from config import OUTPUT_DIR

logger = logging.getLogger(__name__)

IMAGES_CACHE_DIR = OUTPUT_DIR / "images"
IMAGES_CACHE_DIR.mkdir(parents=True, exist_ok=True)

class ImageService:
    """
    Hybrid Image Service:
    1. Searches Wikimedia Commons and web for real ecological, scientific, and educational images.
    2. If not found or unsuitable, automatically falls back to AI image generation (Pollinations/Flux).
    3. Validates and caches images locally as high-resolution JPEGs.
    """

    @classmethod
    async def get_image_for_query(cls, query: str, fallback_prompt: Optional[str] = None) -> Optional[Path]:
        clean_query = query.strip()
        if not clean_query:
            return None

        # Check local cache by query hash
        q_hash = hashlib.md5(clean_query.lower().encode("utf-8")).hexdigest()
        cached_file = IMAGES_CACHE_DIR / f"img_{q_hash}.jpg"
        if cached_file.exists() and cached_file.stat().st_size > 5000:
            return cached_file

        logger.info(f"ImageService: searching image for query '{clean_query}'...")

        # 1. Try Wikimedia Commons (scientific / real photos and diagrams)
        image_path = await cls._search_wikimedia(clean_query, cached_file)
        if image_path:
            return image_path

        # 2. Try DuckDuckGo image search
        image_path = await cls._search_duckduckgo(clean_query, cached_file)
        if image_path:
            return image_path

        # 3. Fallback: AI Generation (Pollinations / Flux)
        prompt_to_use = fallback_prompt or f"Scientific detailed diagram or photo of {clean_query}, high quality, academic, realistic"
        logger.info(f"ImageService: falling back to AI generation for prompt '{prompt_to_use}'...")
        image_path = await cls._generate_ai_image(prompt_to_use, cached_file)
        return image_path

    @classmethod
    async def _search_wikimedia(cls, query: str, target_file: Path) -> Optional[Path]:
        """Search Wikimedia Commons for free scientific/ecological media."""
        url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",  # Media namespace
            "gsrlimit": "4",
            "prop": "imageinfo",
            "iiprop": "url|mime|size",
            "format": "json"
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pages = data.get("query", {}).get("pages", {})
                        for page in pages.values():
                            imageinfo = page.get("imageinfo", [])
                            if imageinfo:
                                img_url = imageinfo[0].get("url")
                                mime = imageinfo[0].get("mime", "")
                                if img_url and ("jpeg" in mime or "png" in mime or "jpg" in mime):
                                    if await cls._download_and_save(session, img_url, target_file):
                                        return target_file
        except Exception as e:
            logger.debug(f"Wikimedia search failed for '{query}': {e}")
        return None

    @classmethod
    async def _search_duckduckgo(cls, query: str, target_file: Path) -> Optional[Path]:
        """Search DuckDuckGo Images."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        token_url = "https://duckduckgo.com/"
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(token_url, params={"q": query}, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    text = await resp.text()
                    vqd = None
                    if "vqd='" in text:
                        vqd = text.split("vqd='")[1].split("'")[0]
                    elif 'vqd="' in text:
                        vqd = text.split('vqd="')[1].split('"')[0]

                    if not vqd:
                        return None

                params = {
                    "l": "wt-wt",
                    "o": "json",
                    "q": query,
                    "vqd": vqd,
                    "f": ",,,",
                    "p": "1"
                }
                async with session.get("https://duckduckgo.com/i.js", params=params, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("results", [])
                        for r in results[:3]:
                            img_url = r.get("image")
                            if img_url and await cls._download_and_save(session, img_url, target_file):
                                return target_file
        except Exception as e:
            logger.debug(f"DuckDuckGo search failed for '{query}': {e}")
        return None

    @classmethod
    async def _generate_ai_image(cls, prompt: str, target_file: Path) -> Optional[Path]:
        """Generate scientific/ecological image via AI."""
        encoded_prompt = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=640&nologo=true&seed=42"
        try:
            async with aiohttp.ClientSession() as session:
                if await cls._download_and_save(session, url, target_file):
                    return target_file
        except Exception as e:
            logger.warning(f"AI image generation failed for '{prompt}': {e}")
        return None

    @classmethod
    async def _download_and_save(cls, session: aiohttp.ClientSession, url: str, target_file: Path) -> bool:
        """Download image, validate via Pillow, and save as JPEG."""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    raw_bytes = await resp.read()
                    if len(raw_bytes) < 3000:
                        return False
                    
                    # Validate image with Pillow
                    with Image.open(BytesIO(raw_bytes)) as img:
                        img = img.convert("RGB")
                        # Resize if too large
                        max_dimension = 1400
                        if img.width > max_dimension or img.height > max_dimension:
                            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
                        img.save(target_file, "JPEG", quality=88)
                        logger.info(f"Saved valid image to {target_file}")
                        return True
        except Exception as e:
            logger.debug(f"Failed to download/save image from {url}: {e}")
        return False
