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
    """Продвинутый конвертер Markdown -> Telegram HTML с поддержкой таблиц и списков."""
    
    # 1. Экранируем системные символы HTML
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    # 2. УМНАЯ ОБРАБОТКА ТАБЛИЦ (Оборачиваем в моноширинный шрифт)
    lines = text.split('\n')
    in_table = False
    parsed_lines = []
    
    for line in lines:
        # Если строка содержит хотя бы две палочки '|' - это 99% строка таблицы
        if line.strip().count('|') >= 2:
            if not in_table:
                parsed_lines.append('<pre><code>') # Открываем блок консольного шрифта
                in_table = True
            parsed_lines.append(line)
        else:
            if in_table:
                parsed_lines.append('</code></pre>') # Закрываем блок
                in_table = False
            parsed_lines.append(line)
            
    if in_table: # Закрываем, если таблица была в самом конце текста
        parsed_lines.append('</code></pre>')
        
    text = '\n'.join(parsed_lines)
    
    # 3. Блоки кода (чтобы не сломать то, что уже обернули)
    text = re.sub(
        r'```(\w*)\n(.*?)```', 
        lambda m: f'<pre><code class="language-{m.group(1)}">{m.group(2)}</code></pre>' if m.group(1) else f'<pre><code>{m.group(2)}</code></pre>',
        text, 
        flags=re.DOTALL
    )
    text = re.sub(r'```(.*?)```', r'<pre><code>\1</code></pre>', text, flags=re.DOTALL)
    
    # 4. Инлайн код: `код` -> <code>код</code>
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    
    # 5. Жирный шрифт: **текст** -> <b>текст</b>
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    
    # 6. Заголовки (эмулируем: делаем жирным и подчеркнутым)
    # Ищем от 1 до 6 решеток в начале строки, пробел и сам текст заголовка
    text = re.sub(r'^#{1,6}\s+(.+)$', r'<b><u>\1</u></b>', text, flags=re.MULTILINE)
    
    # 7. Маркированные списки (меняем '* ' или '- ' на красивую точку '• ')
    text = re.sub(r'^\s*[\*\-]\s+', '• ', text, flags=re.MULTILINE)
    
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

        wait_msg = await message.answer("🤔 Думаю...")
        
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
            response = await model.generate_content_async(content_to_send)
            
            
            # 4. Нарезка и отправка
            chunks = smart_chunk_text(response.text)
            for i, chunk in enumerate(chunks):
                safe_html = format_to_tg_html(chunk)
                if i == 0:
                    # Редактируем заглушку первым куском ответа
                    await wait_msg.edit_text(safe_html, parse_mode=ParseMode.HTML)
                else:
                    # Остальное шлем новыми сообщениями
                    await message.answer(safe_html, parse_mode=ParseMode.HTML)
                
        except Exception as e:
            error_text = f"❌ Ошибка: <code>{str(e)}</code>"
            await wait_msg.edit_text(error_text, parse_mode=ParseMode.HTML)


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
