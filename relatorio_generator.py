from flask import Flask, render_template_string, request, send_from_directory, redirect, url_for
from reportlab.pdfgen import canvas
from pdfrw import PdfReader, PdfWriter, PageMerge
from pathlib import Path
import re, random, os

app = Flask(__name__)
app.secret_key = "chave_secreta_segura"

# NOME DO ARQUIVO PDF DE FUNDO
TEMPLATE_PDF = "CROQUI.pdf"
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

# --- CONFIGURAÇÃO: BANCO DE DADOS DE TÉCNICOS ---
DB_TECNICOS = {
    "agnaldo venancio": "0102060458",
    "alessandro ferreira": "0102047065",
    "cleiton irani": "0102059450",
    "emerson pereira": "0102059848",
    "erickson fernando": "0102053031",
    "joaquim otavio": "0102063826",
    "julio cesar": "0102050030",
    "leandro dias": "0102055139",
    "leonardo félix": "0102063528",
    "marcos paulo": "0124064676",
    "murilo de oliveira": "0102063941",
    "pablo daniel": "0102059303",
    "roger ribeiro": "0102054899",
    "ruan augusto": "0124064626",
    "talissa aparecida": "0102044461",
    "welington josé": "0102047056",
    "aguilson lucas": "0102062737",
    "alan almeida": "0102062248",
    "alan bruno": "0118065433",
    "alex feitosa": "0102064113",
    "caio rodrigo": "0118064757",
    "diogo primo silva": "0102056374",
    "edmilson dos santos": "0102060449",
    "edson rosa": "0118064670",
    "elias fonseca": "0118064645",
    "felipe fontoura": "102062731",
    "felipe nunes": "0102063906",
    "fernando aparecido": "0102060636",
    "henrique de lima": "102063911",
    "joao gabriel": "0118065540",
    "jonathan dos santos": "0102060445",
    "jose gabriel": "0102060418",
    "julio cesar silva": "102060638",
    "jurandi wesley": "0118064679",
    "kelvin gomes": "0102062255",
    "lucas amorim": "0118064689",
    "marcio barbosa": "0102062727",
    "marco de lucca": "0102062770",
    "mauricio oliveira": "0118064616",
    "ruan vinicius": "0102064131",
    "wendel ribeiro": "0102064177"
}

# --- CONFIGURAÇÃO: APELIDOS / VARIAÇÕES (Mapeia Apelido -> Nome Oficial) ---
# O sistema vai procurar isso no texto, mas salvar o nome oficial
DB_ALIASES = {
    # agnaldo
    "agnaldo": "agnaldo venancio",
    "aguinaldo": "agnaldo venancio",
    "agnaldo brisola": "agnaldo venancio",
    # alessandro
    "alessandro": "alessandro ferreira",
    "alessandro morais": "alessandro ferreira",
    # cleiton
    "cleiton": "cleiton irani",
    "cleiton benfica": "cleiton irani",
    # emerson
    "emerson": "emerson pereira",
    "emerson silva": "emerson pereira",
    # erickson
    "erickson": "erickson fernando",
    "erickson leme": "erickson fernando",
    # joaquim
    "joaquim": "joaquim otavio",
    "joaquim vaz": "joaquim otavio",
    # julio (moraes)
    "julio": "julio cesar",
    "julio moraes": "julio cesar",
    # leandro
    "leandro": "leandro dias",
    "leandro junior": "leandro dias",
    # leonardo
    "leonardo": "leonardo félix",
    "leonardo junior": "leonardo félix",
    # marcos
    "marcos": "marcos paulo",
    "marcos santos": "marcos paulo",
    # murilo
    "murilo": "murilo de oliveira",
    "murilo graca": "murilo de oliveira",
    # pablo
    "pablo": "pablo daniel",
    "pablo antonio": "pablo daniel",
    # roger
    "roger": "roger ribeiro",
    "roger gomes": "roger ribeiro",
    # ruan augusto
    "ruan": "ruan augusto",
    "ruan caetano": "ruan augusto",
    # talissa
    "talissa": "talissa aparecida",
    "talissa andrade": "talissa aparecida",
    # welington
    "welington": "welington josé",
    "welington batista": "welington josé",
    # aguilson
    "aguilson": "aguilson lucas",
    # alan almeida
    "alan": "alan almeida",
    # alan bruno
    "alan bruno": "alan bruno",
    # alex
    "alex": "alex feitosa",
    # caio
    "caio": "caio rodrigo",
    # diogo
    "diogo": "diogo primo silva",
    # edmilson
    "edmilson": "edmilson dos santos",
    # edson
    "edson": "edson rosa",
    # elias
    "elias": "elias fonseca",
    # felipe
    "felipe": "felipe nunes",
    # fernando
    "fernando": "fernando aparecido",
    # henrique
    "henrique": "henrique de lima",
    # joao
    "joao": "joao gabriel",
    # jonathan
    "jonathan": "jonathan dos santos",
    # jose
    "jose": "jose gabriel",
    # julio silva (segundo julio)
    "julio silva": "julio cesar silva",
    # jurandi
    "jurandi": "jurandi wesley",
    # kelvin
    "kelvin": "kelvin gomes",
    # lucas
    "lucas": "lucas amorim",
    # marcio
    "marcio": "marcio barbosa",
    # marco
    "marco": "marco de lucca",
    "marco lucca": "marco de lucca",
    # mauricio
    "mauricio": "mauricio oliveira",
    # ruan vinicius
    "ruan vinicius": "ruan vinicius",
    # wendel
    "wendel": "wendel ribeiro",
}
# ----------------------------
# Configurações de Posição
# ----------------------------
COORDS = {
    'codigo_obra': (0.18, 0.039),
    'ta': (0.20, 0.182),
    'causa': (0.17, 0.152),
    'endereco': (0.17, 0.125),
    'localidade': (0.11, 0.096),
    'es': (0.28, 0.096),
    'at': (0.34, 0.096),
    'tronco': (0.10, 0.067),
    'veiculo': (0.47, 0.040),
    'supervisor': (0.63, 0.040),
    'data': (0.83, 0.049),
    'materials_block': (0.045, 0.33),
    'croqui_rect': (0.02, 0.65, 0.95, 0.90)
}

EXEC_CONFIG = {
    'name_x': 0.47,
    're_x': 0.65,
    'start_y': 0.212,
    'step_y': 0.028,
    'max_rows': 6
}

FILTRO_LANCAMENTO = ["metr", "lancado", "lançado", "lancamento", "lançamento"]


# ----------------------------
# Funções Auxiliares (Parsing)
# ----------------------------
def pct_to_pt(xpct, ypct, width_pt, height_pt):
    return xpct * width_pt, ypct * height_pt


def extract_fields(text):
    """
    Função usada APENAS na colagem inicial para preencher o formulário.
    """
    data = {key: '' for key in ['ta', 'codigo_obra', 'causa', 'endereco',
                                'localidade', 'es', 'at', 'tronco',
                                'veiculo', 'data', 'supervisor']}

    text = text.replace('\r\n', '\n').strip()

    # 1. SIGLAS ES.AT (ex: SOC.CR, ignorando .com.br)
    match_sigla = re.search(r"\b(?!(?:com|net|org|gov|www|vivo|http)\b)([a-zA-Z]{3})\.([a-zA-Z]{2})\b", text,
                            re.IGNORECASE)
    if match_sigla:
        data['es'] = match_sigla.group(1).upper()
        data['at'] = match_sigla.group(2).upper()

    # 2. HEADER (SGM - TA)
    match_header = re.search(r"(\d{8,})\s*-\s*TA\s*(\d{8,})", text)
    if match_header:
        data['codigo_obra'] = match_header.group(1)
        data['ta'] = match_header.group(2)
    else:
        m_ta = re.search(r"TA\s*[:\-]?\s*(\d{5,})", text, re.IGNORECASE)
        if m_ta: data['ta'] = m_ta.group(1)
        m_sgm = re.search(r"(?:SGM|Obra)\s*[:\-]?\s*(\d{6,})", text, re.IGNORECASE)
        if m_sgm: data['codigo_obra'] = m_sgm.group(1)

    # 3. CAMPOS GERAIS
    patterns = [
        (r"(?:causa|motivo)\s*[:;\-]?\s*(.+)", 'causa'),
        (r"(?:localidade|cidade)\s*[:;\-]?\s*(.+)", 'localidade'),
        (r"ve[ií]culo\s*[:;\-]?\s*(\S+)", 'veiculo'),
        (r"data\s*[:;\-]?\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})", 'data'),
    ]

    for pattern, key in patterns:
        if not data[key]:
            m = re.search(r"(?m)^.*?" + pattern, text, re.IGNORECASE)
            if m:
                data[key] = m.group(1).strip().rstrip('.,;')

    # 4. ENDEREÇO (Limpeza e Extração de Cidade)
    raw_address = ""
    m_end = re.search(r"(?m)^.*?(?:end[eê]re[cç]o|localiza[cç][aã]o)\s*[:;\-]?\s*(.+)", text, re.IGNORECASE)
    if m_end:
        raw_address = m_end.group(1).strip()
    else:
        tipos_logradouro = r"(?:R\.|Rua|Av\.|Av|Avenida|Estr\.|Estrada|Rod\.|Rodovia|Tv\.|Travessa|Al\.|Alameda|Praça|Pç\.)"
        m_street = re.search(r"(?m)^\s*(?:\d+\)\s*)?(" + tipos_logradouro + r"\s+.+)", text, re.IGNORECASE)
        if m_street:
            raw_address = m_street.group(1).strip()

    if raw_address:
        # Tenta pescar localidade (Cidade - SP) se estiver vazia
        if not data['localidade']:
            m_city = re.search(r"([A-Za-zÀ-ÿ\s]+)\s*[-/]\s*[A-Z]{2}\b", raw_address)
            if m_city:
                city_raw = m_city.group(1).strip()
                city_clean = re.sub(r"^[,.\-\s]+", "", city_raw)
                if "," in city_clean:
                    city_clean = city_clean.split(",")[-1].strip()
                data['localidade'] = city_clean

        # Corta endereço no número
        m_short_addr = re.match(r"^(.*?,\s*\d+)", raw_address)
        if m_short_addr:
            data['endereco'] = m_short_addr.group(1)
        else:
            data['endereco'] = raw_address

    # 5. TRONCO / CABO (TR#)
    m_tr = re.search(r"TR\s*#?\s*(\d+)", text, re.IGNORECASE)
    if m_tr:
        data['tronco'] = m_tr.group(1)
    elif not data['tronco']:
        m_tr_old = re.search(r"tronco\s*[:;\-]?\s*([0-9]+)", text, re.IGNORECASE)
        if m_tr_old: data['tronco'] = m_tr_old.group(1)

    data['supervisor'] = "Wellington"

    # 6. TÉCNICOS (Busca Global)
    exec_list = []
    text_lower = text.lower()
    nomes_encontrados = set()

    for nome_db, re_code in DB_TECNICOS.items():
        if re.search(r"\b" + re.escape(nome_db) + r"\b", text_lower):
            if nome_db not in nomes_encontrados:
                nomes_encontrados.add(nome_db)
                exec_list.append({'name': nome_db, 're': re_code})

    final_execs = []
    nomes_ordenados = sorted(list(nomes_encontrados), key=len, reverse=True)
    processados = set()
    for nome in nomes_ordenados:
        if any(nome in maior for maior in processados):
            continue
        processados.add(nome)
        final_execs.append({'name': nome, 're': DB_TECNICOS[nome]})

    data['executantes_parsed'] = final_execs

    # 7. TRATATIVAS (Extração Inicial e Limpeza)
    raw_materials = ""
    match_genesis = re.search(r"Ação de Recuperação:[\s\S]*?(?=\nMaterial|\nData|\Z)", text, re.IGNORECASE)
    match_manual = re.search(r"O QUE FOI FEITO.*:([\s\S]*?)(?=\n\d+\)|Material|\Z)", text, re.IGNORECASE)

    if match_genesis:
        raw_materials = re.sub(r"Ação de Recuperação:\s*", "", match_genesis.group(0), flags=re.IGNORECASE)
    elif match_manual:
        raw_materials = match_manual.group(1)
    else:
        # Fallback
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        temp_list = []
        for l in lines:
            if re.match(r'^\d+[\s\w]', l) or any(
                    x in l.lower() for x in ['fusão', 'fusões', 'cabo', 'otdr', 'caixa', 'ceo', 'fita', 'tubo']):
                if not re.match(r'^\d{2}/\d{2}/\d{4}', l) and "lat" not in l.lower():
                    temp_list.append(l)
        raw_materials = "\n".join(temp_list)

    if raw_materials:
        # Troca barras por ENTER
        raw_materials = raw_materials.replace('/', '\n')
        # Separa número grudado: "f.o01" -> "f.o\n01"
        raw_materials = re.sub(r"([a-zA-Zçãõéáíóú\.])(\d{2})", r"\1\n\2", raw_materials)
        material_lines = [l.strip() for l in raw_materials.splitlines() if l.strip()]
    else:
        material_lines = []

    return data, material_lines


def detect_launch(material_lines):
    """
    Detecta se é um lançamento de cabo para desenhar a linha.
    Retorna a metragem (int) ou None.
    """
    joined = " ".join(material_lines).lower()

    # REGRA DE SEGURANÇA: Se for "repuxado", NUNCA desenha linha (retorna None)
    if "repuxad" in joined:
        return None

    patterns = [
        # 1. Número seguido de unidade (m, mts, metros)
        r"(\d{1,4})\s*(?:m\b|mt|mts|metr[ao]s?)",
        # 2. Número seguido de LANÇADO
        r"(\d{1,4})\s*(?:lan[cç]ad[oa]|lan[cç]amento)",
        # 3. LANÇADO seguido de número
        r"(?:lan[cç]ad[oa]|lan[cç]amento)\s*(\d{1,4})"
    ]

    for p in patterns:
        m = re.search(p, joined)
        if m:
            return int(m.group(1))

    return None


def generate_pps(total_length, vt_each=15):
    usable = total_length - (2 * vt_each)
    if usable <= 0: return []
    num_spans = max(1, round(usable / 40))
    span_len = round(usable / num_spans)
    return [span_len] * num_spans


def dividir_tratativas(material_lines):
    divisiveis = ["fus", "fusão", "fusões", "fusao", "tubo", "loose"]
    especiais = ["ceo", "ptro", "abertura", "reabertura", "caixa"]
    p1, p2 = [], []

    itens = []
    for linha in material_lines:
        texto = linha.strip()
        low = texto.lower()
        m = re.match(r"(\d+)\s*[-xX]?\s*(.+)", low)
        if not m:
            itens.append({"qtd": 1, "nome": low, "orig": texto})
            continue
        itens.append({"qtd": int(m.group(1)), "nome": m.group(2).strip(), "orig": texto})

    especiais_unitarios = [i for i in itens if i["qtd"] == 1 and any(k in i["nome"] for k in especiais)]

    if len(especiais_unitarios) == 2:
        p1.append(especiais_unitarios[0]["orig"])
        p2.append(especiais_unitarios[1]["orig"])
        restantes = [i for i in itens if i not in especiais_unitarios]
    else:
        restantes = itens.copy()

    for item in restantes:
        qtd, nome, orig = item["qtd"], item["nome"], item["orig"]
        if any(f in nome for f in FILTRO_LANCAMENTO):
            p1.append(orig)
            continue
        if any(k in nome for k in especiais):
            if qtd == 1:
                p1.append(orig)
            else:
                metade = qtd // 2
                resto = qtd - metade
                if metade > 0: p1.append(f"{metade} {nome}")
                if resto > 0: p2.append(f"{resto} {nome}")
            continue
        if any(k in nome for k in divisiveis):
            metade = qtd // 2
            resto = qtd - metade
            if metade > 0: p1.append(f"{metade} {nome}")
            if resto > 0: p2.append(f"{resto} {nome}")
            continue
        p1.append(orig)
    return p1, p2


# ----------------------------
# Geração do PDF
# ----------------------------
def create_overlay(parsed, materials_raw, pp_list, overlay_path):
    if not os.path.exists(TEMPLATE_PDF):
        width_pt, height_pt = 595.27, 841.89
    else:
        tpl = PdfReader(TEMPLATE_PDF)
        page0 = tpl.pages[0]
        media = page0.MediaBox
        llx, lly, urx, ury = map(float, media)
        width_pt = urx - llx
        height_pt = ury - lly

    c = canvas.Canvas(str(overlay_path), pagesize=(width_pt, height_pt))

    def put_xy(key, text, size=9, manual_coords=None):
        if not text: return
        if manual_coords:
            xpct, ypct = manual_coords
        elif key in COORDS:
            xpct, ypct = COORDS[key]
        else:
            return
        x, y = pct_to_pt(xpct, ypct, width_pt, height_pt)
        c.setFont("Helvetica", size)
        lines = str(text).split('\n')
        for i, ln in enumerate(lines):
            c.drawString(x, y - (i * (size + 2)), ln)

    for key, val in parsed.items():
        if key not in ['executantes_parsed']:
            put_xy(key, val, size=9)

    execs = parsed.get('executantes_parsed', [])
    for i, item in enumerate(execs):
        if i >= EXEC_CONFIG['max_rows']: break
        current_y = EXEC_CONFIG['start_y'] - (i * EXEC_CONFIG['step_y'])
        put_xy(f"exec_{i}", item['name'].title(), size=9, manual_coords=(EXEC_CONFIG['name_x'], current_y))
        if item['re']:
            put_xy(f"re_{i}", item['re'], size=9, manual_coords=(EXEC_CONFIG['re_x'], current_y))

    mxp, myp = COORDS['materials_block']
    mx, my = pct_to_pt(mxp, myp, width_pt, height_pt)
    c.setFont('Helvetica', 8)
    for i, line in enumerate(materials_raw[:20]):
        c.drawString(mx, my - (i * 10), line)

    left_pct, bottom_pct, right_pct, top_pct = COORDS['croqui_rect']
    draw_y = height_pt * ((top_pct + bottom_pct) / 2)
    left_x = width_pt * (left_pct + 0.05)
    right_x = width_pt * (right_pct - 0.05)

    c.setLineWidth(2)
    c.setDash(4, 2)
    c.line(left_x, draw_y, right_x, draw_y)
    c.setDash([])

    if parsed.get('endereco'):
        addr = parsed['endereco']
        c.setFont('Helvetica-Bold', 10)
        tw = c.stringWidth(addr, 'Helvetica-Bold', 10)
        cx = (left_x + right_x) / 2
        c.drawString(cx - (tw / 2), draw_y - 100, addr)

    # ---------------------------------------------------------
    # Lógica de desenho: Lançamento vs Caixa Simples
    # ---------------------------------------------------------
    if len(pp_list) == 0:
        # --- DESENHO PADRÃO (CAIXA SIMPLES) ---
        total_width = right_x - left_x
        mid_x = left_x + total_width / 2

        # Ponto Início
        c.circle(left_x, draw_y, 4, fill=1)
        c.drawString(left_x - 12, draw_y - 20, "Início")

        # Ponto Meio (XC)
        c.circle(mid_x, draw_y, 4, fill=1)
        c.drawString(mid_x - 8, draw_y - 20, "XC")

        # Ponto Fim
        c.circle(right_x, draw_y, 4, fill=1)
        c.drawString(right_x - 8, draw_y - 20, "Fim")

        # Caixa de Texto
        box_width, offset = 220, 35
        box_height = 15 + 12 + (len(materials_raw) * 10)
        box_x = mid_x - (box_width / 2)
        box_y = draw_y + offset
        c.rect(box_x, box_y, box_width, box_height, fill=0)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(box_x + 5, box_y + box_height - 10, "Tratativas")
        c.setFont("Helvetica", 8)
        text_start_y = box_y + box_height - 12 - 8
        for i, item in enumerate(materials_raw):
            c.drawString(box_x + 5, text_start_y - (i * 10), item)

        # Seta
        c.line(mid_x, draw_y, mid_x, box_y)
        c.drawString(mid_x - 4, box_y - 10, "↑")

    else:
        # --- DESENHO DE LANÇAMENTO (Bolinhas e Vãos) ---

        # 1. Desenha as caixas de material (E1 e E2)
        p1_list, p2_list = dividir_tratativas(materials_raw)
        offset, box_width = 30, 180

        # Box Esquerda (E1)
        h1 = 15 + 12 + (len(p1_list) * 10)
        bx1, by1 = left_x - 20, draw_y + offset
        c.rect(bx1, by1, box_width, h1, fill=0)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(bx1 + 5, by1 + h1 - 10, "Tratativas E1")
        c.setFont("Helvetica", 8)
        tsy1 = by1 + h1 - 20
        for i, item in enumerate(p1_list):
            c.drawString(bx1 + 5, tsy1 - (i * 10), item)
        c.line(left_x, draw_y, bx1 + box_width / 2, by1)

        # Box Direita (E2)
        h2 = 15 + 12 + (len(p2_list) * 10)
        bx2, by2 = right_x - box_width + 20, draw_y + offset
        c.rect(bx2, by2, box_width, h2, fill=0)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(bx2 + 5, by2 + h2 - 10, "Tratativas E2")
        c.setFont("Helvetica", 8)
        tsy2 = by2 + h2 - 20
        for i, item in enumerate(p2_list):
            c.drawString(bx2 + 5, tsy2 - (i * 10), item)
        c.line(right_x, draw_y, bx2 + box_width / 2, by2)

        # 2. Desenha a Linha de Postes (Pontos)
        total_width = right_x - left_x
        step = total_width / len(pp_list)
        cur_x = left_x

        # --- PONTO INICIAL ---
        c.circle(cur_x, draw_y, 4, fill=1)
        c.drawString(cur_x - 10, draw_y + 15, "VT 15m")  # CORRIGIDO: Desenha VT no início
        c.drawString(cur_x - 10, draw_y - 20, "XC Inicial")  # CORRIGIDO: Desenha label XC Inicial

        # --- PONTOS INTERMEDIÁRIOS E FINAL ---
        for i, dist in enumerate(pp_list):
            nxt_x = cur_x + step
            mid = (cur_x + nxt_x) / 2

            # Label do vão (PP Xm)
            if dist > 0:
                c.drawString(mid - 15, draw_y + 5, f"PP {dist}m")

            c.circle(nxt_x, draw_y, 4, fill=1)

            # Verifica se é o último ponto
            if i == len(pp_list) - 1:
                # É o final
                c.drawString(nxt_x - 10, draw_y - 20, "XC Final")
                c.drawString(nxt_x - 10, draw_y + 15, "VT 15m")  # CORRIGIDO: Desenha VT no final
            else:
                # É um poste do meio
                c.drawString(nxt_x - 8, draw_y - 20, "XC")

            cur_x = nxt_x

    c.showPage()
    c.save()


def merge_overlay(overlay_path, out_path):
    if not os.path.exists(TEMPLATE_PDF):
        os.replace(overlay_path, out_path)
        return
    overlay = PdfReader(str(overlay_path))
    template = PdfReader(TEMPLATE_PDF)
    if len(template.pages) > 0 and len(overlay.pages) > 0:
        merger = PageMerge(template.pages[0])
        merger.add(overlay.pages[0]).render()
    PdfWriter(str(out_path), trailer=template).write()


# ----------------------------
# TELAS HTML (TEMPLATES)
# ----------------------------

PASTE_HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Colar Relatório</title>
<style>
body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background:#f0f2f5; padding:40px; text-align:center; }
.container { max-width:700px; margin:auto; background:#fff; padding:40px; border-radius:12px; box-shadow:0 4px 12px rgba(0,0,0,0.1); }
textarea { width:100%; height:300px; padding:15px; margin-bottom:20px; border:2px solid #ddd; border-radius:8px; font-size:14px; font-family:monospace; resize:vertical; background-color: #fafafa; }
textarea:focus { border-color: #007bff; outline:none; background-color: #fff; }
button { padding:15px 30px; font-size:18px; background:#007bff; color:#fff; border:none; border-radius:6px; cursor:pointer; transition:0.2s; font-weight:bold; }
button:hover { background:#0056b3; }
h2 { color:#333; margin-bottom:10px; }
.manual-link { display:block; margin-top:20px; color:#666; text-decoration:none; font-size:14px; }
.manual-link:hover { text-decoration:underline; color:#007bff; }
.info { color: #666; font-size: 14px; margin-bottom: 25px; }
</style>
</head>
<body>
<div class="container">
    <h2>Gerador de Croquis Automático</h2>
    <p class="info">Cole abaixo o texto do WhatsApp ou do Sistema <strong>GENESIS</strong>.</p>
    <form method="post" action="/preencher">
        <textarea name="raw_text" placeholder="Cole aqui seu encerramento..."></textarea>
        <br>
        <button type="submit">Processar Texto &raquo;</button>
    </form>
    <a href="/form" class="manual-link">Preencher manualmente (Formulário em branco)</a>
</div>
</body>
</html>
"""

FORM_HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Confirmar Dados</title>
<style>
body { font-family: 'Segoe UI', sans-serif; background:#f0f2f5; padding:20px }
.container { max-width:900px; margin:auto; background:#fff; padding:30px; border-radius:10px; box-shadow:0 2px 10px rgba(0,0,0,0.05); }
input, textarea { width:100%; padding:10px; margin-bottom:15px; border:1px solid #ccc; border-radius:5px; font-size:14px; box-sizing: border-box; }
textarea { height:150px; font-family:monospace; line-height: 1.4; }
button { padding:12px 25px; font-size:16px; background:#28a745; color:#fff; border:none; border-radius:5px; cursor:pointer; font-weight:bold; }
button:hover { background:#218838; }
h3 { margin-top:25px; border-bottom: 2px solid #eee; padding-bottom: 10px; color: #444; }
label { font-weight: 600; font-size: 13px; color: #555; display:block; margin-bottom: 5px; }
.tag { display: inline-block; background: #e9ecef; color: #333; padding: 6px 12px; border-radius: 20px; margin: 4px; font-size: 14px; border: 1px solid #ddd; }
.tag span { margin-left: 8px; cursor: pointer; color: #dc3545; font-weight: bold; }
.tag span:hover { color: #bd2130; }
#exec-list { max-height: 150px; overflow-y: auto; border: 1px solid #eee; border-radius: 4px; margin-bottom: 10px; }
#exec-list div:hover { background: #f8f9fa; color: #007bff; }
.back-btn { background: #6c757d; margin-right: 10px; text-decoration:none; display:inline-block; color:white; padding:12px 25px; border-radius:5px; text-align:center;}
.back-btn:hover { background: #5a6268; }
</style>
</head>

<script>
document.addEventListener('DOMContentLoaded', () => {

  let tecnicos = [];
  let selecionados = {{ executantes_list | tojson }};

  fetch('/tecnicos')
    .then(r => r.json())
    .then(d => tecnicos = d);

  const input = document.getElementById('exec-input');
  const list = document.getElementById('exec-list');
  const hidden = document.getElementById('exec-hidden');
  const tagsBox = document.getElementById('exec-tags');

  function atualizarHidden() {
    hidden.value = selecionados.join(', ');
  }

  function renderTags() {
    tagsBox.innerHTML = '';
    selecionados.forEach(nome => {
      const tag = document.createElement('div');
      tag.className = 'tag';
      tag.innerHTML = `${nome} <span>&times;</span>`;
      tag.querySelector('span').onclick = () => {
        selecionados = selecionados.filter(n => n !== nome);
        atualizarHidden();
        renderTags();
      };
      tagsBox.appendChild(tag);
    });
  }

  renderTags();
  atualizarHidden();

  input.addEventListener('input', () => {
    const v = input.value.toLowerCase();
    list.innerHTML = '';
    if (!v) return;

    tecnicos
      .filter(t => t.includes(v) && !selecionados.includes(t))
      .slice(0, 8)
      .forEach(t => {
        const div = document.createElement('div');
        div.textContent = t;
        div.style.cursor = 'pointer';
        div.style.padding = '8px';
        div.style.borderBottom = '1px solid #f0f0f0';

        div.onclick = () => {
          selecionados.push(t);
          atualizarHidden();
          renderTags();
          input.value = '';
          list.innerHTML = '';
        };
        list.appendChild(div);
      });
  });
});
</script>

<body>
<div class="container">
<form method="post" action="/generate" target="_blank">

<h3>Dados Principais</h3>
<div style="display:grid; grid-template-columns: 1fr 1fr; gap:15px;">
    <div><label>TA</label><input name="ta" value="{{ data.get('ta','') }}"></div>
    <div><label>Código Obra (SGM)</label><input name="codigo_obra" value="{{ data.get('codigo_obra','') }}"></div>
</div>

<label>Causa</label>
<input name="causa" value="{{ data.get('causa','') }}">

<label>Endereço / Localização</label>
<input name="endereco" value="{{ data.get('endereco','') }}">

<div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:15px;">
    <div><label>Localidade</label><input name="localidade" value="{{ data.get('localidade','') }}"></div>
    <div><label>ES</label><input name="es" value="{{ data.get('es','') }}"></div>
    <div><label>AT</label><input name="at" value="{{ data.get('at','') }}"></div>
</div>

<div style="display:grid; grid-template-columns: 1fr 1fr; gap:15px;">
    <div><label>Tronco</label><input name="tronco" value="{{ data.get('tronco','') }}"></div>
    <div><label>Veículo</label><input name="veiculo" value="{{ data.get('veiculo','') }}"></div>
</div>

<div style="display:grid; grid-template-columns: 1fr 1fr; gap:15px;">
    <div><label>Supervisor</label><input name="supervisor" value="{{ data.get('supervisor','Wellington') }}"></div>
    <div><label>Data</label><input name="data" value="{{ data.get('data','') }}"></div>
</div>

<h3>Executantes</h3>
<div id="exec-tags" style="margin-bottom:10px;"></div>
<input id="exec-input" placeholder="Digite o nome para adicionar mais (ex: Marcos)...">
<div id="exec-list"></div>
<input type="hidden" name="executantes" id="exec-hidden">

<h3>Tratativas (Itens)</h3>
<textarea name="itens">{{ itens_texto }}</textarea>

<div style="margin-top:30px; border-top: 1px solid #eee; padding-top: 20px;">
    <a href="/" class="back-btn">&laquo; Colar Outro</a>
    <button type="submit">Gerar PDF Final</button>
</div>

</form>
</div>
</body>
</html>
"""


# ----------------------------
# ROTAS FLASK
# ----------------------------

@app.route('/')
def index():
    return render_template_string(PASTE_HTML)


@app.route('/form')
def form_vazio():
    return render_template_string(FORM_HTML, data={}, itens_texto="", executantes_list=[])


@app.route('/preencher', methods=['POST'])
def preencher():
    raw_text = request.form.get('raw_text', '')
    parsed_data, material_lines = extract_fields(raw_text)

    # Prepara lista simples de nomes para o Front-end
    exec_names = [e['name'].title() for e in parsed_data.get('executantes_parsed', [])]

    itens_texto = "\n".join(material_lines)

    return render_template_string(FORM_HTML,
                                  data=parsed_data,
                                  itens_texto=itens_texto,
                                  executantes_list=exec_names)


@app.route('/tecnicos')
def tecnicos():
    return list(DB_TECNICOS.keys())


@app.route('/view/<filename>')
def view_pdf(filename):
    return redirect(url_for('outputs', filename=filename))


@app.route('/outputs/<path:filename>')
def outputs(filename):
    return send_from_directory(OUTPUT_DIR, filename)


@app.route('/generate', methods=['POST'])
def generate():
    # -----------------------------------------------------
    # GERAÇÃO DO PDF - CONFIA NO FORMULÁRIO EDITADO
    # -----------------------------------------------------

    # 1. Pega os campos simples diretamente do formulário
    execs_string = request.form.get('executantes', '')
    exec_list = []
    if execs_string:
        for nome in execs_string.split(','):
            clean = nome.strip().lower()
            if clean in DB_TECNICOS:
                exec_list.append({'name': clean, 're': DB_TECNICOS[clean]})
            else:
                exec_list.append({'name': clean, 're': ''})

    parsed = {
        'ta': request.form.get('ta', ''),
        'codigo_obra': request.form.get('codigo_obra', ''),
        'causa': request.form.get('causa', ''),
        'endereco': request.form.get('endereco', ''),
        'localidade': request.form.get('localidade', ''),
        'es': request.form.get('es', ''),
        'at': request.form.get('at', ''),
        'tronco': request.form.get('tronco', ''),
        'veiculo': request.form.get('veiculo', ''),
        'data': request.form.get('data', ''),
        'supervisor': request.form.get('supervisor', ''),
        'executantes_parsed': exec_list
    }

    # 2. Pega as tratativas editadas
    itens_raw = request.form.get('itens', '')
    material_lines = [l.strip() for l in itens_raw.splitlines() if l.strip()]

    # 3. Detecta lançamento baseado no texto ATUAL
    total_len = detect_launch(material_lines)

    # Se detectou metragem > 0 e NÃO é repuxado, gera lista de pontos
    pp_list = generate_pps(total_len) if total_len else []

    # 4. Gera PDF
    codigo = parsed.get('ta') or f"doc_{random.randint(1000, 9999)}"
    codigo = re.sub(r'[^\w\-]', '', codigo)

    overlay_path = OUTPUT_DIR / f"{codigo}_overlay.pdf"
    out_pdf = OUTPUT_DIR / f"{codigo}.pdf"

    create_overlay(parsed, material_lines, pp_list, overlay_path)
    merge_overlay(overlay_path, out_pdf)

    return redirect(url_for('view_pdf', filename=out_pdf.name))


if __name__ == '__main__':
    if not os.path.exists(TEMPLATE_PDF):
        c = canvas.Canvas(TEMPLATE_PDF)
        c.drawString(100, 700, "TEMPLATE AUSENTE - COLOQUE O ARQUIVO 'CROQUI.pdf'")
        c.save()
        print(f"AVISO: {TEMPLATE_PDF} criado temporariamente.")

    app.run(debug=True, port=5000)