import base64
from pathlib import Path
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db
import tkinter as tk
from tkinter import filedialog

# ==========================================
# 1. CONECTAR AO FIREBASE
# ==========================================
FIREBASE_DB_URL = 'https://geradorcroqui-default-rtdb.firebaseio.com/'

try:
    cred = credentials.Certificate("firebase-key.json")
    firebase_admin.initialize_app(cred, {
        'databaseURL': FIREBASE_DB_URL
    })
    print("✅ Conectado ao Firebase!")
except Exception as e:
    print(f"❌ Erro ao conectar: {e}")
    exit()

# ==========================================
# 2. JANELA PARA SELECIONAR A PASTA
# ==========================================
print("Aguardando seleção da pasta...")

# Inicia o Tkinter invisível (só para puxar a janela de seleção)
root = tk.Tk()
root.withdraw()
root.attributes('-topmost', True)  # Força a janela a aparecer na frente do PyCharm

# Abre a janela para você navegar no PC e escolher a pasta
caminho_pasta = filedialog.askdirectory(title="Selecione a pasta onde estão os seus PDFs antigos")

# Se você fechar a janela sem selecionar nada, ele cancela
if not caminho_pasta:
    print("❌ Nenhuma pasta foi selecionada. Cancelando a migração.")
    exit()

pasta = Path(caminho_pasta)
print(f"📂 Pasta selecionada: {pasta}")

# ==========================================
# 3. LER A NUVEM E INJETAR
# ==========================================
ref_croquis = db.reference('/croquis')
croquis_nuvem = ref_croquis.get() or {}

migrados = 0
ignorados = 0

print("🚀 Iniciando varredura...")

# Procura todos os PDFs dentro da pasta que você escolheu
for arquivo in pasta.glob('*.pdf'):
    if '_overlay' in arquivo.name:
        continue

    ta = arquivo.stem  # Pega o nome do arquivo sem o ".pdf"

    if ta not in croquis_nuvem:
        print(f"📤 Injetando TA {ta} na nuvem...")

        # Lê o PDF e converte para texto Base64
        with open(arquivo, 'rb') as f:
            b64_str = base64.b64encode(f.read()).decode('utf-8')

        # Estrutura para o painel reconhecer o arquivo antigo
        dados_legados = {
            'parsed': {
                'ta': ta,
                'codigo_obra': 'MIGRADO',
                'endereco': 'Arquivo Antigo Local',
                'localidade': 'PC',
                'or_ot': ''
            },
            'itens_raw': '',
            'pdf_legado': b64_str
        }

        # Salva lá no Firebase
        db.reference(f'/croquis/{ta}').set(dados_legados)
        migrados += 1
    else:
        ignorados += 1

print("\n=================================")
print("🚀 MIGRAÇÃO CONCLUÍDA COM SUCESSO!")
print(f"✅ Arquivos enviados: {migrados}")
print(f"⏭️ Arquivos ignorados (já existiam): {ignorados}")
print("=================================")