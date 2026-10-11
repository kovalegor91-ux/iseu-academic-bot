import os
import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    FSInputFile
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config import (
    TELEGRAM_BOT_TOKEN,
    GEMINI_API_KEY,
    WEBAPP_URL,
    OUTPUT_DIR,
    SAKHAROV_STANDARDS
)
from core.gemini_client import GeminiClient
from core.prompts import (
    ACADEMIC_HUMAN_SYSTEM_INSTRUCTION,
    build_doc_generation_prompt,
    build_presentation_prompt,
    build_revision_prompt
)
from core.reference_parser import ReferenceParser
from core.image_service import ImageService
from core.docx_generator import DocxGenerator
from core.pptx_generator import PptxGenerator
from core.session_manager import SessionManager, UserSession
import webapp_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

dp = Dispatcher()
gemini = GeminiClient()

def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Build persistent bottom menu keyboard."""
    buttons = [
        [KeyboardButton(text="⚙️ Конструктор работы", web_app=WebAppInfo(url=WEBAPP_URL))] if WEBAPP_URL.startswith("https") else [KeyboardButton(text="📝 Создать работу в чате")],
        [KeyboardButton(text="📋 Стандарты МГЭИ"), KeyboardButton(text="💡 Помощь и образцы")],
        [KeyboardButton(text="🔄 Сбросить сессию")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_actions_inline_keyboard(has_doc: bool, has_pres: bool) -> InlineKeyboardMarkup:
    """Inline keyboard attached to generated files for instant edits and conversions."""
    inline_buttons = []
    first_row = []
    if has_doc and not has_pres:
        first_row.append(InlineKeyboardButton(text="📊 Сделать презентацию", callback_data="convert_to_pres"))
    elif has_pres and not has_doc:
        first_row.append(InlineKeyboardButton(text="📄 Сделать реферат", callback_data="convert_to_doc"))
    
    first_row.append(InlineKeyboardButton(text="🎤 Текст доклада", callback_data="get_speech"))
    if first_row:
        inline_buttons.append(first_row)

    inline_buttons.append([
        InlineKeyboardButton(text="✏️ Внести правки (напишите в чат)", callback_data="hint_edit"),
        InlineKeyboardButton(text="🔄 Перегенерировать", callback_data="regenerate")
    ])
    return InlineKeyboardMarkup(inline_keyboard=inline_buttons)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    session = SessionManager.get_session(user_id)

    text = (
        "👋 **Добро пожаловать в академический бот МГЭИ им. А.Д. Сахарова БГУ!**\n\n"
        "Я создаю **рефераты, доклады и презентации** сразу в готовых форматах `.docx` и `.pptx`, "
        "строго по стандартам института и ГОСТам Беларуси.\n\n"
        "🔥 **Ключевые возможности:**\n"
        "• 📄 **Стандарты МГЭИ Сахарова**: титульный лист, поля 30/10/20/20 мм, шрифт Times New Roman 14 pt, 1.5 интервал, ссылки на источники [1].\n"
        "• 📊 **Презентации 16:9**: фирменный стиль, карточки, подбор картинок и **заметки докладчика к каждому слайду**!\n"
        "• 🛡️ **Человеческий стиль (Anti-AI)**: защита от детекторов ИИ, белорусская нормативная база, отсутствие клише.\n"
        "• 🖼️ **Иллюстрации**: поиск реальных схем и фото в сети + AI генерация с подписями по ГОСТ («Рисунок 1 — ...»).\n"
        "• 📁 **Клонирование стиля**: отправьте мне любой готовый файл `.docx` или `.pptx` — и я сделаю новую работу по его подобию!\n"
        "• ✏️ **Правки на лету**: после получения файла просто напишите, что изменить, и я пришлю обновленную версию.\n\n"
        "👉 Чтобы начать, нажмите кнопку **«Конструктор работы»** или просто напишите тему реферата в чат!"
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard(user_id))

@dp.message(Command("standards"))
@dp.message(F.text == "📋 Стандарты МГЭИ")
async def cmd_standards(message: types.Message):
    text = (
        "🏛️ **Стандарты оформления студенческих работ МГЭИ им. А.Д. Сахарова БГУ:**\n\n"
        "**1. Параметры страницы и текст:**\n"
        "• Формат: А4, ориентация книжная\n"
        "• Поля: левое — 30 мм, правое — 10 мм, верхнее — 20 мм, нижнее — 20 мм\n"
        "• Шрифт: Times New Roman, 14 pt (таблицы и подписи к рисункам — 12 pt)\n"
        "• Межстрочный интервал: 1.5, абзацный отступ (красная строка): 1.25 см\n"
        "• Выравнивание: по ширине, автоматическая расстановка номеров страниц\n\n"
        "**2. Структура работы:**\n"
        "• Титульный лист (БГУ / МГЭИ им. А.Д. Сахарова / Кафедра / Автор / Руководитель / Минск, 2026)\n"
        "• Содержание\n"
        "• Введение (актуальность, цель, задачи, объект, предмет, методы)\n"
        "• Основная часть (разделы, подразделы, иллюстрации по ГОСТ)\n"
        "• Заключение (выводы по задачам)\n"
        "• Список использованных источников (по ГОСТ 7.1-2003 / ВАК Беларуси)\n\n"
        "**3. Иллюстрации:**\n"
        "• Выравнивание по центру, подпись снизу: `Рисунок 1 — Название рисунка`\n\n"
        "**4. Презентации:**\n"
        "• Формат: 16:9 widescreen, заметки к каждому слайду для выступления."
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("help"))
@dp.message(F.text == "💡 Помощь и образцы")
async def cmd_help(message: types.Message):
    text = (
        "💡 **Как пользоваться ботом:**\n\n"
        "**1. Быстрое создание работы:**\n"
        "Просто отправьте тему в чат, например:\n"
        "`Реферат: Радиационный мониторинг в зоне отчуждения Чернобыльской АЭС`\n"
        "или воспользуйтесь кнопкой «Конструктор работы».\n\n"
        "**2. Загрузка эталонного образца (клонирование стиля):**\n"
        "Пришлите боту файл `.docx` или `.pptx` (например, методичку или прошлый реферат). Бот считает структуру, стили и шрифты, и будет генерировать новые работы по этому образцу!\n\n"
        "**3. Внесение правок:**\n"
        "Получили файл? Напишите любую правку обычным текстом, например:\n"
        "• *«Добавь в заключение больше информации по Беларуси»*\n"
        "• *«Замени картинку во второй главе на график»*\n"
        "• *«Сократи текст презентации до 6 слайдов»*\n"
        "Бот мгновенно перегенерирует и пришлет обновленный файл!\n\n"
        "**4. Команды:**\n"
        "• `/start` — главное меню\n"
        "• `/standards` — стандарты оформления\n"
        "• `/clear` — сбросить активную работу"
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("clear"))
@dp.message(F.text == "🔄 Сбросить сессию")
async def cmd_clear(message: types.Message):
    user_id = message.from_user.id
    SessionManager.clear_session(user_id)
    await message.answer("🧹 Сессия очищена. Вы можете начать создание новой работы!", reply_markup=get_main_keyboard(user_id))

@dp.message(F.document)
async def handle_document(message: types.Message, bot: Bot):
    """Handle uploaded reference document (.docx or .pptx) for style cloning."""
    doc = message.document
    fname = doc.file_name.lower()
    if not (fname.endswith(".docx") or fname.endswith(".pptx")):
        await message.answer("⚠️ Пожалуйста, отправьте файл в формате `.docx` или `.pptx`.")
        return

    user_id = message.from_user.id
    status_msg = await message.answer("⏳ Анализирую присланный файл-образец...")

    try:
        temp_dir = OUTPUT_DIR / "uploads"
        temp_dir.mkdir(parents=True, exist_ok=True)
        local_path = temp_dir / f"ref_{user_id}_{doc.file_name}"
        
        file_info = await bot.get_file(doc.file_id)
        await bot.download_file(file_info.file_path, local_path)

        ref_data = ReferenceParser.parse_file(local_path)
        session = SessionManager.get_session(user_id)
        session.reference_data = ref_data
        SessionManager.save_session(user_id)

        doc_type_str = "DOCX документ" if ref_data["type"] == "docx" else "PPTX презентация"
        headings_cnt = len(ref_data.get("headings", [])) or ref_data.get("slide_count", 0)

        response_text = (
            f"✅ **Эталонный образец успешно загружен и проанализирован!**\n\n"
            f"• Формат: **{doc_type_str}**\n"
            f"• Файл: `{doc.file_name}`\n"
            f"• Обнаружено разделов/слайдов: **{headings_cnt}**\n"
            f"• Шрифт: **{ref_data.get('font_name', 'Times New Roman')}**\n\n"
            f"🎯 **Теперь все новые рефераты и презентации будут создаваться по подобию этого образца!**\n\n"
            f"Напишите тему работы в чат или откройте «Конструктор работы»:"
        )
        await status_msg.edit_text(response_text, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Error parsing uploaded document: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Ошибка при чтении файла: {e}")

@dp.message(F.web_app_data)
async def handle_webapp_data(message: types.Message, bot: Bot):
    """Handle generation request coming from the Telegram WebApp."""
    raw_json = message.web_app_data.data
    try:
        data = json.loads(raw_json)
        await process_generation_request(message, bot, data)
    except Exception as e:
        logger.error(f"Error handling WebApp data: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка обработки данных из WebApp: {e}")

@dp.message(F.text == "📝 Создать работу в чате")
async def cmd_new_chat(message: types.Message):
    await message.answer(
        "📝 **Создание работы прямо в чате:**\n\n"
        "Напишите тему вашей работы следующим сообщением.\n\n"
        "Примеры:\n"
        "• `Реферат: Методы оценки радиационной обстановки в Беларуси`\n"
        "• `Презентация: Ветроэнергетический потенциал Минской области`\n"
        "• `Доклад: Современные подходы к утилизации медицинских отходов`"
    )

@dp.message(F.text)
async def handle_text_message(message: types.Message, bot: Bot):
    """
    Handle plain text:
    1. If user has an active work, treat text as an iterative revision/edit request!
    2. Otherwise, treat text as a topic for a new paper/presentation.
    """
    user_id = message.from_user.id
    session = SessionManager.get_session(user_id)
    text = message.text.strip()

    # Check if active work exists and user is asking for revision
    has_active_work = bool(session.current_doc_data or session.current_pres_data)

    # Keywords indicating a new topic vs revision
    is_explicit_new = any(text.lower().startswith(prefix) for prefix in ["реферат:", "доклад:", "презентация:", "тема:", "/new"])

    if has_active_work and not is_explicit_new:
        # ITERATIVE REVISION MODE
        await process_revision_request(message, bot, session, text)
    else:
        # NEW WORK GENERATION MODE
        clean_topic = text
        for p in ["реферат:", "доклад:", "презентация:", "тема:", "/new "]:
            if clean_topic.lower().startswith(p):
                clean_topic = clean_topic[len(p):].strip()

        mode = "doc"
        if "презентаци" in text.lower():
            mode = "pres"

        data = {
            "work_type": mode,
            "topic": clean_topic,
            "discipline": "Экологический мониторинг",
            "faculty": session.params.get("faculty", "Факультет мониторинга окружающей среды"),
            "department": session.params.get("department", "Кафедра экологического мониторинга"),
            "student_name": session.params.get("student_name", "Иванов И.И."),
            "student_course": session.params.get("student_course", "3"),
            "student_group": session.params.get("student_group", "301"),
            "supervisor": session.params.get("supervisor", "доцент, к.б.н. Петров П.П."),
            "page_count": 15,
            "slide_count": 8,
            "include_images": True,
            "anti_ai_style": True,
            "generate_speech": True
        }
        await process_generation_request(message, bot, data)

async def progress_reporter(bot: Bot, chat_id: int, message_id: int, stop_event: asyncio.Event, topic: str):
    """Asynchronously animates live generation progress bar in Telegram."""
    stages = [
        ("▰▱▱▱▱▱▱▱▱▱", "10%", "Инициализирую стандарты МГЭИ им. А.Д. Сахарова..."),
        ("▰▰▱▱▱▱▱▱▱▱", "25%", "Проектирую структуру и введение (цель, задачи)..."),
        ("▰▰▰▱▱▱▱▱▱▱", "40%", "Пишу теоретическую часть в стиле Anti-AI..."),
        ("▰▰▰▰▱▱▱▱▱▱", "55%", "Анализирую практическую часть и нормативную базу РБ..."),
        ("▰▰▰▰▰▱▱▱▱▱", "70%", "Формулирую выводы и библиографию по ГОСТ..."),
        ("▰▰▰▰▰▰▱▱▱▱", "80%", "Подбираю научные иллюстрации и схемы..."),
        ("▰▰▰▰▰▰▰▱▱▱", "90%", "Верстаю официальный титульный лист и документ..."),
    ]
    idx = 0
    while not stop_event.is_set():
        bar, pct, desc = stages[idx % len(stages)]
        try:
            await bot.send_chat_action(chat_id, action="upload_document")
            text = (
                f"⚙️ **Генерация работы по стандартам МГЭИ им. А.Д. Сахарова:**\n\n"
                f"📌 **Тема:** «{topic[:80]}»\n\n"
                f"[{bar}] **{pct}**\n"
                f"🔄 {desc}"
            )
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

        if idx < len(stages) - 1:
            idx += 1

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=3.5)
        except asyncio.TimeoutError:
            pass

async def process_generation_request(message: types.Message, bot: Bot, params: Dict[str, Any]):
    """Execute end-to-end generation of DOCX and/or PPTX with live visual progress."""
    user_id = message.from_user.id
    session = SessionManager.get_session(user_id)

    topic = params.get("topic", "Экологические исследования")
    work_type = params.get("work_type", "doc")
    include_images = params.get("include_images", True)

    status_msg = await message.answer(
        f"⏳ **Генерация работы по стандартам МГЭИ им. А.Д. Сахарова:**\n\n"
        f"📌 **Тема:** «{topic[:80]}»\n\n"
        f"[▰▱▱▱▱▱▱▱▱▱] **10%**\n"
        f"⚙️ Запускаю академическую генерацию...",
        parse_mode=ParseMode.MARKDOWN
    )

    stop_event = asyncio.Event()
    progress_task = asyncio.create_task(
        progress_reporter(bot, message.chat.id, status_msg.message_id, stop_event, topic)
    )

    try:
        doc_data = None
        pres_data = None
        image_map = {}

        # 1. Generate DOCX data if requested
        if work_type in ["doc", "speech", "bundle"]:
            prompt = build_doc_generation_prompt(
                topic=topic,
                discipline=params.get("discipline", "Экологический мониторинг"),
                work_type="РЕФЕРАТ" if work_type != "speech" else "ДОКЛАД",
                faculty=params.get("faculty", "Факультет мониторинга окружающей среды"),
                department=params.get("department", "Кафедра экологического мониторинга"),
                student_name=params.get("student_name", "Иванов И.И."),
                student_course=str(params.get("student_course", "3")),
                student_group=params.get("student_group", "301"),
                supervisor=params.get("supervisor", "доцент, к.б.н. Петров П.П."),
                page_count=params.get("page_count", 15),
                include_images=include_images,
                reference_data=session.reference_data
            )
            doc_data = await gemini.generate_json(
                prompt=prompt,
                system_instruction=ACADEMIC_HUMAN_SYSTEM_INSTRUCTION
            )
            session.current_doc_data = doc_data

        # 2. Generate PPTX data if requested
        if work_type in ["pres", "bundle"]:
            pres_prompt = build_presentation_prompt(
                topic=topic,
                discipline=params.get("discipline", "Экологический мониторинг"),
                faculty=params.get("faculty", "Факультет мониторинга окружающей среды"),
                student_name=params.get("student_name", "Иванов И.И."),
                supervisor=params.get("supervisor", "доцент, к.б.н. Петров П.П."),
                slide_count=params.get("slide_count", 8),
                include_images=include_images,
                doc_context=doc_data,
                reference_data=session.reference_data
            )
            pres_data = await gemini.generate_json(
                prompt=pres_prompt,
                system_instruction=ACADEMIC_HUMAN_SYSTEM_INSTRUCTION
            )
            session.current_pres_data = pres_data

        # 3. Collect Image Queries & Fetch/Generate Images
        if include_images:
            queries = set()
            if doc_data:
                for sec in doc_data.get("sections", []):
                    for sub in sec.get("subsections", []):
                        if sub.get("image_needed") and sub.get("image_query"):
                            queries.add(sub["image_query"])
            if pres_data:
                for slide in pres_data.get("slides", []):
                    if slide.get("image_query"):
                        queries.add(slide["image_query"])

            for q in list(queries)[:4]:  # Fetch up to 4 images
                img_path = await ImageService.get_image_for_query(q)
                if img_path:
                    image_map[q] = img_path
                    session.current_image_map[q] = str(img_path)

        # 4. Final Document Building
        docx_path = None
        pptx_path = None

        if doc_data:
            docx_path = await DocxGenerator.generate_document(doc_data, image_map)
            session.current_docx_path = str(docx_path)

        if pres_data:
            pptx_path = await PptxGenerator.generate_presentation(pres_data, image_map)
            session.current_pptx_path = str(pptx_path)

        session.last_mode = work_type
        session.revision_count = 1
        SessionManager.save_session(user_id)

        # Stop progress animation and show 100%
        stop_event.set()
        await progress_task

        try:
            await status_msg.edit_text(
                f"✅ **Генерация успешно завершена!**\n\n"
                f"📌 Тема: «{topic}»\n"
                f"[▰▰▰▰▰▰▰▰▰▰] **100%**\n"
                f"🚀 Отправляю готовые файлы в чат...",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

        # Send Files to Telegram
        keyboard = get_actions_inline_keyboard(has_doc=bool(docx_path), has_pres=bool(pptx_path))

        if docx_path and docx_path.exists():
            caption = (
                f"📄 **{doc_data.get('work_type', 'Реферат')} готов к сдаче!**\n"
                f"• Тема: «{doc_data.get('topic')}»\n"
                f"• Стандарт: МГЭИ им. А.Д. Сахарова БГУ\n"
                f"• Шрифт: Times New Roman 14 pt, 1.5 интервал\n"
                f"• Оформление: ГОСТ 7.32 / ГОСТ 7.1-2003\n\n"
                f"💬 *Вы можете написать в ответ любое сообщение, чтобы я внес правку (например: «добавь расчеты во 2 главу»)!*"
            )
            await message.answer_document(
                FSInputFile(docx_path),
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard if not pptx_path else None
            )

        if pptx_path and pptx_path.exists():
            caption = (
                f"📊 **Презентация готова к выступлению!**\n"
                f"• Формат: 16:9 Widescreen\n"
                f"• Слайдов: {len(pres_data.get('slides', []))}\n"
                f"• В каждый слайд встроены **заметки докладчика** для речи!\n\n"
                f"💬 *Напишите правку в чат, если хотите что-то изменить!*"
            )
            await message.answer_document(
                FSInputFile(pptx_path),
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )

    except Exception as e:
        stop_event.set()
        logger.error(f"Generation error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Произошла ошибка при генерации: {e}\n\nПопробуйте повторить или проверьте ключ API.")

async def process_revision_request(message: types.Message, bot: Bot, session: UserSession, instruction: str):
    """Iteratively revise current DOCX or PPTX according to student instructions."""
    user_id = message.from_user.id
    status_msg = await message.answer(f"⏳ **Вношу правки в работу:**\n«{instruction}»\n\nОбновляю документ...")

    try:
        session.revision_count += 1
        rev_num = session.revision_count
        image_map = {q: Path(p) for q, p in session.current_image_map.items()}

        # Revise DOCX if present
        if session.current_doc_data:
            rev_prompt = build_revision_prompt(session.current_doc_data, instruction, is_presentation=False)
            updated_doc_data = await gemini.generate_json(
                prompt=rev_prompt,
                system_instruction=ACADEMIC_HUMAN_SYSTEM_INSTRUCTION
            )
            session.current_doc_data = updated_doc_data
            fname = f"Sakharov_v{rev_num}_{updated_doc_data.get('work_type', 'Реферат')}.docx"
            new_docx = await DocxGenerator.generate_document(updated_doc_data, image_map, output_filename=fname)
            session.current_docx_path = str(new_docx)

            await message.answer_document(
                FSInputFile(new_docx),
                caption=f"✅ **Реферат обновлен (Версия {rev_num})** по вашей правке:\n«{instruction}»",
                reply_markup=get_actions_inline_keyboard(has_doc=True, has_pres=bool(session.current_pres_data))
            )

        # Revise PPTX if present
        if session.current_pres_data:
            rev_pres_prompt = build_revision_prompt(session.current_pres_data, instruction, is_presentation=True)
            updated_pres_data = await gemini.generate_json(
                prompt=rev_pres_prompt,
                system_instruction=ACADEMIC_HUMAN_SYSTEM_INSTRUCTION
            )
            session.current_pres_data = updated_pres_data
            fname = f"Sakharov_v{rev_num}_Презентация.pptx"
            new_pptx = await PptxGenerator.generate_presentation(updated_pres_data, image_map, output_filename=fname)
            session.current_pptx_path = str(new_pptx)

            await message.answer_document(
                FSInputFile(new_pptx),
                caption=f"✅ **Презентация обновлена (Версия {rev_num})** по вашей правке:\n«{instruction}»",
                reply_markup=get_actions_inline_keyboard(has_doc=bool(session.current_doc_data), has_pres=True)
            )

        SessionManager.save_session(user_id)
        await status_msg.delete()

    except Exception as e:
        logger.error(f"Revision error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Ошибка при внесении правок: {e}")

@dp.callback_query(F.data == "convert_to_pres")
async def cb_convert_to_pres(call: types.CallbackQuery, bot: Bot):
    """Convert existing DOCX to PPTX."""
    user_id = call.from_user.id
    session = SessionManager.get_session(user_id)
    if not session.current_doc_data:
        await call.answer("Нет активного реферата для создания презентации.", show_alert=True)
        return

    await call.answer("Генерирую презентацию на основе вашего реферата...")
    data = {
        "work_type": "pres",
        "topic": session.current_doc_data.get("topic", "Исследование"),
        "discipline": session.current_doc_data.get("discipline", "Экология"),
        "faculty": session.current_doc_data.get("faculty", "Факультет мониторинга окружающей среды"),
        "student_name": session.current_doc_data.get("student", {}).get("name", "Иванов И.И."),
        "supervisor": session.current_doc_data.get("supervisor", "доцент Петров П.П."),
        "slide_count": 8,
        "include_images": True
    }
    await process_generation_request(call.message, bot, data)

@dp.callback_query(F.data == "convert_to_doc")
async def cb_convert_to_doc(call: types.CallbackQuery, bot: Bot):
    """Convert existing PPTX to DOCX."""
    user_id = call.from_user.id
    session = SessionManager.get_session(user_id)
    if not session.current_pres_data:
        await call.answer("Нет активной презентации для создания реферата.", show_alert=True)
        return

    await call.answer("Генерирую полный реферат на основе вашей презентации...")
    data = {
        "work_type": "doc",
        "topic": session.current_pres_data.get("topic", "Исследование"),
        "discipline": "Экология",
        "page_count": 15,
        "include_images": True
    }
    await process_generation_request(call.message, bot, data)

@dp.callback_query(F.data == "get_speech")
async def cb_get_speech(call: types.CallbackQuery):
    """Send text of speech notes for the defense."""
    user_id = call.from_user.id
    session = SessionManager.get_session(user_id)
    speech = ""
    if session.current_doc_data and session.current_doc_data.get("speech_text"):
        speech = session.current_doc_data["speech_text"]
    elif session.current_pres_data:
        slides = session.current_pres_data.get("slides", [])
        notes_list = [f"**Слайд {s.get('slide_number', i+1)} ({s.get('title', '')}):**\n{s.get('speech_notes', '')}" for i, s in enumerate(slides) if s.get('speech_notes')]
        speech = "\n\n".join(notes_list)

    if not speech:
        await call.answer("Речь для выступления еще не сгенерирована.", show_alert=True)
        return

    await call.answer()
    # Send in chunks if long
    if len(speech) > 4000:
        for chunk in [speech[i:i+4000] for i in range(0, len(speech), 4000)]:
            await call.message.answer(f"🎤 **Речь для защиты:**\n\n{chunk}", parse_mode=ParseMode.MARKDOWN)
    else:
        await call.message.answer(f"🎤 **Речь для защиты (доклад на 4-6 минут):**\n\n{speech}", parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(F.data == "hint_edit")
async def cb_hint_edit(call: types.CallbackQuery):
    await call.answer()
    await call.message.answer(
        "✏️ **Как внести правку:**\n\n"
        "Просто отправьте в чат текстовое сообщение с вашими пожеланиями, например:\n"
        "• *«Добавь в первую главу подраздел про мониторинг поверхностных вод Минска»*\n"
        "• *«Сделай текст заключения более кратким и четким»*\n"
        "• *«Замени картинку в подразделе 1.1 на другую»*\n\n"
        "Я обновлю документ и пришлю новую версию!"
    )

@dp.callback_query(F.data == "regenerate")
async def cb_regenerate(call: types.CallbackQuery, bot: Bot):
    user_id = call.from_user.id
    session = SessionManager.get_session(user_id)
    topic = ""
    if session.current_doc_data:
        topic = session.current_doc_data.get("topic", "")
    elif session.current_pres_data:
        topic = session.current_pres_data.get("topic", "")

    if not topic:
        await call.answer("Нет данных для перегенерации.", show_alert=True)
        return

    await call.answer("Перегенерирую работу заново...")
    data = {
        "work_type": session.last_mode,
        "topic": topic,
        "include_images": True
    }
    await process_generation_request(call.message, bot, data)

async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не установлен! Укажите токен в файле .env")
        print("\n" + "="*60)
        print("ВНИМАНИЕ: TELEGRAM_BOT_TOKEN не указан в файле .env!")
        print("Пожалуйста, создайте бота через @BotFather в Telegram")
        print("и пропишите полученный токен в .env")
        print("="*60 + "\n")
        return

    # Start WebApp server in background
    try:
        await webapp_server.start_webapp_server()
    except Exception as e:
        logger.warning(f"Could not start WebApp server: {e}")

    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    logger.info("Bot starting polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
