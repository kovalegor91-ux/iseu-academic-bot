import os
import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import docx
from docx.shared import Pt, Inches, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls
from config import OUTPUT_DIR, SAKHAROV_STANDARDS

logger = logging.getLogger(__name__)

class DocxGenerator:
    """
    High-fidelity DOCX generator complying strictly with ISEU Sakharov BSU standards:
    - Times New Roman 14 pt, 1.5 line spacing, 1.25 cm first line indent, justified alignment
    - Correct A4 margins: Left 30mm, Right 10mm, Top 20mm, Bottom 20mm
    - Official Title Page for ISEU named after A.D. Sakharov BSU
    - Page numbering in footer (bottom center, skipping first page)
    - Figures captioned per GOST: 'Рисунок 1 — Название'
    - Formatted Table of Contents and Literature list
    """

    @classmethod
    async def generate_document(
        cls,
        doc_data: Dict[str, Any],
        image_map: Optional[Dict[str, Path]] = None,
        output_filename: Optional[str] = None
    ) -> Path:
        doc = docx.Document()
        image_map = image_map or {}

        # 1. Page Setup (A4 and exact margins)
        section = doc.sections[0]
        section.page_width = Cm(21.0)
        section.page_height = Cm(29.7)
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(3.0)
        section.right_margin = Cm(1.0)

        # 2. Setup Normal Style
        normal_style = doc.styles['Normal']
        normal_style.font.name = 'Times New Roman'
        normal_style.font.size = Pt(14)
        normal_style.font.color.rgb = RGBColor(0, 0, 0)

        # Enable Page Numbering in Footer (centered, skipping first page)
        section.different_first_page_header_footer = True
        footer = section.footer
        footer_p = footer.paragraphs[0]
        footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cls._add_page_number_field(footer_p)

        # Enable Word automatic field updates (TOC, page numbers) on document open
        try:
            settings_el = doc.settings.element
            upd = OxmlElement('w:updateFields')
            upd.set(qn('w:val'), 'true')
            settings_el.append(upd)
        except Exception as e:
            logger.debug(f"Could not set updateFields: {e}")

        # 3. Read Section Inclusions
        sec_cfg = doc_data.get("sections_config", {})
        inc_title = doc_data.get("include_title_page", sec_cfg.get("title_page", True))
        inc_toc = doc_data.get("include_toc", sec_cfg.get("toc", True))
        inc_intro = doc_data.get("include_intro", sec_cfg.get("intro", True))
        inc_body = doc_data.get("include_body", sec_cfg.get("body", True))
        inc_concl = doc_data.get("include_conclusion", sec_cfg.get("conclusion", True))
        inc_bib = doc_data.get("include_bibliography", sec_cfg.get("bibliography", True))
        inc_app = doc_data.get("include_appendix", sec_cfg.get("appendix", not doc_data.get("no_appendix", False)))

        has_prev_section = False

        # 4. Build Title Page
        if inc_title:
            cls._build_title_page(doc, doc_data)
            has_prev_section = True

        # 5. Build Dynamic Table of Contents
        if inc_toc:
            if has_prev_section:
                doc.add_page_break()
            cls._build_table_of_contents(doc, doc_data)
            has_prev_section = True

        # 6. Build Introduction
        if inc_intro:
            if has_prev_section:
                doc.add_page_break()
            cls._build_introduction(doc, doc_data)
            has_prev_section = True

        # 7. Build Main Sections & Subsections with Figures
        if inc_body:
            figure_counter = 1
            sections = doc_data.get("sections", [])
            no_subs = doc_data.get("no_subsections", False)
            for sec_idx, sec in enumerate(sections, 1):
                if has_prev_section and sec_idx == 1:
                    doc.add_page_break()
                cls._build_section(doc, sec, figure_counter, image_map, no_subsections=no_subs)
                # Count figures added
                for sub in sec.get("subsections", []):
                    if sub.get("image_needed") and sub.get("image_query") in image_map:
                        figure_counter += 1
                if sec_idx < len(sections):
                    doc.add_page_break()
            has_prev_section = True

        # 8. Build Conclusion
        if inc_concl:
            if has_prev_section:
                doc.add_page_break()
            cls._build_conclusion(doc, doc_data)
            has_prev_section = True

        # 9. Build Bibliography (Список использованных источников)
        if inc_bib:
            if has_prev_section:
                doc.add_page_break()
            cls._build_bibliography(doc, doc_data)
            has_prev_section = True

        # 10. If Speech Text exists, append as Appendix
        if inc_app and doc_data.get("speech_text") and not doc_data.get("no_appendix", False):
            if has_prev_section:
                doc.add_page_break()
            cls._build_speech_notes_appendix(doc, doc_data["speech_text"])

        # Save file
        topic_slug = "".join(c if c.isalnum() else "_" for c in doc_data.get("topic", "work")[:30]).strip("_")
        fname = output_filename or f"Sakharov_{doc_data.get('work_type', 'Реферат')}_{topic_slug}.docx"
        output_path = OUTPUT_DIR / fname
        doc.save(output_path)
        logger.info(f"Generated DOCX document: {output_path}")
        return output_path

    @classmethod
    def _add_page_number_field(cls, paragraph):
        """Insert dynamic PAGE field into Word paragraph footer."""
        run = paragraph.add_run()
        run.font.name = 'Times New Roman'
        run.font.size = Pt(12)
        fldSimple = OxmlElement('w:fldSimple')
        fldSimple.set(qn('w:instr'), 'PAGE')
        run._r.append(fldSimple)

    @classmethod
    def _set_outline_level(cls, paragraph, level: int = 0):
        """Assign outline level so Word TOC automatically registers this heading."""
        try:
            pPr = paragraph._element.get_or_add_pPr()
            lvl = OxmlElement('w:outlineLvl')
            lvl.set(qn('w:val'), str(level))
            pPr.append(lvl)
        except Exception as e:
            logger.debug(f"Could not set outline level: {e}")

    @classmethod
    def _format_body_paragraph(cls, p, text: str = ""):
        """Apply standard body formatting: 14pt, 1.5 spacing, 1.25cm indent, justified."""
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.line_spacing = 1.5
        p.paragraph_format.first_line_indent = Cm(1.25)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        if text:
            run = p.add_run(text)
            run.font.name = 'Times New Roman'
            run.font.size = Pt(14)

    @classmethod
    def _build_title_page(cls, doc: docx.Document, data: Dict[str, Any]):
        """Generate official ISEU Sakharov BSU Title Page."""
        uni_info = SAKHAROV_STANDARDS.get("university", {})
        ministry = uni_info.get("ministry", "МИНИСТЕРСТВО ОБРАЗОВАНИЯ РЕСПУБЛИКИ БЕЛАРУСЬ")
        univ = uni_info.get("university_name", "БЕЛОРУССКИЙ ГОСУДАРСТВЕННЫЙ УНИВЕРСИТЕТ")
        inst = uni_info.get("institute_name", "МЕЖДУНАРОДНЫЙ ГОСУДАРСТВЕННЫЙ ЭКОЛОГИЧЕСКИЙ ИНСТИТУТ ИМЕНИ А. Д. САХАРОВА")

        # Header lines
        headers = [
            ministry,
            univ,
            inst,
            data.get("faculty", "Факультет мониторинга окружающей среды"),
            data.get("department", "Кафедра экологического мониторинга")
        ]
        for line in headers:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(2)
            run = p.add_run(line)
            run.font.name = 'Times New Roman'
            run.font.size = Pt(11)
            run.bold = True

        # Spacing
        for _ in range(4):
            doc.add_paragraph()

        # Work Type & Topic
        p_type = doc.add_paragraph()
        p_type.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_type.paragraph_format.space_after = Pt(6)
        r_type = p_type.add_run(data.get("work_type", "РЕФЕРАТ").upper())
        r_type.font.name = 'Times New Roman'
        r_type.font.size = Pt(18)
        r_type.bold = True

        p_disc = doc.add_paragraph()
        p_disc.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_disc.paragraph_format.space_after = Pt(12)
        r_disc = p_disc.add_run(f"по дисциплине: «{data.get('discipline', 'Экология')}»")
        r_disc.font.name = 'Times New Roman'
        r_disc.font.size = Pt(14)

        p_topic = doc.add_paragraph()
        p_topic.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_topic.paragraph_format.space_after = Pt(18)
        r_topic = p_topic.add_run(f"на тему: «{data.get('topic', 'Тема работы')}»")
        r_topic.font.name = 'Times New Roman'
        r_topic.font.size = Pt(15)
        r_topic.bold = True

        # Spacing
        for _ in range(3):
            doc.add_paragraph()

        # Author and Supervisor Block (Right-aligned table or tabbed)
        student = data.get("student", {})
        st_name = student.get("name", "Иванов И.И.")
        st_course = student.get("course", "3")
        st_group = student.get("group", "301")
        supervisor = data.get("supervisor", "доцент, к.б.н. Петров П.П.")

        table = doc.add_table(rows=1, cols=2)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        table.columns[0].width = Cm(8.0)
        table.columns[1].width = Cm(9.0)

        cell_right = table.cell(0, 1)
        lines_info = [
            ("Выполнил(а):", True),
            (f"студент(ка) {st_course} курса группы {st_group}", False),
            (f"{st_name}", True),
            ("", False),
            ("Проверил(а):", True),
            (f"{supervisor}", False)
        ]
        for text, bold in lines_info:
            p = cell_right.add_paragraph()
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(text)
            r.font.name = 'Times New Roman'
            r.font.size = Pt(13)
            r.bold = bold

        # Bottom City and Year
        for _ in range(4):
            doc.add_paragraph()

        p_city = doc.add_paragraph()
        p_city.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_city.paragraph_format.space_after = Pt(0)
        r_city = p_city.add_run(f"Минск, {data.get('year', '2026')}")
        r_city.font.name = 'Times New Roman'
        r_city.font.size = Pt(14)

    @classmethod
    def _build_table_of_contents(cls, doc: docx.Document, data: Dict[str, Any]):
        """Build automatic dynamic Table of Contents with native Word field update."""
        p_title = doc.add_paragraph()
        p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_title.paragraph_format.space_before = Pt(0)
        p_title.paragraph_format.space_after = Pt(18)
        r = p_title.add_run("СОДЕРЖАНИЕ")
        r.font.name = 'Times New Roman'
        r.font.size = Pt(14)
        r.bold = True

        # Native Microsoft Word Dynamic TOC Field (updates automatically on open or F9/Update Field)
        p_fld = doc.add_paragraph()
        p_fld.paragraph_format.space_before = Pt(0)
        p_fld.paragraph_format.space_after = Pt(12)
        p_fld.paragraph_format.first_line_indent = Cm(0)
        r_fld = p_fld.add_run()
        fldSimple = OxmlElement('w:fldSimple')
        fldSimple.set(qn('w:instr'), r'TOC \o "1-2" \h \z \u')
        r_fld._r.append(fldSimple)

    @classmethod
    def _build_introduction(cls, doc: docx.Document, data: Dict[str, Any]):
        """Build Introduction section."""
        p_title = doc.add_paragraph()
        p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_title.paragraph_format.space_after = Pt(14)
        cls._set_outline_level(p_title, 0)
        r = p_title.add_run("ВВЕДЕНИЕ")
        r.font.name = 'Times New Roman'
        r.font.size = Pt(14)
        r.bold = True

        intro = data.get("introduction", {})
        relevance = intro.get("relevance", "")
        if relevance:
            for para in relevance.split("\n\n"):
                if para.strip():
                    cls._format_body_paragraph(doc.add_paragraph(), para.strip())

        # Goal and Tasks
        if intro.get("goal"):
            p = doc.add_paragraph()
            cls._format_body_paragraph(p)
            r_g = p.add_run("Цель исследования: ")
            r_g.bold = True
            p.add_run(intro["goal"])

        tasks = intro.get("tasks", [])
        if tasks:
            p_t = doc.add_paragraph()
            cls._format_body_paragraph(p_t)
            r_t = p_t.add_run("Для достижения поставленной цели необходимо решить следующие задачи:")
            r_t.bold = True
            for idx, task in enumerate(tasks, 1):
                p_task = doc.add_paragraph()
                p_task.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                p_task.paragraph_format.line_spacing = 1.5
                p_task.paragraph_format.first_line_indent = Cm(1.25)
                p_task.paragraph_format.space_before = Pt(0)
                p_task.paragraph_format.space_after = Pt(0)
                r_item = p_task.add_run(f"– {task};" if idx < len(tasks) else f"– {task}.")
                r_item.font.name = 'Times New Roman'
                r_item.font.size = Pt(14)

        if intro.get("object"):
            p = doc.add_paragraph()
            cls._format_body_paragraph(p)
            p.add_run("Объект исследования: ").bold = True
            p.add_run(intro["object"])

        if intro.get("subject"):
            p = doc.add_paragraph()
            cls._format_body_paragraph(p)
            p.add_run("Предмет исследования: ").bold = True
            p.add_run(intro["subject"])

        if intro.get("methods"):
            p = doc.add_paragraph()
            cls._format_body_paragraph(p)
            p.add_run("Методы исследования: ").bold = True
            p.add_run(intro["methods"])

    @classmethod
    def _build_section(
        cls,
        doc: docx.Document,
        sec: Dict[str, Any],
        figure_start_num: int,
        image_map: Dict[str, Path],
        no_subsections: bool = False
    ):
        """Build Main Section (Глава) and Subsections."""
        sec_num = sec.get("number", 1)
        sec_title = sec.get("title", "")

        # Section Heading 1: НАЗВАНИЕ ГЛАВЫ (all caps, bold, 14pt, center, without numbers)
        p_sec = doc.add_paragraph()
        p_sec.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_sec.paragraph_format.first_line_indent = Cm(0)
        p_sec.paragraph_format.space_before = Pt(14)
        p_sec.paragraph_format.space_after = Pt(12)
        p_sec.paragraph_format.line_spacing = 1.5
        cls._set_outline_level(p_sec, 0)
        
        # Strip any leading numbers ("1 ", "1.", "Глава 1: ", etc.)
        clean_title = re.sub(r"^(глава\s*)?\d*[\.\s\-—:]*", "", str(sec_title), flags=re.IGNORECASE).strip()
        r_sec = p_sec.add_run(clean_title.upper())
        r_sec.font.name = 'Times New Roman'
        r_sec.font.size = Pt(14)
        r_sec.bold = True

        current_fig_num = figure_start_num
        no_subs = no_subsections or sec.get("no_subsections", False)

        # Direct paragraphs on section if no subsections
        if "paragraphs" in sec and sec["paragraphs"]:
            for para_idx, text in enumerate(sec["paragraphs"]):
                p = doc.add_paragraph()
                cls._format_body_paragraph(p, text)
                if sec.get("image_needed") and para_idx == 0:
                    q = sec.get("image_query", "")
                    img_path = image_map.get(q)
                    if img_path and img_path.exists():
                        cls._insert_figure(doc, img_path, current_fig_num, sec.get("image_caption", q))
                        current_fig_num += 1

        for sub in sec.get("subsections", []):
            sub_num = sub.get("number", f"{sec_num}.1")
            sub_title = sub.get("title", "")

            # Subsection Heading 2: 1.1 Название подраздела (only if not no_subs)
            if not no_subs and sub_title:
                p_sub = doc.add_paragraph()
                p_sub.paragraph_format.first_line_indent = Cm(1.25)
                p_sub.paragraph_format.space_before = Pt(10)
                p_sub.paragraph_format.space_after = Pt(8)
                p_sub.paragraph_format.line_spacing = 1.5
                cls._set_outline_level(p_sub, 1)
                r_sub = p_sub.add_run(f"{sub_num} {sub_title}")
                r_sub.font.name = 'Times New Roman'
                r_sub.font.size = Pt(14)
                r_sub.bold = True

            # Paragraphs
            paragraphs = sub.get("paragraphs", [])
            for para_idx, text in enumerate(paragraphs):
                p = doc.add_paragraph()
                cls._format_body_paragraph(p, text)

                # Insert figure if needed after first or middle paragraph
                if sub.get("image_needed") and para_idx == 0:
                    q = sub.get("image_query", "")
                    img_path = image_map.get(q)
                    if img_path and img_path.exists():
                        cls._insert_figure(doc, img_path, current_fig_num, sub.get("image_caption", q))
                        current_fig_num += 1

    @classmethod
    def _insert_figure(cls, doc: docx.Document, img_path: Path, fig_number: int, caption: str):
        """Insert figure centered with GOST caption: 'Рисунок 1 — Название'."""
        try:
            # Figure Image paragraph
            p_img = doc.add_paragraph()
            p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_img.paragraph_format.space_before = Pt(10)
            p_img.paragraph_format.space_after = Pt(4)
            p_img.paragraph_format.first_line_indent = Cm(0)
            run_img = p_img.add_run()
            # Determine appropriate size based on aspect ratio so image never exceeds 3.5 inches in height
            from PIL import Image as PILImage
            with PILImage.open(img_path) as im:
                im_w, im_h = im.size

            if im_h > im_w:
                # Vertical/portrait image: cap height to 3.1 inches (~8 cm)
                run_img.add_picture(str(img_path), height=Inches(3.1))
            else:
                # Landscape: ensure height never exceeds 3.4 inches
                aspect = im_h / im_w
                if 5.0 * aspect > 3.4:
                    run_img.add_picture(str(img_path), height=Inches(3.4))
                else:
                    run_img.add_picture(str(img_path), width=Inches(5.0))

            # Figure Caption paragraph
            p_cap = doc.add_paragraph()
            p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_cap.paragraph_format.space_before = Pt(2)
            p_cap.paragraph_format.space_after = Pt(12)
            p_cap.paragraph_format.first_line_indent = Cm(0)

            # Strip any preexisting 'Рисунок X —' or 'Рис. X' to prevent duplicates
            clean_cap = re.sub(r"^(рисунок|рис\.?)\s*\d*\s*[-—–:]*\s*", "", str(caption), flags=re.IGNORECASE).strip()
            clean_cap = re.sub(r"^(рисунок|рис\.?)\s*\d*\s*[-—–:]*\s*", "", clean_cap, flags=re.IGNORECASE).strip()
            cap_text = f"Рисунок {fig_number} — {clean_cap}" if clean_cap else f"Рисунок {fig_number}"

            r_cap = p_cap.add_run(cap_text)
            r_cap.font.name = 'Times New Roman'
            r_cap.font.size = Pt(12)
        except Exception as e:
            logger.error(f"Error inserting figure {img_path}: {e}")

    @classmethod
    def _build_conclusion(cls, doc: docx.Document, data: Dict[str, Any]):
        """Build Conclusion section."""
        p_title = doc.add_paragraph()
        p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_title.paragraph_format.space_after = Pt(14)
        cls._set_outline_level(p_title, 0)
        r = p_title.add_run("ЗАКЛЮЧЕНИЕ")
        r.font.name = 'Times New Roman'
        r.font.size = Pt(14)
        r.bold = True

        conclusions = data.get("conclusion", [])
        if isinstance(conclusions, list):
            for item in conclusions:
                cls._format_body_paragraph(doc.add_paragraph(), item)
        elif isinstance(conclusions, str):
            for para in conclusions.split("\n\n"):
                if para.strip():
                    cls._format_body_paragraph(doc.add_paragraph(), para.strip())

    @classmethod
    def _build_bibliography(cls, doc: docx.Document, data: Dict[str, Any]):
        """Build Bibliography section per GOST 7.1-2003 / VAK RB."""
        p_title = doc.add_paragraph()
        p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_title.paragraph_format.space_after = Pt(14)
        cls._set_outline_level(p_title, 0)
        r = p_title.add_run("СПИСОК ИСПОЛЬЗОВАННЫХ ИСТОЧНИКОВ")
        r.font.name = 'Times New Roman'
        r.font.size = Pt(14)
        r.bold = True

        sources = data.get("bibliography", [])
        for src in sources:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.line_spacing = 1.5
            p.paragraph_format.first_line_indent = Cm(1.25)
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(4)
            run = p.add_run(src)
            run.font.name = 'Times New Roman'
            run.font.size = Pt(14)

    @classmethod
    def _build_speech_notes_appendix(cls, doc: docx.Document, speech_text: str):
        """Append speaking notes for oral defense."""
        p_title = doc.add_paragraph()
        p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_title.paragraph_format.space_after = Pt(14)
        cls._set_outline_level(p_title, 0)
        r = p_title.add_run("ПРИЛОЖЕНИЕ А\nТезисы доклада для защиты (речь выступления)")
        r.font.name = 'Times New Roman'
        r.font.size = Pt(14)
        r.bold = True

        for para in speech_text.split("\n\n"):
            if para.strip():
                cls._format_body_paragraph(doc.add_paragraph(), para.strip())
