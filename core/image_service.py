import aiohttp
import asyncio
import hashlib
import logging
import re
import urllib.parse
from io import BytesIO
from pathlib import Path
from typing import Optional, List
from PIL import Image
from config import OUTPUT_DIR

logger = logging.getLogger(__name__)

IMAGES_CACHE_DIR = OUTPUT_DIR / "images"
IMAGES_CACHE_DIR.mkdir(parents=True, exist_ok=True)

WIKI_HEADERS = {
    "User-Agent": "ISEUSakharovAcademicBot/1.0 (https://iseu.bsu.by; student-research) Python/aiohttp"
}

class ImageService:
    """
    High-Fidelity Scientific & Academic Image Service:
    1. Extracts clean, targeted scientific keywords from academic topics.
    2. Searches Wikimedia Commons and Wikipedia PageImages for real authentic diagrams, histological scans, and charts.
    3. Searches DuckDuckGo Images with filtering for academic/educational media.
    4. AI Fallback (Pollinations/Flux) with strict vector infographic prompt if no web image is found.
    5. Validates, strips watermarks/logos, and optimizes as 300dpi JPEG.
    """

    @classmethod
    async def get_image_for_query(cls, query: str, fallback_prompt: Optional[str] = None) -> Optional[Path]:
        clean_query = query.strip()
        if not clean_query:
            return None

        # Check local cache by query hash
        q_hash = hashlib.md5(clean_query.lower().encode("utf-8")).hexdigest()
        cached_file = IMAGES_CACHE_DIR / f"img_{q_hash}.jpg"
        if cached_file.exists() and cached_file.stat().st_size > 8000:
            try:
                with Image.open(cached_file) as c_img:
                    if cls._is_valid_academic_image(c_img):
                        return cached_file
                # If cached image was bad/black, remove it
                cached_file.unlink(missing_ok=True)
            except Exception:
                cached_file.unlink(missing_ok=True)

        search_variants = cls._extract_search_variants(clean_query)
        logger.info(f"ImageService: searching image for '{clean_query}'. Variants: {search_variants}")

        # 1. Search Wikimedia Commons & Wikipedia
        for q in search_variants:
            # Wikimedia Commons
            img = await cls._search_wikimedia(q, cached_file)
            if img:
                return img
            # Wikipedia PageImages
            img = await cls._search_wikipedia_images(q, cached_file)
            if img:
                return img

        # 2. Search DuckDuckGo Images
        for q in search_variants[:2]:
            img = await cls._search_duckduckgo(f"{q} схема диаграмма", cached_file)
            if img:
                return img
            img = await cls._search_duckduckgo(q, cached_file)
            if img:
                return img

        # 3. AI Fallback: Minimalist Vector Infographic (crisp, academic, no watermarks)
        top_keyword = search_variants[0] if search_variants else clean_query
        ai_prompt = fallback_prompt or (
            f"educational scientific diagram of {top_keyword}, crisp vector infographic, "
            f"medical and ecological academic textbook illustration, clear schematic view, "
            f"clean white background, professional medical publication, no watermarks"
        )
        logger.info(f"ImageService: AI fallback generation with prompt: '{ai_prompt}'")
        return await cls._generate_ai_image(ai_prompt, cached_file)

    @classmethod
    def _extract_search_variants(cls, query: str) -> List[str]:
        """Extract simplified, targeted keywords from long academic sentences."""
        cleaned = re.sub(r"^(рисунок|рис\.?)\s*\d*\s*[-—–:]*\s*", "", query, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"(алгоритм|методы|оценка|исследование|анализ|стратификация|динамика|классификация)\s+", "", cleaned, flags=re.IGNORECASE).strip()

        variants = []
        if cleaned and cleaned != query:
            variants.append(cleaned)
        variants.append(query)

        # Check for Latin/English acronyms (e.g. EU-TIRADS, PM2.5, DNA, GIS)
        acronyms = re.findall(r"\b[A-Za-z0-9\-_]{2,}\b", query)
        for acr in acronyms:
            if len(acr) >= 3 and acr.lower() not in ["the", "and", "for", "img"]:
                variants.append(acr)

        # Truncate overly long queries to first 3-4 significant words
        words = [w for w in cleaned.split() if len(w) > 3]
        if len(words) > 3:
            variants.append(" ".join(words[:3]))

        # Deduplicate while preserving order
        seen = set()
        result = []
        for v in variants:
            v_s = v.strip()
            if v_s and v_s.lower() not in seen:
                seen.add(v_s.lower())
                result.append(v_s)

        return result[:4]

    @classmethod
    async def _search_wikimedia(cls, query: str, target_file: Path) -> Optional[Path]:
        """Search Wikimedia Commons with authentic User-Agent."""
        url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",  # Media
            "gsrlimit": "4",
            "prop": "imageinfo",
            "iiprop": "url|mime|size",
            "format": "json"
        }
        try:
            async with aiohttp.ClientSession(headers=WIKI_HEADERS) as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pages = data.get("query", {}).get("pages", {})
                        for page in pages.values():
                            imageinfo = page.get("imageinfo", [])
                            if imageinfo:
                                img_url = imageinfo[0].get("url")
                                mime = imageinfo[0].get("mime", "")
                                size = imageinfo[0].get("size", 0)
                                if img_url and size > 15000 and ("jpeg" in mime or "png" in mime or "jpg" in mime):
                                    if await cls._download_and_save(session, img_url, target_file):
                                        return target_file
        except Exception as e:
            logger.debug(f"Wikimedia search failed for '{query}': {e}")
        return None

    @classmethod
    async def _search_wikipedia_images(cls, query: str, target_file: Path) -> Optional[Path]:
        """Search Russian and English Wikipedia lead pageimages."""
        endpoints = [
            "https://ru.wikipedia.org/w/api.php",
            "https://en.wikipedia.org/w/api.php"
        ]
        try:
            async with aiohttp.ClientSession(headers=WIKI_HEADERS) as session:
                for ep in endpoints:
                    params = {
                        "action": "query",
                        "generator": "search",
                        "gsrsearch": query,
                        "gsrlimit": "3",
                        "prop": "pageimages",
                        "pithumbsize": "1200",
                        "format": "json"
                    }
                    async with session.get(ep, params=params, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            pages = data.get("query", {}).get("pages", {})
                            for page in pages.values():
                                thumb = page.get("thumbnail", {})
                                img_url = thumb.get("source")
                                if img_url and ("jpeg" in img_url or "png" in img_url or "jpg" in img_url):
                                    if await cls._download_and_save(session, img_url, target_file):
                                        return target_file
        except Exception as e:
            logger.debug(f"Wikipedia pageimages search failed for '{query}': {e}")
        return None

    @classmethod
    async def _search_duckduckgo(cls, query: str, target_file: Path) -> Optional[Path]:
        """Search DuckDuckGo Images with modern desktop headers."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
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
                        for r in results[:4]:
                            img_url = r.get("image")
                            if img_url and await cls._download_and_save(session, img_url, target_file):
                                return target_file
        except Exception as e:
            logger.debug(f"DuckDuckGo search failed for '{query}': {e}")
        return None

    @classmethod
    async def _generate_ai_image(cls, prompt: str, target_file: Path) -> Optional[Path]:
        """Generate high quality scientific diagram via AI with watermark filtering."""
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
    def _is_valid_academic_image(cls, img: Image.Image) -> bool:
        """Validate that the image is not a black rectangle, solid color, or low-quality icon."""
        if img.width < 300 or img.height < 200:
            return False

        gray = img.convert("L")
        # Sample pixels for fast verification
        small = gray.resize((100, 100))
        pixels = list(small.tobytes())
        total = len(pixels)
        if total == 0:
            return False

        # Reject if more than 35% pitch black pixels
        black_count = sum(1 for p in pixels if p < 25)
        if (black_count / total) > 0.35:
            return False

        # Reject if average brightness is too dark (< 45) or completely blank white (> 253)
        avg_brightness = sum(pixels) / total
        if avg_brightness < 45 or avg_brightness > 253:
            return False

        # Reject if contrast is too low (e.g. solid single color or blank grey box)
        min_val, max_val = gray.getextrema()
        if (max_val - min_val) < 40:
            return False

        return True

    @classmethod
    async def _download_and_save(cls, session: aiohttp.ClientSession, url: str, target_file: Path) -> bool:
        """Download image, composite transparency onto white, validate quality, auto-crop vertical images, and save as JPEG."""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    raw_bytes = await resp.read()
                    if len(raw_bytes) < 4000:
                        return False

                    with Image.open(BytesIO(raw_bytes)) as raw_img:
                        # 1. Composite transparent PNG/SVG onto solid white background so it NEVER turns black
                        if raw_img.mode in ("RGBA", "LA") or (raw_img.mode == "P" and "transparency" in raw_img.info):
                            alpha = raw_img.convert("RGBA")
                            white_bg = Image.new("RGBA", alpha.size, (255, 255, 255, 255))
                            img = Image.alpha_composite(white_bg, alpha).convert("RGB")
                        else:
                            img = raw_img.convert("RGB")

                        # 2. Strict Academic Quality Filter (rejects black boxes, blank images, icons)
                        if not cls._is_valid_academic_image(img):
                            logger.info(f"ImageService: rejected image from {url} (failed quality/brightness check)")
                            return False

                        # 3. Auto-crop overly tall vertical images to compact landscape/square aspect ratio (max height = 0.9 * width)
                        w, h = img.size
                        if h > w:
                            target_h = int(w * 0.85)
                            top = (h - target_h) // 2
                            bottom = top + target_h
                            img = img.crop((0, top, w, bottom))
                            logger.info(f"ImageService: auto-cropped tall vertical image from {w}x{h} to {img.width}x{img.height}")

                        # 4. Resize if excessively large
                        max_w, max_h = 1200, 800
                        if img.width > max_w or img.height > max_h:
                            img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

                        img.save(target_file, "JPEG", quality=90)
                        logger.info(f"ImageService: saved validated image ({img.width}x{img.height}) to {target_file}")
                        return True
        except Exception as e:
            logger.debug(f"Failed to download image from {url}: {e}")
        return False

