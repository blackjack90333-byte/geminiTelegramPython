import os
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
import google.generativeai as genai
from aiohttp import web

# Получаем ключи из переменных окружения
# Локально они берутся из файла, а на Render мы их впишем в настройках
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PORT = int(os.getenv("PORT", 10000)) # Render сам назначит порт

# Настраиваем Gemini
genai.configure(api_key=GEMINI_API_KEY)
# Используем flash-модель: она супер-быстрая и лимитов Free Tier хватит за глаза
model = genai.GenerativeModel('gemini-2.5-flash')

# Инициализируем бота и диспетчер
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# Обработчик команды /start
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("Привет! Я твой личный ИИ-ассистент. Напиши мне любой вопрос, например 'что такое биссектриса?'")

# Обработчик всех остальных текстовых сообщений
@dp.message()
async def handle_message(message: Message):
    # Отправляем сообщение-заглушку, чтобы ты видел, что запрос ушел
    wait_msg = await message.answer("🤔 Думаю...")
    
    try:
        # Отправляем текст из Телеграма в Gemini
        response = model.generate_content(message.text)
        
        # Редактируем наше сообщение "Думаю...", заменяя его на готовый ответ
        await wait_msg.edit_text(response.text)
        
    except Exception as e:
        await wait_msg.edit_text(f"Упс, произошла ошибка на стороне API: {e}")

# Простая веб-страничка для Render (чтобы сервис не падал)
async def handle_ping(request):
    return web.Response(text="Bot is running perfectly!")

async def main():
    print("Запускаю бота и веб-сервер...")
    
    # Настраиваем веб-сервер aiohttp
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    # Запускаем бота в режиме polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Если запускаешь локально, раскомментируй следующие две строки для подгрузки .env
    # from dotenv import load_dotenv
    # load_dotenv()
    
    asyncio.run(main())
