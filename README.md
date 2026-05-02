# Telegram Bot (Aiogram v3 + Webhook)

Python + Aiogram v3 негізіндегі дүкен боты. Webhook арқылы жұмыс істейді.

## Орнату

```bash
pip install -r requirements.txt
```

## Орта айнымалылары (.env)

```
TELEGRAM_BOT_TOKEN=...       # @BotFather-дан
ADMIN_TELEGRAM_IDS=123,456   # Үтірмен бөлінген admin Telegram ID-лер
DATABASE_URL=postgresql://...  # PostgreSQL байланыс URL
WEBHOOK_URL=https://your-domain.com/webhook  # Сыртқы домен + /webhook
WEBHOOK_PATH=/webhook         # Webhook жолы (сервер ішінде)
PORT=8080                     # Тыңдайтын порт
```

## Іске қосу

```bash
python bot.py
```

## Railway-де деплой

1. `railway.app` сайтына тіркеліңіз
2. New Project → GitHub repo немесе Empty Project
3. PostgreSQL қосыңыз (New → Database → PostgreSQL)
4. Орта айнымалыларын қосыңыз (Variables бөлімінде)
5. `WEBHOOK_URL` = `https://your-app.railway.app/webhook`
6. Deploy

## Дерекқор схемасы

Бұл бот қазіргі жобаның дерекқор схемасын (Drizzle ORM арқылы жасалған) пайдаланады.
Кестелер: users, accounts, categories, products, product_keys, transactions, topup_requests, settings.

Жаңа дерекқорға schema жасау үшін негізгі жобада:
```bash
pnpm --filter @workspace/db run push
```
