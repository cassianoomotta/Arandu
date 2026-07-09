"""
Rebuild CRM.pptx with Arandu brand identity.
Dark obsidian backgrounds + gold gradients + tech style.
"""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn, nsmap
import copy
import os
from lxml import etree

# ── Brand Colors ──
OBSIDIAN = RGBColor(0x05, 0x05, 0x05)
DARK_BG = RGBColor(0x0A, 0x0A, 0x0F)
GOLD = RGBColor(0xC5, 0xA8, 0x5C)
GOLD_LIGHT = RGBColor(0xE8, 0xD0, 0x98)
GOLD_DARK = RGBColor(0x9A, 0x7B, 0x3E)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GRAY_TEXT = RGBColor(0xB0, 0xB0, 0xB0)
GRAY_SUBTLE = RGBColor(0x70, 0x70, 0x70)
DARK_SURFACE = RGBColor(0x10, 0x10, 0x10)  # slightly lighter than background
ACCENT_DARK = RGBColor(0x20, 0x1A, 0x0A)
LOGO_BG = RGBColor(2, 2, 2)  # Exact color of the logo background

# Slide dimensions (widescreen 10x5.625)
SLIDE_W = Emu(9144000)
SLIDE_H = Emu(5143500)

# Margins
MARGIN_L = Inches(0.8)
MARGIN_R = Inches(0.8)
CONTENT_W = SLIDE_W - MARGIN_L - MARGIN_R

# Logo paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_FULL_PATH = os.path.join(SCRIPT_DIR, 'arandu_logo_full.png')  # Full logo with text
LOGO_ICON_PATH = os.path.join(SCRIPT_DIR, 'arandu_icon.png')       # Icon only (golden A)


def create_presentation():
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    return prs


def set_solid_bg(slide):
    """Add a solid background to a slide to perfectly match the logo."""
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = LOGO_BG


def add_shape_gradient(shape, c1="C5A85C", c2="9A7B3E", angle=135):
    """Fill a shape with gradient."""
    fill = shape.fill
    fill.gradient()
    fill.gradient_stops[0].color.rgb = RGBColor.from_string(c1)
    fill.gradient_stops[0].position = 0.0
    fill.gradient_stops[1].color.rgb = RGBColor.from_string(c2)
    fill.gradient_stops[1].position = 1.0
    gsf_elem = fill._fill._element if hasattr(fill._fill, '_element') else fill._fill
    lin = gsf_elem.find(qn('a:lin'))
    if lin is None:
        lin = etree.SubElement(gsf_elem, qn('a:lin'))
    lin.set('ang', str(angle * 60000))
    lin.set('scaled', '1')


def add_gold_accent_line(slide, left, top, width, height=Pt(3)):
    """Add a thin gold accent line."""
    line_shape = slide.shapes.add_shape(1, left, top, width, height)  # 1 = rectangle
    line_shape.fill.solid()
    line_shape.fill.fore_color.rgb = GOLD
    line_shape.line.fill.background()
    return line_shape


def add_decorative_corner(slide, left, top, size=Inches(0.6), opacity_pct=15):
    """Add a subtle decorative corner element."""
    shape = slide.shapes.add_shape(1, left, top, size, size)
    shape.fill.solid()
    shape.fill.fore_color.rgb = ACCENT_DARK  # Use a dark gold-tinted color instead of transparency
    shape.line.fill.background()
    shape.rotation = 45.0
    return shape


def add_glass_card(slide, left, top, width, height):
    """Add a glassmorphism-style card (dark semi-transparent rectangle)."""
    card = slide.shapes.add_shape(1, left, top, width, height)
    card.fill.solid()
    card.fill.fore_color.rgb = DARK_SURFACE
    # Rounded corners via XML
    sp = card._element
    sp_pr = sp.find(qn('a:prstGeom')) or sp.find('.//' + qn('a:prstGeom'))
    # Set border to a subtle gold tint
    card.line.color.rgb = RGBColor(0x35, 0x2D, 0x1A)
    card.line.width = Pt(1)
    return card


def set_text(tf, text, size=Pt(14), color=WHITE, bold=False, align=PP_ALIGN.LEFT, font_name='Calibri'):
    """Set text in a text frame with styling."""
    tf.clear()
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = size
    run.font.color.rgb = color
    run.font.bold = bold
    run.font.name = font_name
    return run


def add_paragraph(tf, text, size=Pt(14), color=WHITE, bold=False, align=PP_ALIGN.LEFT, font_name='Calibri', space_before=Pt(4), space_after=Pt(4)):
    """Add a new paragraph to existing text frame."""
    p = tf.add_paragraph()
    p.alignment = align
    p.space_before = space_before
    p.space_after = space_after
    run = p.add_run()
    run.text = text
    run.font.size = size
    run.font.color.rgb = color
    run.font.bold = bold
    run.font.name = font_name
    return run


def add_bullet_point(tf, text, size=Pt(13), color=GRAY_TEXT, bullet_color=GOLD, font_name='Calibri'):
    """Add a bullet point with gold bullet marker."""
    p = tf.add_paragraph()
    p.space_before = Pt(6)
    p.space_after = Pt(2)
    # Gold bullet
    b_run = p.add_run()
    b_run.text = "▸  "
    b_run.font.size = size
    b_run.font.color.rgb = bullet_color
    b_run.font.name = font_name
    b_run.font.bold = True
    # Text
    t_run = p.add_run()
    t_run.text = text
    t_run.font.size = size
    t_run.font.color.rgb = color
    t_run.font.name = font_name
    return p


def add_text_box(slide, left, top, width, height):
    """Add a text box and return its text frame."""
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    return tf, txBox


def add_logo_large(slide, center_x=None, top=Inches(1.0), height=Inches(1.2)):
    """Add the full Arandu logo prominently (for title slide)."""
    logo_path = LOGO_FULL_PATH
    if not os.path.exists(logo_path):
        return None
    from PIL import Image as PILImage
    img = PILImage.open(logo_path)
    aspect = img.width / img.height
    w = int(height * aspect)
    if center_x is None:
        center_x = (SLIDE_W - w) // 2
    pic = slide.shapes.add_picture(logo_path, center_x, top, w, height)
    return pic


def add_logo_watermark(slide):
    """Add a small discrete Arandu icon in the bottom-right corner."""
    logo_path = LOGO_ICON_PATH
    if not os.path.exists(logo_path):
        return None
    logo_h = Inches(0.4)
    from PIL import Image as PILImage
    img = PILImage.open(logo_path)
    aspect = img.width / img.height
    logo_w = int(logo_h * aspect)
    left = SLIDE_W - logo_w - Inches(0.3)
    top = SLIDE_H - logo_h - Inches(0.15)
    pic = slide.shapes.add_picture(logo_path, left, top, logo_w, logo_h)
    return pic


def build_title_slide(prs):
    """Slide 1: CRM - Title slide with dramatic gradient."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank
    set_solid_bg(slide)

    # Decorative elements
    add_decorative_corner(slide, Inches(-0.3), Inches(-0.3), Inches(1.5), 8)
    add_decorative_corner(slide, Inches(8.8), Inches(4.2), Inches(1.5), 8)

    # Full logo (includes icon + ARANDU text + tagline)
    add_logo_large(slide, center_x=None, top=Inches(0.5), height=Inches(2.8))

    # Gold accent line below logo
    add_gold_accent_line(slide, Inches(3.5), Inches(3.5), Inches(3), Pt(2))

    # Main title
    tf, _ = add_text_box(slide, Inches(1), Inches(3.7), Inches(8), Inches(0.9))
    set_text(tf, "CRM", Pt(52), GOLD_LIGHT, bold=True, align=PP_ALIGN.CENTER, font_name='Calibri')

    # Subtitle
    tf, _ = add_text_box(slide, Inches(1.5), Inches(4.4), Inches(7), Inches(0.6))
    set_text(tf, "Customer Relationship Management", Pt(16), GRAY_TEXT, bold=False, align=PP_ALIGN.CENTER, font_name='Calibri')


def build_section_slide(prs, title_text, subtitle_text=None):
    """Section divider slide with centered text and dramatic styling."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_solid_bg(slide)

    # Left gold bar
    add_gold_accent_line(slide, Inches(0), Inches(0), Pt(4), SLIDE_H)

    # Center title
    tf, _ = add_text_box(slide, Inches(1), Inches(1.8), Inches(8), Inches(1.5))
    set_text(tf, title_text, Pt(36), GOLD_LIGHT, bold=True, align=PP_ALIGN.CENTER, font_name='Calibri')

    if subtitle_text:
        tf2, _ = add_text_box(slide, Inches(1.5), Inches(3.3), Inches(7), Inches(0.6))
        set_text(tf2, subtitle_text, Pt(14), GRAY_TEXT, bold=False, align=PP_ALIGN.CENTER, font_name='Calibri')

    # Bottom accent
    add_gold_accent_line(slide, Inches(4), Inches(4.5), Inches(2), Pt(2))

    # Discrete watermark logo
    add_logo_watermark(slide)


def build_content_slide(prs, title, bullets_left, bullets_right=None, title_color=WHITE):
    """Content slide with one or two columns."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_solid_bg(slide)

    # Top gold line
    add_gold_accent_line(slide, MARGIN_L, Inches(0.3), Inches(1.5), Pt(3))

    # Title
    tf, _ = add_text_box(slide, MARGIN_L, Inches(0.45), Inches(8.4), Inches(0.6))
    set_text(tf, title, Pt(26), title_color, bold=True, align=PP_ALIGN.LEFT, font_name='Calibri')

    # Separator line under title
    add_gold_accent_line(slide, MARGIN_L, Inches(1.1), Inches(8.4), Pt(1))

    if bullets_right is not None:
        # Two columns
        col_w = Inches(3.9)
        # Left card
        card_l = add_glass_card(slide, MARGIN_L, Inches(1.3), col_w, Inches(3.8))
        tf_l, _ = add_text_box(slide, Inches(1.0), Inches(1.4), Inches(3.5), Inches(3.6))
        for item in bullets_left:
            if item.get('header'):
                add_paragraph(tf_l, item['text'], Pt(16), GOLD, bold=True, space_before=Pt(8))
            else:
                add_bullet_point(tf_l, item['text'], Pt(12))

        # Right card
        card_r = add_glass_card(slide, Inches(5.3), Inches(1.3), col_w, Inches(3.8))
        tf_r, _ = add_text_box(slide, Inches(5.5), Inches(1.4), Inches(3.5), Inches(3.6))
        for item in bullets_right:
            if item.get('header'):
                add_paragraph(tf_r, item['text'], Pt(16), GOLD, bold=True, space_before=Pt(8))
            else:
                add_bullet_point(tf_r, item['text'], Pt(12))
    else:
        # Single column
        card = add_glass_card(slide, MARGIN_L, Inches(1.3), Inches(8.4), Inches(3.8))
        tf_c, _ = add_text_box(slide, Inches(1.0), Inches(1.4), Inches(8.0), Inches(3.6))
        for item in bullets_left:
            if item.get('header'):
                add_paragraph(tf_c, item['text'], Pt(16), GOLD, bold=True, space_before=Pt(8))
            else:
                add_bullet_point(tf_c, item['text'], Pt(12))

    # Footer brand
    tf, _ = add_text_box(slide, Inches(0), Inches(5.2), SLIDE_W, Inches(0.3))
    set_text(tf, "ARANDU  •  Consultoria & Tecnologia", Pt(7), GRAY_SUBTLE, align=PP_ALIGN.CENTER)

    # Discrete watermark logo
    add_logo_watermark(slide)


def build_full():
    prs = create_presentation()

    # ── Slide 1: Title ──
    build_title_slide(prs)

    # ── Slide 2: Showcase ──
    build_section_slide(prs, "Showcase", "Visão geral do projeto de transformação digital")

    # ── Slide 3: Programa de transformação digital ──
    build_section_slide(prs, "Programa de Transformação Digital")

    # ── Slide 4: Pergunta central ──
    build_section_slide(prs, "Devemos desenvolver um CRM próprio\nou contratar um CRM já existente\nno mercado?")

    # ── Slide 5: Pontos a serem considerados ──
    build_content_slide(prs,
        "Pontos a Serem Considerados",
        [
            {'text': 'Critérios de Avaliação', 'header': True},
            {'text': 'Valor entregue ao negócio'},
            {'text': 'Tempo de implementação'},
            {'text': 'Custos totais (TCO)'},
            {'text': 'Riscos envolvidos'},
        ],
        [
            {'text': 'Visão Estratégica', 'header': True},
            {'text': 'Flexibilidade operacional'},
            {'text': 'Vantagem competitiva'},
            {'text': 'Escalabilidade da solução'},
            {'text': 'Futuro da organização'},
        ]
    )

    # ── Slide 6: O problema não é um CRM ──
    build_content_slide(prs,
        "O Problema Não é um CRM",
        [
            {'text': 'O verdadeiro problema observado é:', 'header': True},
            {'text': 'Informações distribuídas em inúmeras planilhas'},
            {'text': 'Retrabalho manual constante'},
            {'text': 'Duplicidade de dados entre setores'},
            {'text': 'Dificuldade de encontrar informações'},
            {'text': 'Pouca rastreabilidade dos processos'},
            {'text': 'Ausência de histórico único do aluno'},
            {'text': 'Dificuldade para gerar indicadores'},
        ]
    )

    # ── Slide 7: Contratar CRM de mercado ──
    build_content_slide(prs,
        "Contratar um CRM de Mercado",
        [
            {'text': 'Benefícios', 'header': True},
            {'text': 'Implementação em semanas ao invés de meses'},
            {'text': 'Produto já validado por milhares de usuários'},
            {'text': 'Menor investimento inicial'},
            {'text': 'Não é necessário contratar equipe de dev'},
            {'text': 'Atualizações e evolução constantes'},
            {'text': 'Segurança, backups e conformidade LGPD'},
        ],
        [
            {'text': 'Desvantagens', 'header': True},
            {'text': 'Fluxos precisam se adaptar ao software'},
            {'text': 'Funcionalidades específicas podem não existir'},
            {'text': 'Dependência do fornecedor (vendor lock-in)'},
            {'text': 'Custos recorrentes de licenciamento'},
        ]
    )

    # ── Slide 8: Construir CRM próprio - Benefícios ──
    build_content_slide(prs,
        "Construir um CRM Próprio — Benefícios",
        [
            {'text': 'Vantagens Estratégicas', 'header': True},
            {'text': 'Sistema feito sob medida para a escola'},
            {'text': 'Processos desenhados como a operação funciona'},
            {'text': 'Sem funcionalidades desnecessárias'},
            {'text': 'Controle total dos dados sem dependência'},
            {'text': 'Evolução contínua alinhada ao negócio'},
        ]
    )

    # ── Slide 9: Construir CRM próprio - Desvantagens ──
    build_content_slide(prs,
        "Construir um CRM Próprio — Desvantagens",
        [
            {'text': 'Riscos e Custos', 'header': True},
            {'text': 'Tempo elevado de desenvolvimento'},
            {'text': 'Investimento alto: desenvolvimento, testes, infraestrutura, manutenção'},
            {'text': 'Responsabilidade permanente: bugs, atualizações, segurança, backup'},
            {'text': 'Risco tecnológico: atraso, aumento de custos, funcionalidades incompletas'},
        ]
    )

    # ── Slide 10: O que realmente gera valor ──
    build_section_slide(prs, "O que Realmente\nGera Valor", "Separando o operacional do estratégico")

    # ── Slide 11: Dois tipos de software ──
    build_content_slide(prs,
        "Existem Dois Tipos de Software",
        [
            {'text': 'Operacional', 'header': True},
            {'text': 'Ajuda a trabalhar no dia a dia'},
            {'text': 'Financeiro, Agenda, E-mail, WhatsApp, RH'},
            {'text': 'São facilmente comprados no mercado'},
            {'text': '→ Comprar tudo aquilo que é commodity'},
        ],
        [
            {'text': 'Estratégico', 'header': True},
            {'text': 'Representa o diferencial competitivo'},
            {'text': 'Metodologia pedagógica, Inteligência sobre o aluno'},
            {'text': 'Acompanhamento individual, Automações próprias'},
            {'text': 'Normalmente não é encontrado pronto'},
            {'text': '→ Construir somente aquilo que gera vantagem'},
        ]
    )

    # ── Slide 12: CRM de mercado - opções ──
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_solid_bg(slide)
    add_gold_accent_line(slide, MARGIN_L, Inches(0.3), Inches(1.5), Pt(3))

    tf, _ = add_text_box(slide, MARGIN_L, Inches(0.45), Inches(8.4), Inches(0.6))
    set_text(tf, "Opções de CRM de Mercado", Pt(26), WHITE, bold=True, font_name='Calibri')
    add_gold_accent_line(slide, MARGIN_L, Inches(1.1), Inches(8.4), Pt(1))

    # Create cards for each CRM option
    crm_options = [
        ("Attio CRM", "R$0,00 c/ limite"),
        ("Pipefy", "Consultar condições"),
        ("Twenty", "Auto hospedagem"),
        ("EspoCRM", "Auto hospedagem"),
        ("Odoo", "Plataforma completa"),
        ("Zoho CRM", "Plano gratuito disponível"),
        ("Pipedrive", "Trial disponível"),
    ]

    cols = 3
    card_w = Inches(2.6)
    card_h = Inches(1.2)
    gap_x = Inches(0.2)
    gap_y = Inches(0.15)
    start_x = MARGIN_L
    start_y = Inches(1.35)

    for idx, (name, desc) in enumerate(crm_options):
        row = idx // cols
        col = idx % cols
        x = start_x + col * (card_w + gap_x)
        y = start_y + row * (card_h + gap_y)

        card = add_glass_card(slide, x, y, card_w, card_h)
        tf, _ = add_text_box(slide, x + Inches(0.15), y + Inches(0.2), card_w - Inches(0.3), Inches(0.4))
        set_text(tf, name, Pt(15), GOLD_LIGHT, bold=True, font_name='Calibri')
        tf2, _ = add_text_box(slide, x + Inches(0.15), y + Inches(0.65), card_w - Inches(0.3), Inches(0.4))
        set_text(tf2, desc, Pt(11), GRAY_TEXT, font_name='Calibri')

    tf, _ = add_text_box(slide, Inches(0), Inches(5.2), SLIDE_W, Inches(0.3))
    set_text(tf, "ARANDU  •  Consultoria & Tecnologia", Pt(7), GRAY_SUBTLE, align=PP_ALIGN.CENTER)
    add_logo_watermark(slide)

    # ── Slide 13: Porque não criar o próprio ──
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_solid_bg(slide)
    add_gold_accent_line(slide, Inches(0), Inches(0), Pt(4), SLIDE_H)

    tf, _ = add_text_box(slide, Inches(1), Inches(1.5), Inches(8), Inches(1))
    set_text(tf, "Por que Não Criar o Próprio?", Pt(32), GOLD_LIGHT, bold=True, align=PP_ALIGN.CENTER, font_name='Calibri')

    # Reference card
    card = add_glass_card(slide, Inches(2), Inches(2.8), Inches(6), Inches(1.2))
    tf, _ = add_text_box(slide, Inches(2.3), Inches(2.9), Inches(5.4), Inches(0.4))
    set_text(tf, "Leitura recomendada:", Pt(12), GRAY_TEXT, font_name='Calibri')
    tf2, _ = add_text_box(slide, Inches(2.3), Inches(3.3), Inches(5.4), Inches(0.5))
    set_text(tf2, "crmpiperun.com/blog/crm-interno/", Pt(14), GOLD, bold=True, font_name='Calibri')

    add_gold_accent_line(slide, Inches(4), Inches(4.5), Inches(2), Pt(2))
    add_logo_watermark(slide)

    # Save to proposals folder in project root
    project_root = os.path.dirname(os.path.dirname(__file__))
    proposals_dir = os.path.join(project_root, 'propostas')
    os.makedirs(proposals_dir, exist_ok=True)
    output_path = os.path.join(proposals_dir, 'CRM_Arandu.pptx')
    prs.save(output_path)
    print(f'[OK] Apresentacao salva em: {output_path}')
    print(f'   Total de slides: {len(prs.slides)}')


if __name__ == '__main__':
    build_full()
