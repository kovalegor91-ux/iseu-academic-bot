import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import pptx
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from config import OUTPUT_DIR, SAKHAROV_STANDARDS

logger = logging.getLogger(__name__)

class PptxGenerator:
    """
    Modern 16:9 PowerPoint Presentation Generator:
    - University aesthetic (Emerald / Dark Slate / Pure White / Clean Cards)
    - Structured content with bulleted cards and high-res illustrations
    - Integrated speaker notes on every slide
    """

    # Academic Palette
    COLOR_PRIMARY = RGBColor(18, 59, 47)      # Deep Forest Emerald
    COLOR_ACCENT = RGBColor(46, 125, 50)      # Muted Leaf Green
    COLOR_LIGHT_BG = RGBColor(248, 250, 249)  # Soft background
    COLOR_CARD_BG = RGBColor(242, 246, 244)   # Card background
    COLOR_TEXT_DARK = RGBColor(26, 37, 33)    # Deep charcoal
    COLOR_TEXT_MUTED = RGBColor(80, 95, 90)   # Slate gray
    COLOR_WHITE = RGBColor(255, 255, 255)

    @classmethod
    async def generate_presentation(
        cls,
        pres_data: Dict[str, Any],
        image_map: Optional[Dict[str, Path]] = None,
        output_filename: Optional[str] = None
    ) -> Path:
        prs = pptx.Presentation()
        # 16:9 Widescreen standard
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)
        blank_slide_layout = prs.slide_layouts[6]  # Blank layout

        image_map = image_map or {}
        slides = pres_data.get("slides", [])

        for idx, slide_info in enumerate(slides, 1):
            slide_type = slide_info.get("type", "content")
            slide = prs.slides.add_slide(blank_slide_layout)

            # Background fill
            cls._apply_background(slide)

            if slide_type == "title" or idx == 1:
                cls._render_title_slide(slide, slide_info, pres_data)
            elif slide_type == "conclusion" or idx == len(slides):
                cls._render_conclusion_slide(slide, slide_info)
            else:
                cls._render_content_slide(slide, slide_info, image_map)

            # Speaker Notes
            speech_notes = slide_info.get("speech_notes", "")
            if speech_notes:
                cls._add_speaker_notes(slide, speech_notes)

        topic_slug = "".join(c if c.isalnum() else "_" for c in pres_data.get("topic", "presentation")[:30]).strip("_")
        fname = output_filename or f"Sakharov_Презентация_{topic_slug}.pptx"
        output_path = OUTPUT_DIR / fname
        prs.save(output_path)
        logger.info(f"Generated PPTX presentation: {output_path}")
        return output_path

    @classmethod
    def _apply_background(cls, slide):
        """Fill slide background with subtle clean gradient/solid color."""
        background = slide.background
        fill = background.fill
        fill.solid()
        fill.fore_color.rgb = cls.COLOR_LIGHT_BG

    @classmethod
    def _render_title_slide(cls, slide, slide_info: Dict[str, Any], pres_data: Dict[str, Any]):
        """Render Title Slide with Sakharov Institute Header and Student Info."""
        # Top Header Bar
        header_box = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0), Inches(0), Inches(13.333), Inches(0.9)
        )
        header_box.fill.solid()
        header_box.fill.fore_color.rgb = cls.COLOR_PRIMARY
        header_box.line.fill.background()

        tf_header = header_box.text_frame
        tf_header.word_wrap = True
        p_hdr = tf_header.paragraphs[0]
        p_hdr.alignment = PP_ALIGN.CENTER
        r_hdr = p_hdr.add_run()
        r_hdr.text = "МЕЖДУНАРОДНЫЙ ГОСУДАРСТВЕННЫЙ ЭКОЛОГИЧЕСКИЙ ИНСТИТУТ ИМЕНИ А. Д. САХАРОВА БГУ"
        r_hdr.font.name = "Arial"
        r_hdr.font.size = Pt(13)
        r_hdr.font.bold = True
        r_hdr.font.color.rgb = cls.COLOR_WHITE

        # Main Title Box
        title_box = slide.shapes.add_textbox(Inches(1.2), Inches(1.8), Inches(10.9), Inches(2.6))
        tf_title = title_box.text_frame
        tf_title.word_wrap = True

        p_t = tf_title.paragraphs[0]
        p_t.alignment = PP_ALIGN.CENTER
        r_t = p_t.add_run()
        r_t.text = slide_info.get("title", pres_data.get("topic", "Тема доклада"))
        r_t.font.name = "Arial"
        r_t.font.size = Pt(32)
        r_t.font.bold = True
        r_t.font.color.rgb = cls.COLOR_PRIMARY

        subtitle = slide_info.get("subtitle", pres_data.get("faculty", "Факультет мониторинга окружающей среды"))
        p_sub = tf_title.add_paragraph()
        p_sub.alignment = PP_ALIGN.CENTER
        p_sub.space_before = Pt(14)
        r_sub = p_sub.add_run()
        r_sub.text = subtitle
        r_sub.font.name = "Calibri"
        r_sub.font.size = Pt(18)
        r_sub.font.color.rgb = cls.COLOR_TEXT_MUTED

        # Bottom Info Card (Author & Supervisor)
        card = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE,
            Inches(2.5), Inches(4.8), Inches(8.333), Inches(1.8)
        )
        card.fill.solid()
        card.fill.fore_color.rgb = cls.COLOR_CARD_BG
        card.line.color.rgb = cls.COLOR_ACCENT
        card.line.width = Pt(1.5)

        tf_card = card.text_frame
        tf_card.word_wrap = True
        p_c1 = tf_card.paragraphs[0]
        p_c1.alignment = PP_ALIGN.CENTER
        r_c1 = p_c1.add_run()
        r_c1.text = f"Выполнил(а): {pres_data.get('author', 'Студент МГЭИ им. А.Д. Сахарова')}"
        r_c1.font.name = "Calibri"
        r_c1.font.size = Pt(16)
        r_c1.font.bold = True
        r_c1.font.color.rgb = cls.COLOR_TEXT_DARK

        p_c2 = tf_card.add_paragraph()
        p_c2.alignment = PP_ALIGN.CENTER
        p_c2.space_before = Pt(6)
        r_c2 = p_c2.add_run()
        r_c2.text = f"Научный руководитель: {pres_data.get('supervisor', 'Преподаватель кафедры')}"
        r_c2.font.name = "Calibri"
        r_c2.font.size = Pt(15)
        r_c2.font.color.rgb = cls.COLOR_TEXT_MUTED

        p_c3 = tf_card.add_paragraph()
        p_c3.alignment = PP_ALIGN.CENTER
        p_c3.space_before = Pt(4)
        r_c3 = p_c3.add_run()
        r_c3.text = "Минск, 2026"
        r_c3.font.name = "Calibri"
        r_c3.font.size = Pt(13)
        r_c3.font.color.rgb = cls.COLOR_TEXT_MUTED

    @classmethod
    def _render_content_slide(cls, slide, slide_info: Dict[str, Any], image_map: Dict[str, Path]):
        """Render Standard Content Slide with Split Cards or Full Bullets."""
        # Top Title Accent
        title_text = slide_info.get("title", "Раздел исследования")
        t_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11.7), Inches(1.0))
        tf = t_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text = title_text
        r.font.name = "Arial"
        r.font.size = Pt(26)
        r.font.bold = True
        r.font.color.rgb = cls.COLOR_PRIMARY

        # Divider line
        line = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.8), Inches(1.35), Inches(11.733), Inches(0.04)
        )
        line.fill.solid()
        line.fill.fore_color.rgb = cls.COLOR_ACCENT
        line.line.fill.background()

        # Check if image is available for query
        img_query = slide_info.get("image_query", "")
        img_path = image_map.get(img_query)
        has_image = bool(img_path and img_path.exists())

        bullets = slide_info.get("bullets", [])

        if has_image:
            # Split Layout: Left Text Card (6.0"), Right Image Card (5.3")
            text_card = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE,
                Inches(0.8), Inches(1.6), Inches(6.0), Inches(5.2)
            )
            text_card.fill.solid()
            text_card.fill.fore_color.rgb = cls.COLOR_CARD_BG
            text_card.line.fill.background()

            tf_bullets = text_card.text_frame
            tf_bullets.word_wrap = True
            tf_bullets.margin_left = Inches(0.4)
            tf_bullets.margin_right = Inches(0.4)
            tf_bullets.margin_top = Inches(0.4)

            for b_idx, bullet in enumerate(bullets):
                p_b = tf_bullets.paragraphs[0] if b_idx == 0 else tf_bullets.add_paragraph()
                p_b.space_before = Pt(10) if b_idx > 0 else Pt(0)
                p_b.line_spacing = 1.2
                r_bullet = p_b.add_run()
                r_bullet.text = f"•  {bullet}"
                r_bullet.font.name = "Calibri"
                r_bullet.font.size = Pt(17)
                r_bullet.font.color.rgb = cls.COLOR_TEXT_DARK

            # Image on Right
            try:
                slide.shapes.add_picture(
                    str(img_path),
                    Inches(7.1), Inches(1.6),
                    width=Inches(5.4)
                )
            except Exception as e:
                logger.error(f"Error adding picture to PPTX: {e}")
        else:
            # Full Width Card
            full_card = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE,
                Inches(0.8), Inches(1.6), Inches(11.733), Inches(5.2)
            )
            full_card.fill.solid()
            full_card.fill.fore_color.rgb = cls.COLOR_CARD_BG
            full_card.line.fill.background()

            tf_bullets = full_card.text_frame
            tf_bullets.word_wrap = True
            tf_bullets.margin_left = Inches(0.6)
            tf_bullets.margin_right = Inches(0.6)
            tf_bullets.margin_top = Inches(0.5)

            for b_idx, bullet in enumerate(bullets):
                p_b = tf_bullets.paragraphs[0] if b_idx == 0 else tf_bullets.add_paragraph()
                p_b.space_before = Pt(14) if b_idx > 0 else Pt(0)
                p_b.line_spacing = 1.3
                r_bullet = p_b.add_run()
                r_bullet.text = f"✔  {bullet}"
                r_bullet.font.name = "Calibri"
                r_bullet.font.size = Pt(19)
                r_bullet.font.color.rgb = cls.COLOR_TEXT_DARK

    @classmethod
    def _render_conclusion_slide(cls, slide, slide_info: Dict[str, Any]):
        """Render Final Conclusion / Q&A Slide."""
        t_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.6), Inches(11.7), Inches(1.0))
        tf = t_box.text_frame
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text = slide_info.get("title", "Заключение и выводы")
        r.font.name = "Arial"
        r.font.size = Pt(28)
        r.font.bold = True
        r.font.color.rgb = cls.COLOR_PRIMARY

        card = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE,
            Inches(1.0), Inches(1.8), Inches(11.333), Inches(4.8)
        )
        card.fill.solid()
        card.fill.fore_color.rgb = cls.COLOR_CARD_BG
        card.line.color.rgb = cls.COLOR_ACCENT
        card.line.width = Pt(2.0)

        tf_card = card.text_frame
        tf_card.word_wrap = True
        tf_card.margin_left = Inches(0.8)
        tf_card.margin_right = Inches(0.8)
        tf_card.margin_top = Inches(0.6)

        bullets = slide_info.get("bullets", [])
        for b_idx, bullet in enumerate(bullets):
            p_b = tf_card.paragraphs[0] if b_idx == 0 else tf_card.add_paragraph()
            p_b.space_before = Pt(12) if b_idx > 0 else Pt(0)
            r_bullet = p_b.add_run()
            r_bullet.text = f"• {bullet}"
            r_bullet.font.name = "Calibri"
            r_bullet.font.size = Pt(19)
            r_bullet.font.color.rgb = cls.COLOR_TEXT_DARK

        # Final Thank You Box
        p_ty = tf_card.add_paragraph()
        p_ty.alignment = PP_ALIGN.CENTER
        r_ty = p_ty.add_run()
        r_ty.text = "Благодарю за внимание! Готов(а) ответить на вопросы."
        r_ty.font.name = "Arial"

        r_ty.font.size = Pt(22)
        r_ty.font.bold = True
        r_ty.font.color.rgb = cls.COLOR_PRIMARY

    @classmethod
    def _add_speaker_notes(cls, slide, speech_notes: str):
        """Add speaker notes to the slide for oral presentation defense."""
        try:
            notes_slide = slide.notes_slide
            tf = notes_slide.notes_text_frame
            tf.text = speech_notes
        except Exception as e:
            logger.debug(f"Failed to set speaker notes: {e}")
