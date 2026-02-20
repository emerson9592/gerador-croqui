from telethon import TelegramClient

# --- COLOQUE SEUS DADOS AQUI ---
api_id = 33091552  # SEU API_ID (numero)
api_hash = 'd09dcafbf4b9ba5427d80e5b4cad5837' # SEU API_HASH (texto)
session_name = 'sessao_usuario' # Nome do arquivo que será criado

async def main():
    # Isso vai abrir um prompt pedindo seu telefone e o código
    async with TelegramClient(session_name, api_id, api_hash) as client:
        print(f"Logado como: {await client.get_me()}")
        print("\n--- SEUS GRUPOS (Copie o ID do grupo que você quer) ---")
        async for dialog in client.iter_dialogs():
            if dialog.is_group:
                print(f"Nome: {dialog.name} | ID: {dialog.id}")

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())