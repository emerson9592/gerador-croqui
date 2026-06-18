import base64
import os
from pathlib import Path
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db
import tkinter as tk
from tkinter import filedialog

# ==========================================
# 1. CONFIGURAR O NOVO BANCO
# ==========================================
# ⚠️ ADICIONE A URL DO SEU NOVO BANCO AQUI:
NOVA_FIREBASE_URL = 'https://gerador-de-croqui-97b2f-default-rtdb.firebaseio.com/'

try:
    cred = credentials.Certificate("firebase-key.json")
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'databaseURL': NOVA_FIREBASE_URL})
    print("✅ Conectado ao NOVO Firebase com sucesso!")
except Exception as e:
    print(f"❌ Erro ao conectar: {e}")
    exit()

# ==========================================
# 2. SELECIONAR A PASTA DOS PDFS
# ==========================================
print("Aguardando a seleção da pasta de PDFs no seu computador...")
root = tk.Tk()
root.withdraw()
root.attributes('-topmost', True)

caminho_pasta = filedialog.askdirectory(title="Selecione a pasta onde estão os PDFs para a nova nuvem")

if not caminho_pasta:
    print("❌ Nenhuma pasta selecionada. Processo cancelado.")
    exit()

pasta = Path(caminho_pasta)
arquivos_pdf = list(pasta.glob('*.pdf'))
total = len(arquivos_pdf)

migrados = 0
erros = 0

print(f"\n🚀 Iniciando migração limpa de {total} arquivos para o novo banco...\n")

# ==========================================
# 3. TRANSFERÊNCIA ESTRUTURADA
# ==========================================
for i, arquivo in enumerate(arquivos_pdf, 1):
    if '_overlay' in arquivo.name:
        continue

    ta = arquivo.stem
    tamanho_mb = os.path.getsize(arquivo) / (1024 * 1024)

    # Proteção para arquivos gigantescos
    if tamanho_mb > 5.0:
        print(f"[{i}/{total}] ⚠️ TA {ta} pulada (Muito pesada: {tamanho_mb:.1f}MB)")
        erros += 1
        continue

    print(f"[{i}/{total}] 📤 Enviando TA {ta} ({tamanho_mb:.1f}MB)...", end=" ", flush=True)

    try:
        with open(arquivo, 'rb') as f:
            b64_str = base64.b64encode(f.read()).decode('utf-8')

        # 1. Registro leve (Para o site abrir instantaneamente)
        dados_leves = {
            'parsed': {
                'ta': ta,
                'codigo_obra': 'MIGRADO',
                'endereco': 'Arquivo Antigo Local',
                'localidade': 'PC',
                'or_ot': '',
                'qtd_anexos': 0
            },
            'itens_raw': ''
        }
        db.reference(f'/croquis/{ta}').set(dados_leves)

        # 2. Registro pesado isolado (SÓ abre quando você clicar no botão de gerar)
        db.reference(f'/pdfs_pesados/{ta}/pdf_legado').set(b64_str)

        print("✅ Enviado com segurança!")
        migrados += 1

    except Exception as e:
        print(f"❌ ERRO: {e}")
        erros += 1

print("\n=================================")
print("🎯 NOVA NUVEM CRIADA COM SUCESSO!")
print(f"✅ Arquivos processados e protegidos: {migrados}")
print(f"⚠️ Arquivos com erro ou pesados: {erros}")
print("=================================")