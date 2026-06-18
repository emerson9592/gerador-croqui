import asyncio
import os
import re
from playwright.async_api import async_playwright


# =======================================================
# FUNÇÃO 1: BUSCAR DADOS DA TA (A que trabalha no dia a dia)
# =======================================================
async def buscar_dados_ta_sigitm(ta_number):
    """
    Abre o navegador usando a sessão salva, foca na aba correta,
    busca a TA, acessa as abas Hist. e Proced. e extrai o texto bruto.
    """
    async with async_playwright() as p:
        # headless=True faz o robô rodar em segundo plano
        browser = await p.chromium.launch(headless=True)

        try:
            # 1. Carrega a sessão forçando tamanho de tela e "disfarce" de usuário real
            context = await browser.new_context(
                storage_state="sessao_sigitm.json",
                viewport={'width': 1920, 'height': 1080},  # Força uma tela Full HD
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await context.new_page()

            print("🌐 Acessando o SIGITM com a sessão salva...")
            await page.goto("https://sigitm.vivo.com.br/app/app.jsp")

            # Espera 4 segundos para o sistema processar e abrir a nova aba sozinho
            await page.wait_for_timeout(4000)

            # --- O TRUQUE DAS ABAS ---
            print("🗂️ Verificando abas abertas e mudando o foco...")
            todas_as_abas = context.pages  # Pega a lista de todas as abas
            page = todas_as_abas[-1]  # Atualiza o robô para olhar para a ÚLTIMA aba
            await page.bring_to_front()  # Traz a aba certa para a frente
            print("✅ Sistema focado na aba correta!")

            # 2. Navegação no Menu Lateral (Árvore)
            print("➡️ Aguardando o menu de árvore carregar...")
            menu_anormalidade = page.get_by_text("Tíquete de anormalidade")
            await menu_anormalidade.wait_for(state="visible", timeout=20000)

            print("➡️ Clicando no item 'Tíquete de anormalidade' para expandir o menu...")
            await menu_anormalidade.click()

            print("➡️ Aguardando o sub-menu 'Localizar' ficar visível...")
            localizar_item = page.get_by_text("Localizar", exact=True)
            await localizar_item.wait_for(state="visible", timeout=15000)

            print("➡️ Clicando em 'Localizar'...")
            await localizar_item.click()

            # Pausa rápida para a área central de pesquisa terminar de desenhar na tela
            await page.wait_for_timeout(2000)

            # 3. Busca da TA
            print("➡️ Aguardando a tela de pesquisa carregar...")
            # Primeiro garantimos que o formulário visualmente carregou na tela
            await page.get_by_text("Número do tíquete:").wait_for(state="visible", timeout=15000)

            print(f"🔍 Digitando a TA: {ta_number}")
            # A MÁGICA AQUI: O ':visible' obriga o robô a ignorar os inputs escondidos do sistema
            await page.locator("input.x-form-text:visible").first.fill(ta_number)

            await page.keyboard.press("Enter")

            print("⏳ Aguardando a tela da TA carregar...")
            await page.wait_for_timeout(4000)  # Tempo para processar e abrir a TA

            # 4. Extração na aba Histórico
            print("➡️ Acessando a aba 'Hist.'...")
            await page.locator("text='Hist.'").click()
            await page.wait_for_timeout(2500)  # Espera a tabela atualizar

            print("📥 Extraindo texto do Histórico...")
            texto_historico = await page.locator("body").inner_text()

            # 5. Extração na aba Procedimentos
            print("➡️ Acessando a aba 'Proced.'...")
            await page.locator("text='Proced.'").click()
            await page.wait_for_timeout(2500)  # Espera a tabela de procedimentos carregar

            print("📥 Extraindo texto dos Procedimentos...")
            texto_procedimentos = await page.locator("body").inner_text()

            # 6. Juntando as informações brutas
            texto_bruto_completo = (
                    "--- ABA HISTÓRICO ---\n\n" +
                    texto_historico +
                    "\n\n--- ABA PROCEDIMENTOS ---\n\n" +
                    texto_procedimentos
            )

            print("\n✅ EXTRAÇÃO CONCLUÍDA!")
            return texto_bruto_completo

        except Exception as e:
            print(f"❌ Erro na automação de busca: {e}")
            return None
        finally:
            print("Fechando navegador de busca...\n")
            await browser.close()


# =======================================================
# FUNÇÃO 2: RENOVAR SESSÃO COM CAPTCHA (A que te salva no Admin)
# =======================================================
async def gerar_sessao_interativa(usuario, senha):
    """ Robô que interage com o usuário para resolver o Captcha """
    # Limpa arquivos de tentativas anteriores
    for f in ['static/captcha.png', 'static/captcha_answer.txt', 'static/login_status.txt']:
        if os.path.exists(f): os.remove(f)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            # Simulamos um monitor Full HD para o form de login aparecer normal
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await context.new_page()

            print("🌐 Acessando página de login...")
            await page.goto("https://sigitm.vivo.com.br/")
            await page.wait_for_load_state("networkidle")

            print("🔑 Preenchendo credenciais...")
            await page.locator('input[type="text"]').first.fill(usuario)
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
            while not os.path.exists("static/captcha_answer.txt"):
                await asyncio.sleep(1)
                tempo_espera += 1
                if tempo_espera > 120:
                    with open('static/login_status.txt', 'w') as f: f.write("TIMEOUT")
                    return False

            print("✅ Resposta recebida! Finalizando login...")
            with open("static/captcha_answer.txt", "r") as f:
                resposta = f.read().strip()

            # --- A CORREÇÃO: Apaga a imagem para o site não te pedir de novo! ---
            try:
                if os.path.exists("static/captcha.png"):
                    os.remove("static/captcha.png")
                if os.path.exists("static/captcha_answer.txt"):
                    os.remove("static/captcha_answer.txt")
            except Exception:
                pass
            # --------------------------------------------------------------------

            input_captcha = page.get_by_placeholder(re.compile(r"código", re.IGNORECASE))
            if await input_captcha.count() > 0:
                await input_captcha.fill(resposta)
            else:
                await page.locator('input[type="text"]').last.fill(resposta)

            await page.keyboard.press("Enter")
            print("⏳ Aguardando autenticação (15s para garantir cookies)...")
            await page.wait_for_timeout(15000)

            # Verifica se deu erro (se a página ainda é a de login ou se o campo de senha continua lá)
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