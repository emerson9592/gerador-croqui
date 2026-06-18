import asyncio
import os
import re
from playwright.async_api import async_playwright


def limpar_texto_gwt(texto_bruto):
    """ Filtra a maçaroca do GWT e extrai apenas o texto legível """
    textos = re.findall(r'"(.*?)"', texto_bruto)
    texto_limpo = []

    # Palavras que só devem ser ignoradas se forem EXATAMENTE iguais
    # (Evita apagar o histórico inteiro só porque tem a palavra "Data" no meio)
    colunas_grid = [
        'Código', 'Data', 'Grupo', 'Usuário', 'Armário',
        'Cód. Localidade', 'Sigla Localidade', 'Nome Localidade',
        'Cód. Área', 'Nome Área', 'sortField', 'sortDir', 'sfm'
    ]

    # Substrings que se aparecerem em qualquer lugar da string, nós ignoramos
    lixo_sistema = [
        'com.telefonica', 'com.extjs', 'java.lang',
        'TBL_', 'net.customware', 'LISTA_'
    ]

    for t in textos:
        texto_aparado = t.strip()

        # 1. Se for exatamente o nome de uma coluna solta, ignora
        if texto_aparado in colunas_grid:
            continue

        # 2. Se contiver código de sistema escondido no meio, ignora
        if any(x in t for x in lixo_sistema):
            continue

        # 3. Se passou pelos filtros, é texto humano de verdade!
        if len(texto_aparado) > 2:
            # Converte os escapes de quebra de linha que vêm da API
            t = t.replace('\\n', '\n').replace('\\r', '')
            texto_limpo.append(t)

    return "\n\n".join(texto_limpo)


# =======================================================
# FUNÇÃO 1: BUSCAR DADOS DA TA (API TURBO)
# =======================================================
async def buscar_dados_ta_sigitm(ta_number):
    """
    Bate direto na API do SIGITM usando pacotes GWT RPC.
    """
    async with async_playwright() as p:
        request_context = await p.request.new_context(
            storage_state="sessao_sigitm.json"
        )

        print(f"⚡ Disparando requisições API para a TA: {ta_number}...")

        url_rpc = "https://sigitm.vivo.com.br/app/modules/Sigitm/command.rpc"

        headers = {
            "Content-Type": "text/x-gwt-rpc; charset=utf-8",
            "X-GWT-Permutation": "ED03BE33C7AAC86185E1D08DD3FAB578",
            "X-GWT-Module-Base": "https://sigitm.vivo.com.br/app/modules/Sigitm/"
        }

        # 1. NOVO PACOTE: A Capa da TA (Endereço, Localidade, Causa, etc.)
        payload_capa = f"7|0|7|https://sigitm.vivo.com.br/app/modules/Sigitm/|ED03BE33C7AAC86185E1D08DD3FAB578|com.telefonica.fsr.command.client.CommandService|execute|net.customware.gwt.dispatch.shared.Action|com.telefonica.sigitm.gxt.ta.shared.command.GetAR/2509891078|java.lang.Integer/3438268394|1|2|3|4|1|5|6|7|{ta_number}|0|"

        # 2. Histórico
        payload_historico = f"7|0|7|https://sigitm.vivo.com.br/app/modules/Sigitm/|ED03BE33C7AAC86185E1D08DD3FAB578|com.telefonica.fsr.command.client.CommandService|execute|net.customware.gwt.dispatch.shared.Action|com.telefonica.sigitm.gxt.ta.shared.command.ListarHistoricosTaAction/740817333|java.lang.Integer/3438268394|1|2|3|4|1|5|6|7|{ta_number}|"

        # 3. Procedimentos
        payload_procedimento = f"7|0|30|https://sigitm.vivo.com.br/app/modules/Sigitm/|ED03BE33C7AAC86185E1D08DD3FAB578|com.telefonica.fsr.command.client.CommandService|execute|net.customware.gwt.dispatch.shared.Action|com.telefonica.sigitm.gxt.widget.shared.command.GridAR/4194059826|com.telefonica.sigitm.gxt.widget.shared.sfm.SfmLoadConfig/3569800714|com.extjs.gxt.ui.client.data.RpcMap/3441186752|sortField|sortDir|com.extjs.gxt.ui.client.Style$SortDir/3873584144|sfm|com.telefonica.sigitm.gxt.widget.shared.sfm.SelectForMapping/585997930|java.util.ArrayList/4159755760|com.telefonica.sigitm.gxt.widget.shared.sfm.Column/1420698442|Código|TBL_PROCEDIMENTOS_TA#PCA_CODIGO|Data|TBL_PROCEDIMENTOS_TA#PCA_DATA|Grupo|TBL_PROCEDIMENTOS_TA#PCA_GRUPO#GRP_NOME|Usuário|TBL_PROCEDIMENTOS_TA#PCA_USUARIO#USR_NOME|TBL_PROCEDIMENTOS_TA|LISTA_PROCEDIMENTOS_TA|com.telefonica.sigitm.gxt.widget.shared.sfm.OrderBy/1959731157|com.telefonica.sigitm.gxt.widget.shared.sfm.Where/2540186203|TBL_PROCEDIMENTOS_TA#PCA_TA#TQA_CODIGO|TBL_TA#TQA_CODIGO|java.lang.Integer/3438268394|1|2|3|4|1|5|6|7|0|1|8|3|9|0|10|11|0|12|13|14|4|15|16|17|0|50|15|18|19|0|100|15|20|21|0|100|15|22|23|0|100|24|14|0|14|0|25|14|1|26|1|19|-1|14|0|14|1|27|28|29|30|{ta_number}|0|"

        try:
            print("📤 Pedindo Capa da TA (Dados Principais)...")
            resp_capa = await request_context.post(url_rpc, data=payload_capa, headers=headers)
            texto_capa_limpo = limpar_texto_gwt(await resp_capa.text())

            print("📤 Pedindo Histórico...")
            resp_hist = await request_context.post(url_rpc, data=payload_historico, headers=headers)
            texto_hist_limpo = limpar_texto_gwt(await resp_hist.text())

            print("📤 Pedindo Procedimentos...")
            resp_proced = await request_context.post(url_rpc, data=payload_procedimento, headers=headers)
            texto_proced_limpo = limpar_texto_gwt(await resp_proced.text())

            # Montagem final recriando o layout que o seu sistema já sabe ler
            texto_final = (
                f"--- DADOS DA CAPA ---\n\n"
                f"{texto_capa_limpo}\n\n"
                "--------------------------------------------------\n\n"
                f"--- HISTÓRICO DA TA: {ta_number} ---\n\n"
                f"{texto_hist_limpo}\n\n"
                "--------------------------------------------------\n\n"
                f"--- PROCEDIMENTOS DA TA: {ta_number} ---\n\n"
                f"{texto_proced_limpo}"
            )

            print("\n✅ EXTRAÇÃO API CONCLUÍDA E LIMPA!")
            return texto_final

        except Exception as e:
            print(f"❌ Erro na requisição API: {e}")
            return None
        finally:
            await request_context.dispose()

# =======================================================
# FUNÇÃO 2: RENOVAR SESSÃO COM CAPTCHA (A que te salva no Admin)
# =======================================================
async def gerar_sessao_interativa(usuario, senha):
    """ Robô que interage com o usuário para resolver o Captcha """
    for f in ['static/captcha.png', 'static/captcha_answer.txt', 'static/login_status.txt']:
        if os.path.exists(f): os.remove(f)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--single-process'
            ]
        )
        try:
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await context.new_page()

            print("🌐 Acessando página de login...")
            await page.goto("https://sigitm.vivo.com.br/", wait_until="networkidle")

            print("🔑 Preenchendo credenciais...")
            input_user = page.locator('input[type="text"]').first
            await input_user.wait_for(state="visible", timeout=10000)
            await input_user.fill(usuario)

            await page.locator('input[type="password"]').first.fill(senha)

            print("📸 Tirando print da área de Login...")
            os.makedirs('static', exist_ok=True)

            try:
                login_box = page.locator('form').first
                if await login_box.count() > 0:
                    await login_box.screenshot(path="static/captcha.png")
                else:
                    await page.screenshot(path="static/captcha.png")
            except Exception as e:
                print(f"Aviso ao tirar print: {e}")
                await page.screenshot(path="static/captcha.png")

            print("⏳ Aguardando você resolver o Captcha pelo site...")
            tempo_espera = 0
            # Reduzido para 85 segundos para evitar estourar o limite de timeout HTTP do gateway do Render
            while not os.path.exists("static/captcha_answer.txt"):
                await asyncio.sleep(1)
                tempo_espera += 1
                if tempo_espera > 85:
                    with open('static/login_status.txt', 'w') as f: f.write("TIMEOUT")
                    return False

            print("✅ Resposta recebida! Finalizando login...")
            with open("static/captcha_answer.txt", "r") as f:
                resposta = f.read().strip()

            try:
                if os.path.exists("static/captcha.png"):
                    os.remove("static/captcha.png")
                if os.path.exists("static/captcha_answer.txt"):
                    os.remove("static/captcha_answer.txt")
            except Exception:
                pass

            input_captcha = page.get_by_placeholder(re.compile(r"código", re.IGNORECASE))
            if await input_captcha.count() > 0:
                await input_captcha.fill(resposta)
            else:
                await page.locator('input[type="text"]').last.fill(resposta)

            await page.keyboard.press("Enter")
            print("⏳ Aguardando autenticação...")

            # Em vez de travar 15 segundos fixos, aguardamos que o campo de senha desapareça (sucesso)
            try:
                await page.locator('input[type="password"]').wait_for(state="hidden", timeout=15000)
            except Exception:
                # Caso o sistema esteja lento ou ocorra erro, prossegue para a validação abaixo
                pass

            if "login" in page.url.lower() or await page.locator('input[type="password"]').is_visible():
                with open('static/login_status.txt', 'w') as f: f.write("FALHA_SENHA_OU_CAPTCHA")
                return False

            print("💾 Sessão validada! Salvando JSON...")
            await context.storage_state(path="sessao_sigitm.json")
            with open('static/login_status.txt', 'w') as f:
                f.write("SUCESSO")
            return True

        except Exception as e:
            print(f"❌ Erro no robô de login: {e}")
            with open('static/login_status.txt', 'w') as f:
                f.write(f"ERRO")
            return False
        finally:
            await browser.close()