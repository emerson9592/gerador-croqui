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
        # Otimização crucial para servidores Cloud (Render): limita o uso de RAM e CPU
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',  # Evita falhas por falta de memória partilhada
                '--disable-gpu',
                '--single-process'  # Reduz a criação de múltiplos processos do Chromium
            ]
        )

        try:
            # 1. Carrega a sessão forçando tamanho de ecrã e "disfarce" de utilizador real
            context = await browser.new_context(
                storage_state="sessao_sigitm.json",
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await context.new_page()

            print("🌐 Acessando o SIGITM com a sessão salva...")
            # Usamos wait_until="networkidle" para garantir que a página base carregou os scripts iniciais
            await page.goto("https://sigitm.vivo.com.br/app/app.jsp", wait_until="networkidle")

            # --- O TRUQUE DAS ABAS (Otimizado) ---
            print("🗂️ Verificando abas abertas e mudando o foco...")

            # Pequeno loop dinâmico para esperar o sistema abrir a nova aba interna
            for _ in range(10):
                if len(context.pages) > 1:
                    break
                await asyncio.sleep(0.5)

            todas_as_abas = context.pages
            page = todas_as_abas[-1]  # Foca na última aba aberta
            await page.bring_to_front()
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

            # 3. Busca da TA
            print("➡️ Aguardando a tela de pesquisa carregar...")
            # Espera dinamicamente pelo rótulo do formulário
            await page.get_by_text("Número do tíquete:").wait_for(state="visible", timeout=15000)

            print(f"🔍 Digitando a TA: {ta_number}")
            input_ta = page.locator("input.x-form-text:visible").first
            await input_ta.wait_for(state="visible", timeout=10000)
            await input_ta.fill(ta_number)

            await page.keyboard.press("Enter")

            print("⏳ Aguardando a tela da TA carregar...")
            # Em vez de esperar 4 segundos fixos, espera até que o botão 'Hist.' esteja visível na interface da TA
            aba_hist = page.locator("text='Hist.'")
            await aba_hist.wait_for(state="visible", timeout=20000)

            # 4. Extração na aba Histórico
            print("➡️ Acessando a aba 'Hist.'...")
            await aba_hist.click()

            # Espera que as requisições AJAX de carregamento da tabela terminem
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(1)  # Pausa mínima de segurança para renderização interna do sistema legada

            print("📥 Extraindo texto do Histórico...")
            texto_historico = await page.locator("body").inner_text()

            # 5. Extração na aba Procedimentos
            print("➡️ Acessando a aba 'Proced.'...")
            aba_proced = page.locator("text='Proced.'")
            await aba_proced.wait_for(state="visible", timeout=10000)
            await aba_proced.click()

            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(1)

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