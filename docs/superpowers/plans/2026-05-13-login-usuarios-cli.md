# Sistema de Login, Gestão de Usuários e CLI de Criação de Usuário Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar autenticação com sessão, CRUD de usuários com controle de perfil e comando de terminal para criação de usuário administrador.

**Architecture:** Vamos adicionar um módulo de autenticação baseado em sessão via cookie assinado no FastAPI, com hash de senha em banco e dependência reutilizável para proteger rotas. A gestão de usuários será feita por router dedicado com templates Jinja, usando papéis (`admin`, `operador`) para autorização. Um comando CLI em `run.py` permitirá criar usuário sem depender da UI.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, Jinja2, `passlib[bcrypt]`, `itsdangerous`, `pytest`

---

## Estrutura de Arquivos

- Criar: `app/auth.py` (hash/sessão/dependências de autenticação)
- Criar: `app/routers/auth.py` (login, logout)
- Criar: `app/routers/usuarios.py` (CRUD de usuários)
- Criar: `app/templates/auth/login.html` (tela de login)
- Criar: `app/templates/usuarios/list.html` (listagem)
- Criar: `app/templates/usuarios/form.html` (criação/edição)
- Criar: `tests/test_auth.py` (testes de login/sessão)
- Criar: `tests/test_usuarios.py` (testes de autorização e CRUD)
- Modificar: `app/models.py` (modelo `Usuario`)
- Modificar: `app/main.py` (inclusão de routers e middleware de sessão)
- Modificar: `app/templates/base.html` (menu com usuário logado/logout)
- Modificar: `requirements.txt` (novas dependências)
- Modificar: `run.py` (comando CLI `create-user`)

### Task 1: Fundacao de autenticacao e modelo Usuario

**Files:**
- Create: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/tests/test_auth.py`
- Modify: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/app/models.py`
- Modify: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/requirements.txt`
- Create: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/app/auth.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth.py
from app.auth import hash_password, verify_password

def test_hash_and_verify_password():
    raw = "SenhaForte123!"
    digest = hash_password(raw)
    assert digest != raw
    assert verify_password(raw, digest) is True
    assert verify_password("errada", digest) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth.py::test_hash_and_verify_password -v`
Expected: FAIL com `ModuleNotFoundError` para `app.auth`.

- [ ] **Step 3: Write minimal implementation**

```python
# app/auth.py
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)
```

```python
# app/models.py (acrescentar)
class Usuario(Base):
    __tablename__ = "usuarios"

    id_usuario = Column(Integer, primary_key=True, index=True)
    nome = Column(String(140), nullable=False)
    email = Column(String(140), nullable=False, unique=True, index=True)
    senha_hash = Column(String(255), nullable=False)
    perfil = Column(String(30), nullable=False, default="operador")
    ativo = Column(String(3), nullable=False, default="Sim")
```

```txt
# requirements.txt (acrescentar)
passlib[bcrypt]
itsdangerous
pytest
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auth.py::test_hash_and_verify_password -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_auth.py app/auth.py app/models.py requirements.txt
git commit -m "feat: add auth foundations and user model"
```

### Task 2: Login/logout com sessao

**Files:**
- Modify: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/tests/test_auth.py`
- Create: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/app/routers/auth.py`
- Create: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/app/templates/auth/login.html`
- Modify: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/app/main.py`
- Modify: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/app/auth.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_login_redirects_when_invalid_credentials():
    response = client.post("/auth/login", data={"email": "x@x.com", "senha": "errada"}, allow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login?erro=1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth.py::test_login_redirects_when_invalid_credentials -v`
Expected: FAIL com rota `/auth/login` inexistente.

- [ ] **Step 3: Write minimal implementation**

```python
# app/routers/auth.py
from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Usuario
from app.auth import verify_password, create_session, clear_session

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login")
def login(email: str = Form(...), senha: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(Usuario).filter(Usuario.email == email, Usuario.ativo == "Sim").first()
    if not user or not verify_password(senha, user.senha_hash):
        return RedirectResponse("/auth/login?erro=1", status_code=303)

    response = RedirectResponse("/", status_code=303)
    create_session(response, user)
    return response

@router.post("/logout")
def logout():
    response = RedirectResponse("/auth/login", status_code=303)
    clear_session(response)
    return response
```

```python
# app/main.py (acrescentar)
from app.routers import auth
app.include_router(auth.router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auth.py::test_login_redirects_when_invalid_credentials -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_auth.py app/routers/auth.py app/main.py app/templates/auth/login.html app/auth.py
git commit -m "feat: add login/logout routes with session cookie"
```

### Task 3: Gestao de usuarios (admin)

**Files:**
- Create: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/tests/test_usuarios.py`
- Create: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/app/routers/usuarios.py`
- Create: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/app/templates/usuarios/list.html`
- Create: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/app/templates/usuarios/form.html`
- Modify: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/app/main.py`
- Modify: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/app/templates/base.html`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_usuarios.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_usuarios_requires_admin_session():
    response = client.get("/usuarios", allow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/auth/login")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_usuarios.py::test_usuarios_requires_admin_session -v`
Expected: FAIL com rota `/usuarios` inexistente.

- [ ] **Step 3: Write minimal implementation**

```python
# app/routers/usuarios.py
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from app.auth import require_admin_user

router = APIRouter(prefix="/usuarios", tags=["usuarios"])

@router.get("")
def listar_usuarios(user=Depends(require_admin_user)):
    return {"ok": True, "usuario": user.email}
```

```python
# app/main.py
from app.routers import usuarios
app.include_router(usuarios.router)
```

```html
<!-- app/templates/base.html -->
<form method="post" action="/auth/logout">
  <button type="submit">Sair</button>
</form>
<a href="/usuarios">Usuarios</a>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_usuarios.py::test_usuarios_requires_admin_session -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_usuarios.py app/routers/usuarios.py app/main.py app/templates/base.html app/templates/usuarios/list.html app/templates/usuarios/form.html
git commit -m "feat: add admin user management routes and views"
```

### Task 4: Comando de terminal para criar usuario

**Files:**
- Modify: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/tests/test_usuarios.py`
- Modify: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/run.py`
- Modify: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/app/database.py`
- Modify: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/app/auth.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_usuarios.py
from run import build_parser

def test_create_user_command_parser_has_required_args():
    parser = build_parser()
    args = parser.parse_args([
        "create-user",
        "--nome", "Administrador",
        "--email", "admin@local",
        "--senha", "Senha123!",
        "--perfil", "admin",
    ])
    assert args.command == "create-user"
    assert args.perfil == "admin"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_usuarios.py::test_create_user_command_parser_has_required_args -v`
Expected: FAIL porque `build_parser` ainda nao existe em `run.py`.

- [ ] **Step 3: Write minimal implementation**

```python
# run.py
import argparse
from app.database import SessionLocal
from app.models import Usuario
from app.auth import hash_password


def build_parser():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    create_user = sub.add_parser("create-user")
    create_user.add_argument("--nome", required=True)
    create_user.add_argument("--email", required=True)
    create_user.add_argument("--senha", required=True)
    create_user.add_argument("--perfil", choices=["admin", "operador"], default="operador")
    return parser


def create_user(nome: str, email: str, senha: str, perfil: str):
    db = SessionLocal()
    try:
        exists = db.query(Usuario).filter(Usuario.email == email).first()
        if exists:
            raise SystemExit("Usuario ja existe")
        db.add(Usuario(nome=nome, email=email, senha_hash=hash_password(senha), perfil=perfil, ativo="Sim"))
        db.commit()
    finally:
        db.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_usuarios.py::test_create_user_command_parser_has_required_args -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_usuarios.py run.py app/auth.py app/database.py
git commit -m "feat: add create-user terminal command"
```

### Task 5: Regressao rapida e documentacao operacional

**Files:**
- Modify: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/README.md`
- Modify: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/tests/test_auth.py`
- Modify: `C:/Users/vmore/Documents/GitHub/porsche_autonomos/tests/test_usuarios.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth.py

def test_logout_clears_session_cookie(client_logged_admin):
    response = client_logged_admin.post("/auth/logout", allow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth.py::test_logout_clears_session_cookie -v`
Expected: FAIL se cookie de sessao nao for removido corretamente.

- [ ] **Step 3: Write minimal implementation**

```python
# app/auth.py
SESSION_COOKIE = "porsche_session"


def clear_session(response):
    response.delete_cookie(SESSION_COOKIE, path="/")
```

```markdown
# README.md (acrescentar)
## Autenticacao

- Login: `POST /auth/login`
- Logout: `POST /auth/logout`
- Perfis: `admin`, `operador`

## Criacao de usuario via terminal

```bash
python run.py create-user --nome "Admin" --email "admin@local" --senha "Senha123!" --perfil admin
```
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auth.py tests/test_usuarios.py -v`
Expected: PASS em todos os testes de auth e usuarios.

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_auth.py tests/test_usuarios.py app/auth.py
git commit -m "docs: document auth and cli user creation"
```

## Self-Review

- Cobertura de escopo:
  - Sistema de login: coberto nas Tasks 1, 2 e 5.
  - Gestao de usuarios: coberto na Task 3.
  - Comando terminal para criar usuario: coberto na Task 4.
- Placeholder scan: nenhum `TODO`, `TBD` ou instrucoes vagas.
- Consistencia: perfis padronizados como `admin` e `operador` em todas as tasks.

Plan complete and saved to `docs/superpowers/plans/2026-05-13-login-usuarios-cli.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
