#!/bin/zsh
# Запуск бота из папки проекта: ./start.sh
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
if [ ! -f .env ]; then
  echo "Нет .env — скопируй .env.example в .env и заполни"; exit 1
fi
exec .venv/bin/python -m app.main
