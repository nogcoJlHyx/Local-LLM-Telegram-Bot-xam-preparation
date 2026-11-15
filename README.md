# 🤖 Local LLM Telegram Bot & Exam preparationn

> Telegram-бот с локальной языковой моделью для подготовки к экзамену. Срочный проект, реализован за 3 дня.
---

## 📌 О проекте (Overview)
Бот отправляет вопрос -> пользователь вводит ответ -> нейросеть обрабатывает контекст вопроса и ответа, далее выносит вердикт верно/неверно. Так же ИИ генерирует краткие пояснения после ответа и показывает на что опиралась при выводе. Это позволяет даже при галлюцинациях пользователю самостоятельно оценить верность ответа. 

### Ключевые возможности:
- 🧠 **Локальный инференс LLM** — работа без сторонних платных API и утечки данных.
- ⚡ **Приватность** — заказчик просил приватного бота для определенного круга лиц. Поэтому программа реализована через Telegram-ID (для больших компаний и аудитории 50+ человек такой вариант плох)
- 📊 **Экономия ресурсов** — Гибридная валидация (Fast checks + LLM): не тратится ресурс видеокарты/процессора там, где можно проверить регулярным выражением или точным совпадением.
- 💬 **Удобный интерфейс** — быстрые и простые сценарии в Telegram.

---

## 🛠 Tech Stack & Architecture

### Backend & Core
- **Language:** Python 3.10+
- **Asynchronous Framework:** `asyncio` (non-blocking I/O, background thread delegation via `asyncio.to_thread`)
- **HTTP & Networking:** `aiohttp` (custom session timeout management), `requests`

### Telegram Bot Framework
- **Framework:** `aiogram 3.x`
- **Architecture & State Management:** FSM (Finite State Machine) with `MemoryStorage`
- **Security & Access Control:** Custom outer middleware (`access_middleware`) for strict whitelist filtering by Telegram User ID
- **UX & Formatting:** HTML parse mode, automated chunking for long-form messages (>4000 chars)

### AI & LLM Integration
- **Engine / Runtime:** [Ollama](https://ollama.com/) (local inference API)
- **Model:** `Qwen 2.5 (1.5B)` fine-tuned/prompted via custom `Modelfile`
- **Prompt Engineering & Validation:** Structured JSON Output enforcement (`format: "json"`, temperature 0), fallback regex JSON parser, regex-based numeric and entity guards
- **Hybrid Verification Pipeline:** 
  - Fast-path deterministic evaluation (exact match, rule-based extraction, unit normalization)
  - LLM semantic inference for open-ended professional/customs exam answers

### Configuration & Data Management
- **Environment Management:** `python-dotenv`
- **Data Serialization:** JSON (`questions.json` dataset with strict validation schemas)
  
---

## 🖼 Демонстрация (Demo)

> *Совет: сделай 5-секундную гифку через ScreenToGif или скриншот диалога с ботом и положи в папку `assets/demo.png`.*

![Демонстрация работы](assets/demo.png)

---

## 🚀 Быстрый старт (Getting Started)

### Предварительные требования
- **Python 3.10+**
- **Ollama** (установленная и запущенная локально)
- Windows 10/11 с доступом к PowerShell или командной строке (CMD)

---

### Установка и запуск

1. **Клонируйте репозиторий:**
bash

git clone https://github.com/nogcoJlHyx/Local-LLM-Telegram-Bot-exam-preparation.git

cd Local-LLM-Telegram-Bot-exam-preparation

2. **Создайте и активируйте виртуальное окружение:**
cmd

python -m venv .venv

.venv\Scripts\activate

3. **Установите зависимости:**
cmd

pip install -r requirements.txt

4. **Загрузите модель в Ollama:**
cmd

ollama pull qwen2.5:1.5b

   *(Опционально: создайте кастомную модель через Modelfile: `ollama create exam_checker -f Modelfile`)*

5. **Настройте переменные окружения:**
cmd

copy .env.example .env
   Откройте `.env` и укажите ваш `BOT_TOKEN` от Telegram BotFather, а также свой Telegram ID в списке `ALLOWED_USERS` в `bot.py`.

6. **Запустите бота:**
cmd

python bot.py

---

## 📁 Структура проекта (Architecture)
text

Local-LLM-Telegram-Bot-exam-preparation/

├── assets/ # Медиафайлы, скриншоты диалогов и демонстрация для гитхаба

│ └── demo.png # Скриншот демонстрации работы экзаменатора

├── .env.example # Шаблон переменных окружения (токен Telegram, URL инференса)

├── .gitignore # Исключение конфиденциальных данных (.env) и виртуального окружения (.venv)

├── Modelfile # Конфигурация локальной модели (системные промпты и параметры для Ollama)

├── bot.py # Основная точка входа бота: FSM, диспетчеризация aiogram и обработка сообщений

├── checker.py # Двухуровневый модуль валидации ответов: Fast Checks (Regex) + Ollama API

├── questions.json # База экзаменационных вопросов с критериями проверки и ключами оценивания

└── requirements.txt # Зависимости проекта (aiogram, requests, python-dotenv)

## 👤 Автор (Author)
- GitHub: [@nogcoJlHyx](https://github.com/nogcoJlHyx)
- Telegram: [@nodcoJlHyx](https://t.me/nodcoJlHyx)
