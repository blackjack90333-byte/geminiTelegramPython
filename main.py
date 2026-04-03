import os
import re
import io
import asyncio
from PIL import Image
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.utils.chat_action import ChatActionSender
import google.generativeai as genai
from aiohttp import web

# Получаем ключи из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PORT = int(os.getenv("PORT", 10000))

# Настраиваем Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# Инициализируем бота и диспетчер
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()


# --- АРХИТЕКТУРНЫЕ ФУНКЦИИ ---

def format_to_tg_html(text: str) -> str:
    """Безопасный конвертер Markdown в HTML, понятный Телеграму."""
    # 1. Сначала обязательно экранируем системные символы HTML
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    # 2. Многострочный код: ```python\n code \n```
    text = re.sub(
        r'```(\w*)\n(.*?)```', 
        lambda m: f'<pre><code class="language-{m.group(1)}">{m.group(2)}</code></pre>' if m.group(1) else f'<pre><code>{m.group(2)}</code></pre>',
        text, 
        flags=re.DOTALL
    )
    # На всякий случай обрабатываем блоки кода без переноса строки
    text = re.sub(r'```(.*?)```', r'<pre><code>\1</code></pre>', text, flags=re.DOTALL)
    
    # 3. Инлайн код: `код` -> <code>код</code>
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    
    # 4. Жирный шрифт: **текст** -> <b>текст</b>
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    
    return text


def smart_chunk_text(text: str, min_limit=2500, hard_limit=3800) -> list:
    """Умная нарезка сырого текста с сохранением парных тегов кода."""
    chunks = []
    while text:
        if len(text) <= hard_limit:
            chunks.append(text)
            break
            
        # Ищем перенос строки в безопасном окне
        split_index = text.rfind('\n', min_limit, hard_limit)
        
        # Если переноса нет, ищем последний пробел
        if split_index == -1:
            split_index = text.rfind(' ', min_limit, hard_limit)
            
        # Жесткая обрезка (fallback)
        if split_index == -1:
            split_index = hard_limit
            
        chunk = text[:split_index]
        remainder = text[split_index:].lstrip()
        
        # Проверяем нечетное количество открытых блоков кода
        if chunk.count('```') % 2 != 0:
            chunk += '\n```'
            remainder = '```\n' + remainder
            
        chunks.append(chunk)
        text = remainder
        
    return chunks


# --- ОБРАБОТЧИКИ ---

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("Привет! Я твой личный ИИ-ассистент. Напиши текст или отправь фото с вопросом.")


@dp.message(F.text | F.photo)
async def handle_message(message: Message):
    # Вместо сообщения-заглушки используем асинхронный статус "печатает..."
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        try:
            content_to_send = []
            
            # Если прислали фото (Vision)
            if message.photo:
                photo = message.photo[-1] # Берем оригинал
                photo_file = await bot.get_file(photo.file_id)
                photo_bytes = await bot.download_file(photo_file.file_path)
                
                # Читаем в оперативную память без сохранения на диск
                image = Image.open(io.BytesIO(photo_bytes.read()))
                content_to_send.append(image)
                
                prompt = message.caption if message.caption else "Что на этой картинке? Опиши подробно."
                content_to_send.append(prompt)
                
            # Если просто текст
            elif message.text:
                content_to_send.append(message.text)

            # Отправляем в Gemini
            response = model.generate_content(content_to_send)
            
            # 1. Сначала режем сырой текст по логике
            chunks = smart_chunk_text(response.text)
            
            # 2. Потом конвертируем куски в HTML и отправляем
            for chunk in chunks:
                safe_html = format_to_tg_html(chunk)
                await message.answer(safe_html, parse_mode=ParseMode.HTML)
                
        except Exception as e:
            await message.answer(f"Упс, ошибка на стороне API: <code>{str(e)}</code>", parse_mode=ParseMode.HTML)


# --- ВЕБ-СЕРВЕР ---

async def handle_ping(request):
    return web.Response(text="Bot is running perfectly!")

async def main():
    print("Запускаю бота и веб-сервер...")
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    await dp.start_polling(bot)


if __name__ == "__main__":
    # Локальный тест
    # from dotenv import load_dotenv
    # load_dotenv()
    
    asyncio.run(main())
