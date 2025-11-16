import logging
import json
import os
import asyncio
import uuid
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
import aiohttp
import base64
import re
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

logging.basicConfig(level=logging.INFO)

# Получение токенов из .env
API_TOKEN = os.getenv('API_TOKEN')
GIGACHAT_AUTHORIZATION_KEY = os.getenv('GIGACHAT_AUTHORIZATION_KEY')
GIGACHAT_SCOPE = os.getenv('GIGACHAT_SCOPE')

# Проверка наличия токенов
if not API_TOKEN:
    raise ValueError("API_TOKEN не найден в .env файле")
if not GIGACHAT_AUTHORIZATION_KEY:
    raise ValueError("GIGACHAT_AUTHORIZATION_KEY не найден в .env файле")
if not GIGACHAT_SCOPE:
    raise ValueError("GIGACHAT_SCOPE не найден в .env файле")

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Кэш для токенов
gigachat_tokens = {}


# FSM состояния
class UserStates(StatesGroup):
    waiting_for_choice = State()
    waiting_for_action = State()
    waiting_for_org_name = State()
    waiting_for_org_description = State()
    waiting_for_org_activity = State()
    waiting_for_text_type = State()
    waiting_for_post_topic = State()
    waiting_for_post_aspect = State()
    waiting_for_post_relevance = State()
    waiting_for_event_name = State()
    waiting_for_event_date = State()
    waiting_for_event_location = State()
    waiting_for_event_audience = State()
    waiting_for_event_details = State()
    waiting_for_post_example = State()
    waiting_for_image_subject = State()
    waiting_for_image_background = State()
    waiting_for_image_style = State()
    waiting_for_content_plan_period = State()
    waiting_for_content_plan_theme = State()
    waiting_for_content_plan_goals = State()
    waiting_for_text_edit = State()


# Получение токена доступа GigaChat
async def get_gigachat_token() -> str:
    try:
        rquid = str(uuid.uuid4())
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'RqUID': rquid,
            'Authorization': f'Basic {GIGACHAT_AUTHORIZATION_KEY}'
        }
        data = {'scope': GIGACHAT_SCOPE}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    'https://ngw.devices.sberbank.ru:9443/api/v2/oauth',
                    headers=headers,
                    data=data,
                    ssl=False  # отключаем проверку сертификата для self-signed
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    token = result['access_token']
                    expires_at = result['expires_at']
                    gigachat_tokens['token'] = token
                    gigachat_tokens['expires_at'] = expires_at
                    logging.info("GigaChat token получен успешно")
                    return token
                else:
                    error_text = await response.text()
                    logging.error(f"GigaChat auth error: {error_text}")
                    return None
    except Exception as e:
        logging.error(f"Error getting GigaChat token: {e}")
        return None


# Форматирование промпта с учетом данных пользователя
def format_prompt(base_prompt: str, user_data: dict = None) -> str:
    if not user_data:
        return base_prompt

    ngo_context = ""
    if user_data.get('ngo_data'):
        ngo = user_data['ngo_data']
        if ngo.get('org_name'):
            ngo_context += f"Организация: {ngo['org_name']}. "
        if ngo.get('org_description'):
            ngo_context += f"Описание: {ngo['org_description']}. "
        if ngo.get('org_activity'):
            ngo_context += f"Деятельность: {ngo['org_activity']}. "

    if ngo_context:
        return f"{base_prompt}\n\nКонтекст для генерации: {ngo_context}\n\nУчти эту информацию при создании текста."

    return base_prompt


# Генерация текста с помощью GigaChat API (не промпты)
async def generate_text_with_gigachat(prompt: str, user_data: dict = None) -> str:
    try:
        token = gigachat_tokens.get('token')
        if not token or gigachat_tokens.get('expires_at', 0) < datetime.now().timestamp() * 1000:
            token = await get_gigachat_token()
            if not token:
                return " Ошибка авторизации в GigaChat"

        full_prompt = format_prompt(prompt, user_data)

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {token}'
        }

        data = {
            "model": "GigaChat",
            "messages": [{"role": "user", "content": full_prompt}],
            "temperature": 0.7,
            "max_tokens": 1000
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    'https://gigachat.devices.sberbank.ru/api/v1/chat/completions',
                    headers=headers,
                    json=data,
                    ssl=False
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result['choices'][0]['message']['content']
                elif response.status == 401:
                    token = await get_gigachat_token()
                    if token:
                        headers['Authorization'] = f'Bearer {token}'
                        async with session.post(
                                'https://gigachat.devices.sberbank.ru/api/v1/chat/completions',
                                headers=headers,
                                json=data,
                                ssl=False
                        ) as retry_response:
                            if retry_response.status == 200:
                                result = await retry_response.json()
                                return result['choices'][0]['message']['content']
                    return "❌ Ошибка доступа к GigaChat API"
                else:
                    error_text = await response.text()
                    logging.error(f"GigaChat API error: {error_text}")
                    return f"❌ Ошибка при генерации текста: {response.status}"
    except Exception as e:
        logging.error(f"Error generating text with GigaChat: {e}")
        return f"❌ Произошла ошибка: {str(e)}"


# Клавиатуры самого бота
def get_main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="Заполнить данные об НКО"),
             types.KeyboardButton(text="Продолжить без данных")]
        ],
        resize_keyboard=True
    )
    return keyboard


def get_action_keyboard():
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="Генерация текста"),
             types.KeyboardButton(text="Сделать картинку")],
            [types.KeyboardButton(text="Контент-план"),
             types.KeyboardButton(text="Редактор текста")],
            [types.KeyboardButton(text="Назад")]
        ],
        resize_keyboard=True
    )
    return keyboard


def get_text_generation_keyboard():
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="Генерация текста для поста по вашей идее")],
            [types.KeyboardButton(text="Генерация текста для поста, информирующий о предстоящем мероприятии")],
            [types.KeyboardButton(text="Генерация текста на примере другого поста")],
            [types.KeyboardButton(text="Назад в меню")]
        ],
        resize_keyboard=True
    )
    return keyboard


def get_skip_keyboard():
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="Пропустить")]],
        resize_keyboard=True
    )
    return keyboard


def get_cancel_keyboard():
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="Отмена")]],
        resize_keyboard=True
    )
    return keyboard


# Функции сохранения данных
def save_ngo_data(user_id, data):
    user_dir = f"data/user{user_id}"
    os.makedirs(user_dir, exist_ok=True)
    filename = f"{user_dir}/ngo_data.json"
    data['timestamp'] = datetime.now().isoformat()
    data['user_id'] = user_id
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logging.error(f"Ошибка сохранения данных: {e}")
        return False


def save_text_generation_data(user_id, generation_type, data):
    user_dir = f"data/user{user_id}"
    os.makedirs(user_dir, exist_ok=True)
    filename = f"{user_dir}/text_generation_{generation_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    data['generation_type'] = generation_type
    data['timestamp'] = datetime.now().isoformat()
    data['user_id'] = user_id
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logging.error(f"Ошибка сохранения данных генерации: {e}")
        return False


def save_image_generation_data(user_id, data):
    user_dir = f"data/user{user_id}"
    os.makedirs(user_dir, exist_ok=True)
    filename = f"{user_dir}/image_generation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    data['generation_type'] = 'image'
    data['timestamp'] = datetime.now().isoformat()
    data['user_id'] = user_id
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logging.error(f"Ошибка сохранения данных генерации изображения: {e}")
        return False


def save_text_edit_data(user_id, text):
    user_dir = f"data/user{user_id}"
    os.makedirs(user_dir, exist_ok=True)
    filename = f"{user_dir}/text_edit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    data = {
        'text': text,
        'type': 'text_edit',
        'timestamp': datetime.now().isoformat(),
        'user_id': user_id
    }
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logging.error(f"Ошибка сохранения текста для редактирования: {e}")
        return False


def save_content_plan_data(user_id, data):
    user_dir = f"data/user{user_id}"
    os.makedirs(user_dir, exist_ok=True)
    filename = f"{user_dir}/content_plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    data['type'] = 'content_plan'
    data['timestamp'] = datetime.now().isoformat()
    data['user_id'] = user_id
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logging.error(f"Ошибка сохранения контент-плана: {e}")
        return False


# Обработчики команд ==============

# Приветственное окно
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    try:
        with open("wlcm_ter.jpg", 'rb') as photo:
            await message.answer_photo(
                photo=types.BufferedInputFile(photo.read(), filename="welcome.jpg")
            )
    except Exception as e:
        logging.warning(f"Не удалось отправить фото: {e}")
    await message.answer(
        '''⭐️ Привет!

Я бот, который помогает генерировать тексты постов, создавать изображения и идеи контент-плана 🤖

Сэкономлю время и помогу рассказать миру о вашем важном деле ярко и качественно 💪''',
        reply_markup=get_main_keyboard()
    )
    await state.set_state(UserStates.waiting_for_choice)


# Главное меню
@dp.message(UserStates.waiting_for_choice)
async def process_main_menu(message: types.Message, state: FSMContext):
    if message.text == "Заполнить данные об НКО":
        await state.update_data(ngo_data={})
        await message.answer(
            "Я генерирую контент, подстраиваясь под цели вашей организации.\n"
            "Позвольте узнать про вашу НКО, чтобы помочь вам достичь результата как можно скорее!\n\n"
            "1️⃣ Напишите название вашей организации \n\n"
            "❗️Если вы не хотите сообщать данные об НКО, ничего страшного! Просто нажмите кнопку \"Пропустить\"",
            reply_markup=get_skip_keyboard()
        )
        await state.set_state(UserStates.waiting_for_org_name)

    elif message.text == "Продолжить без данных":
        await message.answer("Вы выбрали: Продолжить без данных")
        await message.answer("Переходим к основным функциям:", reply_markup=get_action_keyboard())
        await state.set_state(UserStates.waiting_for_action)

    else:
        await message.answer("Пожалуйста, выберите один из предложенных вариантов :", reply_markup=get_main_keyboard())


# Ввод данных об НКО
@dp.message(UserStates.waiting_for_org_name)
async def process_org_name(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    ngo_data = user_data.get('ngo_data', {})

    if message.text == "Пропустить":
        ngo_data['org_name'] = None
        await message.answer("Название организации пропущено")
    else:
        ngo_data['org_name'] = message.text
        await message.answer(f"✅ Название сохранено: {message.text}")

    await state.update_data(ngo_data=ngo_data)

    await message.answer(
        "2️⃣ Опишите вашу организацию в 2-3 предложениях.\n"
        "Это поможет мне лучше понять ваши цели и аудиторию!",
        reply_markup=get_skip_keyboard()
    )
    await state.set_state(UserStates.waiting_for_org_description)


@dp.message(UserStates.waiting_for_org_description)
async def process_org_description(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    ngo_data = user_data.get('ngo_data', {})

    if message.text == "Пропустить":
        ngo_data['org_description'] = None
        await message.answer("Описание организации пропущено")
    else:
        ngo_data['org_description'] = message.text
        await message.answer("✅ Описание сохранено")

    await state.update_data(ngo_data=ngo_data)

    await message.answer(
        "3️⃣Напишите форму вашей деятельности\n"
        "Например, медицина, защита окружающей среды, социальная защита и т. д.",
        reply_markup=get_skip_keyboard()
    )
    await state.set_state(UserStates.waiting_for_org_activity)


@dp.message(UserStates.waiting_for_org_activity)
async def process_org_activity(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    ngo_data = user_data.get('ngo_data', {})

    if message.text == "Пропустить":
        ngo_data['org_activity'] = None
        await message.answer("Форма деятельности пропущена")
    else:
        ngo_data['org_activity'] = message.text
        await message.answer("✅ Форма деятельности сохранена")

    await state.update_data(ngo_data=ngo_data)

    # Сохранение данных НКО
    if save_ngo_data(message.from_user.id, ngo_data):
        await message.answer(
            "🎉 Данные об НКО успешно сохранены!\n"
            "Теперь я могу генерировать контент, учитывая специфику вашей организации.",
            reply_markup=get_action_keyboard()
        )
    else:
        await message.answer(
            "⚠️ Данные собраны, но произошла ошибка при сохранении файла.\n"
            "Переходим к основным функциям:",
            reply_markup=get_action_keyboard()
        )

    await state.set_state(UserStates.waiting_for_action)


# Меню действий
@dp.message(UserStates.waiting_for_action)
async def process_actions(message: types.Message, state: FSMContext):
    if message.text == "Генерация текста":
        await message.answer(
            "📝 Выберите тип генерации текста:",
            reply_markup=get_text_generation_keyboard()
        )
        await state.set_state(UserStates.waiting_for_text_type)

    elif message.text == "Сделать картинку":
        await state.update_data(image_generation_data={})
        await message.answer(
            "Отлично!\n\nОпишите, кого или что вы хотите видеть на картинке?",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(UserStates.waiting_for_image_subject)

    elif message.text == "Контент-план":
        await state.update_data(content_plan_data={})
        await message.answer(
            "На какой период нужен контент-план? (например: на неделю, на месяц, на квартал)",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(UserStates.waiting_for_content_plan_period)

    elif message.text == "Редактор текста":
        await message.answer(
            "Отправьте текст, который нужно проверить",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(UserStates.waiting_for_text_edit)

    elif message.text == "Назад":
        await message.answer("Возвращаемся в главное меню:", reply_markup=get_main_keyboard())
        await state.set_state(UserStates.waiting_for_choice)

    else:
        await message.answer("Пожалуйста, выберите один из предложенных вариантов:", reply_markup=get_action_keyboard())


# Выбор типа текста
@dp.message(UserStates.waiting_for_text_type)
async def process_text_type(message: types.Message, state: FSMContext):
    if message.text == "Генерация текста для поста по вашей идее":
        await state.update_data(generation_data={})
        await message.answer("Напишите тему поста 📇:", reply_markup=get_cancel_keyboard())
        await state.set_state(UserStates.waiting_for_post_topic)

    elif message.text == "Генерация текста для поста, информирующий о предстоящем мероприятии":
        await state.update_data(generation_data={})
        await message.answer("Какое мероприятие вы организуете? 🔨", reply_markup=get_cancel_keyboard())
        await state.set_state(UserStates.waiting_for_event_name)

    elif message.text == "Генерация текста на примере другого поста":
        await state.update_data(generation_data={})
        await message.answer("Отправьте текст поста-примера 💭:", reply_markup=get_cancel_keyboard())
        await state.set_state(UserStates.waiting_for_post_example)

    elif message.text == "Назад в меню":
        await message.answer("Возвращаемся к основным функциям:", reply_markup=get_action_keyboard())
        await state.set_state(UserStates.waiting_for_action)

    else:
        await message.answer("Выберите вариант из меню:", reply_markup=get_text_generation_keyboard())


# Генерация текста по идее
@dp.message(UserStates.waiting_for_post_topic)
async def process_post_topic(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await message.answer("Отменяем генерацию текста", reply_markup=get_action_keyboard())
        await state.set_state(UserStates.waiting_for_action)
        return

    user_data = await state.get_data()
    gen_data = user_data.get('generation_data', {})
    gen_data['topic'] = message.text
    await state.update_data(generation_data=gen_data)

    await message.answer("Опишите аспект темы, который хотите раскрыть 🖋️:")
    await state.set_state(UserStates.waiting_for_post_aspect)


@dp.message(UserStates.waiting_for_post_aspect)
async def process_post_aspect(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    gen_data = user_data.get('generation_data', {})
    gen_data['aspect'] = message.text
    await state.update_data(generation_data=gen_data)

    await message.answer("Почему эта тема актуальна? 🤔")
    await state.set_state(UserStates.waiting_for_post_relevance)


@dp.message(UserStates.waiting_for_post_relevance)
async def process_post_relevance(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    gen_data = user_data.get('generation_data', {})
    gen_data['relevance'] = message.text

    save_text_generation_data(message.from_user.id, "by_idea", gen_data)

    # ПРОМПТ 1
    prompt = f"""
    ты имеешь огромный опыт в создании:
    мероприятий, 
    маркетинге, 
    SMM,
    психологии человека. 

    Ты работал в этой сфере всю жизнь и прошел все этапы работы и адаптации. 
    На данный момент ты профессиональный помощник по написанию анонсов мероприятий для некомерческих организаций. 
    Каждая твоя фраза это точное, интригующее, завлекающее предложение, которое было основано на данных
    Пиши ясно и емко, без ошибок.

    Сгенерируй текст для поста на тему "{gen_data['topic']}".
    Аспект: {gen_data['aspect']}. Актуальность: {gen_data['relevance']}.
    Сделай текст живым, engaging, с призывом к действию и эмодзи.
    """

    result = await generate_text_with_gigachat(prompt, user_data)
    await message.answer(f"📝 Сгенерированный текст:\n\n{result}", reply_markup=get_action_keyboard())
    await state.set_state(UserStates.waiting_for_action)


# Генерация текста о мероприятии
@dp.message(UserStates.waiting_for_event_name)
async def process_event_name(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    gen_data = user_data.get('generation_data', {})
    gen_data['event_name'] = message.text
    await state.update_data(generation_data=gen_data)

    await message.answer("Когда состоится мероприятие? (дата и время) 📅")
    await state.set_state(UserStates.waiting_for_event_date)


@dp.message(UserStates.waiting_for_event_date)
async def process_event_date(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    gen_data = user_data.get('generation_data', {})
    gen_data['event_date'] = message.text
    await state.update_data(generation_data=gen_data)

    await message.answer("Где будет проходить мероприятие?")
    await state.set_state(UserStates.waiting_for_event_location)


@dp.message(UserStates.waiting_for_event_location)
async def process_event_location(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    gen_data = user_data.get('generation_data', {})
    gen_data['event_location'] = message.text
    await state.update_data(generation_data=gen_data)

    await message.answer("Для кого организовано мероприятие? 👥")
    await state.set_state(UserStates.waiting_for_event_audience)


@dp.message(UserStates.waiting_for_event_audience)
async def process_event_audience(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    gen_data = user_data.get('generation_data', {})
    gen_data['event_audience'] = message.text
    await state.update_data(generation_data=gen_data)

    await message.answer("Дополнительные детали мероприятия ➕:")
    await state.set_state(UserStates.waiting_for_event_details)


@dp.message(UserStates.waiting_for_event_details)
async def process_event_details(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    gen_data = user_data.get('generation_data', {})
    gen_data['event_details'] = message.text
    save_text_generation_data(message.from_user.id, "event_info", gen_data)

    prompt = f"""    ты имеешь огромный опыт в создании:
    мероприятий, 
    маркетинге, 
    SMM,
    психологии человека. 

    тебя нанинмают тысячи компаний, нацеленные на добрые дела. 


    Ты работал в этой сфере всю жизнь и прошел все этапы работы и адаптации. 
    На данный момент ты профессиональный помощник по написанию анонсов мероприятий для некомерческих организаций. 
    Каждая твоя фраза это точное, интригующее, завлекающее предложение, которое было основано на данных
    Пиши ясно и емко, без ошибок.

    Анализируй и думай над каждым вводным данным, после на соновве анализа выдавай ананос


    Сгенерируй анонс мероприятия для соцсетей:
    - Название: {gen_data['event_name']}
    - Дата: {gen_data['event_date']}
    - Место: {gen_data['event_location']}
    - Аудитория: {gen_data['event_audience']}
    - Детали: {gen_data['event_details']}
    Сделай текст привлекательным и информативным с призывом к действию.
    """
    result = await generate_text_with_gigachat(prompt, user_data)
    await message.answer(f"📅 Анонс мероприятия:\n\n{result}", reply_markup=get_action_keyboard())
    await state.set_state(UserStates.waiting_for_action)


# Генерация текста по примеру
@dp.message(UserStates.waiting_for_post_example)
async def process_post_example(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    gen_data = user_data.get('generation_data', {})
    gen_data['post_example'] = message.text
    save_text_generation_data(message.from_user.id, "by_example", gen_data)

    prompt = f"""
    ты имеешь огромный опыт в создании:
    мероприятий, 
    маркетинге, 
    SMM,
    психологии человека. 

    тебя нанинмают тысячи компаний, нацеленные на добрые дела. 


    Ты работал в этой сфере всю жизнь и прошел все этапы работы и адаптации. 
    На данный момент ты профессиональный помощник по написанию анонсов мероприятий для некомерческих организаций. 
    Каждая твоя фраза это точное, интригующее, завлекающее предложение, которое было основано на данных
    Пиши ясно и емко, без ошибок.

    Анализируй и думай над каждым вводным данным, после на соновве анализа выдавай ананос. Ты гений анализа и креатива.

    Создай новый пост в стиле примера, но на тему деятельности НКО:
    {gen_data['post_example']}
    """
    result = await generate_text_with_gigachat(prompt, user_data)
    await message.answer(f"📝 Текст в стиле примера:\n\n{result}", reply_markup=get_action_keyboard())
    await state.set_state(UserStates.waiting_for_action)


# Обработка ввода объекта изображения
@dp.message(UserStates.waiting_for_image_subject)
async def process_image_subject(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await message.answer("Отменяем генерацию изображения", reply_markup=get_action_keyboard())
        await state.set_state(UserStates.waiting_for_action)
        return

    user_data = await state.get_data()
    image_data = user_data.get('image_generation_data', {})
    image_data['subject'] = message.text
    await state.update_data(image_generation_data=image_data)

    await message.answer(
        "Теперь опишите фон или окружение для изображения:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(UserStates.waiting_for_image_background)


# Обработка ввода фона изображения
@dp.message(UserStates.waiting_for_image_background)
async def process_image_background(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await message.answer("Отменяем генерацию изображения", reply_markup=get_action_keyboard())
        await state.set_state(UserStates.waiting_for_action)
        return

    user_data = await state.get_data()
    image_data = user_data.get('image_generation_data', {})
    image_data['background'] = message.text
    await state.update_data(image_generation_data=image_data)

    await message.answer(
        "Какой стиль изображения предпочитаете? (например: реализм, мультяшный, минимализм)",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(UserStates.waiting_for_image_style)


# Обработка ввода стиля и генерация изображения
@dp.message(UserStates.waiting_for_image_style)
async def process_image_style(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await message.answer("Отменяем генерацию изображения", reply_markup=get_action_keyboard())
        await state.set_state(UserStates.waiting_for_action)
        return

    user_data = await state.get_data()
    image_data = user_data.get('image_generation_data', {})
    image_data['style'] = message.text

    # Сохраняем данные
    save_image_generation_data(message.from_user.id, image_data)

    await message.answer("🔄 Генерирую изображение... Это может занять несколько секунд ⏳")

    # Генерируем изображение
    img_bytes = await generate_image_via_function(
        subject=image_data['subject'],
        background=image_data['background'],
        style=image_data['style']
    )

    if img_bytes:
        # Отправляем сгенерированное изображение
        await message.answer_photo(
            photo=types.BufferedInputFile(img_bytes, filename="generated_image.jpg"),
            caption="🎨 Ваше сгенерированное изображение!",
            reply_markup=get_action_keyboard()
        )
    else:
        await message.answer(
            "❌ Не удалось сгенерировать изображение. Попробуйте позже или измените описание.",
            reply_markup=get_action_keyboard()
        )

    await state.set_state(UserStates.waiting_for_action)

async def generate_image_via_function(subject: str, background: str, style: str):
    """
    Генерация изображения через встроенную image-функцию GigaChat (text2image).
    Работает строго по документации GigaChat.
    Возвращает байты изображения (подходит для Telegram send_photo).
    """

    # Проверяем токен
    token = gigachat_tokens.get("token")
    if not token or gigachat_tokens.get("expires_at", 0) < datetime.now().timestamp() * 1000:
        token = await get_gigachat_token()
        if not token:
            logging.error("❌ Не удалось получить токен для функции генерации изображений")
            return None

    # Заголовки
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # Формируем текстовый запрос, который GigaChat должен интерпретировать как вызов функции image
    prompt = f"Сгенерируй изображение. Объект: {subject}. Фон: {background}. Стиль: {style}"

    body = {
        "model": "GigaChat",
        "messages": [
            {"role": "system", "content": "Ты — помощник, который умеет создавать изображения по запросу."},
            {"role": "user", "content": prompt}
        ],
        "function_call": "auto"
    }

    # 1) Отправляем запрос на chat/completions → GigaChat вернет <img src="ID"/>
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
                    headers=headers,
                    json=body,
                    ssl=False
            ) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    logging.error(f"❌ Ошибка GigaChat image-функции: {resp.status} — {err}")
                    return None

                data = await resp.json()

    except Exception as e:
        logging.error(f"❌ Ошибка при запросе к GigaChat chat/completions: {e}")
        return None

    # Парсим ID изображения
    try:
        content = data["choices"][0]["message"]["content"]
        # Пример ответа: <img src="ec49c288-6601-4fe4-8be5-5ef9e3738ac6" fuse="true" />
        match = re.search(r'<img src="([^"]+)"', content)

        if not match:
            logging.error(f"❌ Не удалось найти файл изображения в ответе GigaChat: {content}")
            return None

        file_id = match.group(1)

    except Exception as e:
        logging.error(f"❌ Ошибка при извлечении file_id из ответа: {e}")
        return None

    # 2) Скачиваем изображение по file_id
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    f"https://gigachat.devices.sberbank.ru/api/v1/files/{file_id}/content",
                    headers={"Authorization": f"Bearer {token}"},
                    ssl=False
            ) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    logging.error(f"❌ Ошибка GigaChat при скачивании файла: {resp.status} — {err}")
                    return None

                img_bytes = await resp.read()
                return img_bytes

    except Exception as e:
        logging.error(f"❌ Ошибка при загрузке изображения по file_id: {e}")
        return None


# Контент-план

# Контент-план (расширенная версия)
@dp.message(UserStates.waiting_for_content_plan_period)
async def process_content_plan_period(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await message.answer("Отменяем создание контент-плана", reply_markup=get_action_keyboard())
        await state.set_state(UserStates.waiting_for_action)
        return

    user_data = await state.get_data()
    cp_data = user_data.get('content_plan_data', {})
    cp_data['period'] = message.text
    await state.update_data(content_plan_data=cp_data)

    await message.answer("✅ Отлично! Какая основная тема контент-плана?")
    await state.set_state(UserStates.waiting_for_content_plan_theme)


@dp.message(UserStates.waiting_for_content_plan_theme)
async def process_content_plan_theme(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await message.answer("Отменяем создание контент-плана", reply_markup=get_action_keyboard())
        await state.set_state(UserStates.waiting_for_action)
        return

    user_data = await state.get_data()
    cp_data = user_data.get('content_plan_data', {})
    cp_data['theme'] = message.text
    await state.update_data(content_plan_data=cp_data)

    await message.answer("✅ Отлично! Какие цели вы хотите достичь с помощью контента?")
    await state.set_state(UserStates.waiting_for_content_plan_goals)


@dp.message(UserStates.waiting_for_content_plan_goals)
async def process_content_plan_goals(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await message.answer("Отменяем создание контент-плана", reply_markup=get_action_keyboard())
        await state.set_state(UserStates.waiting_for_action)
        return

    user_data = await state.get_data()
    cp_data = user_data.get('content_plan_data', {})
    cp_data['goals'] = message.text

    # Сохраняем данные
    save_content_plan_data(message.from_user.id, cp_data)

    await message.answer("🔄 Создаю контент-план... Это займет несколько секунд ⏳")

    # Формируем детальный промпт
    prompt = f"""
    Ты - эксперт по контент-стратегии для некоммерческих организаций. 
    Разработай профессиональный контент-план для социальных сетей.

    ДАННЫЕ ДЛЯ ПЛАНИРОВАНИЯ:
    📅 Период: {cp_data['period']}
    🎯 Тематика: {cp_data['theme']}
    🎯 Цели: {cp_data['goals']}

    СТРУКТУРА КОНТЕНТ-ПЛАНА:
    1. ОБЩИЙ ОБЗОР ПЕРИОДА
    2. ДЛЯ КАЖДОГО ЭЛЕМЕНТА УКАЖИ:
       - Тема поста
       - Формат контента
       - Ключевое сообщение
       - Призыв к действию (CTA)
       - Рекомендуемые хэштеги

    ТРЕБОВАНИЯ:
    • Соответствуй тематике НКО
    • Чередуй образовательный, вовлекающий и призывной контент
    • Учитывай реалистичность выполнения
    • Включи 1-2 дня для пользовательского контента

    ФОРМАТ ОТВЕТА:
    понедельник: ....
    вторник: ....
    среда: ....
    четверг: ...
    пятница: ...
    суббота: ...
    воскресенье: ...
    
    используй простой текст столбиком, чтобы было сразу наглядно, понятно и ясно. Добавь локанчные эмодзи, которые дополняют контент план
    """

    # Генерируем контент-план
    content_plan = await generate_text_with_gigachat(prompt, user_data)

    if content_plan and not content_plan.startswith("❌"):
        # Обрабатываем длинные сообщения
        if len(content_plan) > 4000:
            # Разбиваем по абзацам или предложениям
            parts = []
            current_part = ""

            for paragraph in content_plan.split('\n\n'):
                if len(current_part + paragraph) < 4000:
                    current_part += paragraph + '\n\n'
                else:
                    parts.append(current_part)
                    current_part = paragraph + '\n\n'

            if current_part:
                parts.append(current_part)

            # Отправляем части
            for i, part in enumerate(parts, 1):
                if i == 1:
                    await message.answer(f"📊 КОНТЕНТ-ПЛАН (часть {i}/{len(parts)}):\n\n{part}")
                else:
                    await message.answer(part)

                # Небольшая задержка между сообщениями
                if i < len(parts):
                    await asyncio.sleep(0.5)
        else:
            await message.answer(f"📊 ВАШ КОНТЕНТ-ПЛАН:\n\n{content_plan}")

        # Финальное сообщение
        await message.answer(
            "🎯 Контент-план создан! Теперь у вас есть четкий план публикаций.\n\n"
            "💡 Советы по использованию:\n"
            "• Адаптируйте предложенные идеи под вашу аудиторию\n"
            "• Используйте разные форматы контента\n"
            "• Отслеживайте engagement для оптимизации\n\n"
            "Что хотите сделать дальше?",
            reply_markup=get_action_keyboard()
        )

    await state.set_state(UserStates.waiting_for_action)


# Редактор текста
@dp.message(UserStates.waiting_for_text_edit)
async def process_text_edit(message: types.Message, state: FSMContext):
    save_text_edit_data(message.from_user.id, message.text)

    prompt = f"""
    Ты гений драматургии и лингвистики. Ты проверяешь каждое слово и значение, а также анализируешь на корректность сочиненные связи.
    Проверь текст на грамматические, синтаксические и пунктуационные ошибки:
    {message.text}
    """
    result = await generate_text_with_gigachat(prompt)
    await message.answer(f"🔍 Результат проверки:\n\n{result}", reply_markup=get_action_keyboard())
    await state.set_state(UserStates.waiting_for_action)


if __name__ == '__main__':
    import asyncio


    async def runner():
        try:
            if not os.path.exists('data'):
                os.makedirs('data')

            # Проверка токена GigaChat
            token = await get_gigachat_token()
            if token:
                logging.info("✅ GigaChat подключен успешно")
            else:
                logging.warning("⚠️ GigaChat не подключен. Проверьте AUTHORIZATION_KEY")

            await dp.start_polling(bot)
        finally:
            await bot.session.close()


    asyncio.run(runner())
