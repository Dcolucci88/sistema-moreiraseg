@echo off
setlocal

echo === REMOVENDO AMBIENTE ANTIGO (.venv) ===
rmdir /s /q .venv 2>nul

echo === CRIANDO NOVO AMBIENTE VIRTUAL COM PYTHON 3.12 REAL ===
"C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe" -m venv .venv

echo === ATIVANDO NOVO AMBIENTE ===
call .venv\Scripts\activate

echo === ATUALIZANDO PIP ===
python -m pip install --upgrade pip

echo === INSTALANDO DEPENDENCIAS DO requirements.txt ===
pip install -r requirements.txt

echo === AMBIENTE PRONTO COM PYTHON 3.12! ===
pause

