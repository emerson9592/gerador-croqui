import asyncio
from playwright.async_api import async_playwright


async def salvar_sessao_manual():
    async with async_playwright() as p:
        # Abre o navegador visível para você interagir
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("🌐 Acessando o SIGITM...")
        await page.goto("https://sigitm.vivo.com.br/app/app.jsp")

        print("\n⏳ Faça o login normalmente no navegador que se abriu.")
        print("✅ Resolva o CAPTCHA e espere a tela principal do sistema carregar completamente.")

        # O script vai pausar aqui e esperar você dar o comando no terminal
        input(
            "\n🟢 Pressione ENTER aqui neste terminal APENAS DEPOIS que você estiver logado e vendo a tela inicial do sistema...")

        # O Playwright salva todos os cookies e tokens em um arquivo JSON
        await context.storage_state(path="sessao_sigitm.json")

        print("🎉 Sessão salva com sucesso no arquivo 'sessao_sigitm.json'!")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(salvar_sessao_manual())