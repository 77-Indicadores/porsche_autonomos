"""Convite de acesso por e-mail: token de senha e envio.

Antes, criar um usuário exigia digitar uma senha no formulário e combiná-la com
a pessoa por fora — WhatsApp, na maioria das vezes. A senha ficava registrada
na conversa, quem criou a conhecia, e ninguém era obrigado a trocá-la.

Agora o sistema manda um link e a própria pessoa define a senha. Ninguém além
dela conhece a senha, em momento nenhum.

Regras que o token segue, as mesmas do dash_adl:

- no banco fica só o HASH do token. Quem tiver acesso à tabela não consegue
  entrar na conta de ninguém, porque o valor que vale está apenas no e-mail;
- validade curta, e uso único: usado ou vencido, não abre mais;
- token gerado com `secrets`, não com `random` — este último é previsível e
  não serve para nada que proteja acesso.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import (Column, DateTime, Integer, MetaData, String, Table,
                        insert, select, update)

from app.database import engine

metadata_acesso = MetaData()

usuario_token_senha = Table(
    "usuario_token_senha",
    metadata_acesso,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String(200), index=True),
    Column("token_hash", String(64), unique=True),
    Column("expira_em", DateTime),
    Column("usado_em", DateTime, nullable=True),
    Column("criado_em", DateTime),
    # "criacao" (primeiro acesso) ou "recuperacao": muda só o texto do e-mail
    Column("motivo", String(20)),
)

metadata_acesso.create_all(engine)

# Primeiro acesso tem prazo maior: a pessoa costuma receber o convite fora do
# horário de trabalho, e um link de 1 hora chega vencido na prática.
HORAS_CRIACAO = int(os.getenv("ACESSO_HORAS_CRIACAO", "48") or 48)
HORAS_RECUPERACAO = int(os.getenv("ACESSO_HORAS_RECUPERACAO", "2") or 2)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def gerar_token(email: str, motivo: str = "criacao") -> str:
    """Cria o token, guarda só o hash e devolve o valor que vai no e-mail."""
    token = secrets.token_urlsafe(32)
    horas = HORAS_CRIACAO if motivo == "criacao" else HORAS_RECUPERACAO
    agora = datetime.now()
    with engine.begin() as cx:
        # links anteriores da mesma pessoa deixam de valer: se o acesso foi
        # reenviado é porque o anterior não serviu, e deixá-lo vivo só amplia
        # a janela em que um link antigo ainda abre a conta
        cx.execute(
            update(usuario_token_senha)
            .where(usuario_token_senha.c.email == email)
            .where(usuario_token_senha.c.usado_em.is_(None))
            .values(usado_em=agora)
        )
        cx.execute(insert(usuario_token_senha), {
            "email": email,
            "token_hash": _hash(token),
            "expira_em": agora + timedelta(hours=horas),
            "usado_em": None,
            "criado_em": agora,
            "motivo": motivo,
        })
    return token


def validar_token(token: str) -> dict | None:
    """Devolve o registro se o token serve. None se não abre — e não diz por quê.

    A tela mostra uma mensagem só para inválido, vencido e já usado. Distinguir
    os casos conta a quem tem o link se ele já existiu, e isso não ajuda quem é
    dono da conta.
    """
    if not token:
        return None
    with engine.connect() as cx:
        linha = cx.execute(
            select(usuario_token_senha)
            .where(usuario_token_senha.c.token_hash == _hash(token))
        ).mappings().first()
    if not linha:
        return None
    if linha["usado_em"] is not None:
        return None
    if linha["expira_em"] and linha["expira_em"] < datetime.now():
        return None
    return dict(linha)


def marcar_usado(token: str) -> None:
    with engine.begin() as cx:
        cx.execute(
            update(usuario_token_senha)
            .where(usuario_token_senha.c.token_hash == _hash(token))
            .values(usado_em=datetime.now())
        )


# ─── envio ────────────────────────────────────────────────────────────────────

def smtp_configurado() -> bool:
    return bool(os.getenv("SMTP_HOST"))


def _enviar(destino: str, assunto: str, texto: str, html: str) -> None:
    host = os.getenv("SMTP_HOST")
    if not host:
        raise RuntimeError(
            "SMTP_HOST não configurado — sem isso o sistema não tem por onde "
            "enviar o convite de acesso.")
    porta = int(os.getenv("SMTP_PORT", "587") or 587)
    usuario = os.getenv("SMTP_USER")
    senha = os.getenv("SMTP_PASS")
    remetente = os.getenv("SMTP_FROM") or "Sistema Porsche <noreply@77indicadores.com.br>"

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = remetente
    msg["To"] = destino
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")

    if porta == 465:
        with smtplib.SMTP_SSL(host, porta, context=ssl.create_default_context(),
                              timeout=20) as s:
            if usuario and senha:
                s.login(usuario, senha)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, porta, timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            if usuario and senha:
                s.login(usuario, senha)
            s.send_message(msg)


def _html(titulo: str, chamada: str, link: str, rotulo_botao: str,
          validade: str, rodape: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f1f3f6;font-family:system-ui,-apple-system,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 16px">
    <tr><td align="center">
      <table width="480" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:10px;border:1px solid #e2e8f0;overflow:hidden">
        <tr>
          <td style="background:#0B0B0C;padding:24px 32px">
            <span style="font-size:20px;font-weight:900;letter-spacing:-.02em;color:#fff">PORSCHE</span>
            <span style="display:block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.14em;color:#8b909b;margin-top:4px">Carrera Cup Brasil · Sistema</span>
          </td>
        </tr>
        <tr>
          <td style="padding:32px">
            <h1 style="margin:0 0 8px;font-size:18px;font-weight:800;color:#0f172a">{titulo}</h1>
            <p style="margin:0 0 24px;font-size:14px;color:#64748b;line-height:1.6">{chamada}</p>
            <a href="{link}" style="display:inline-block;background:#D50032;color:#fff;font-size:14px;font-weight:700;padding:12px 28px;border-radius:7px;text-decoration:none">{rotulo_botao}</a>
            <p style="margin:24px 0 0;font-size:12px;color:#94a3b8;line-height:1.6">
              O link expira em <strong>{validade}</strong> e só pode ser usado uma vez.<br>
              {rodape}<br><br>
              Se o botão não funcionar, copie este endereço:<br>
              <span style="word-break:break-all">{link}</span>
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def enviar_convite(destino: str, nome: str, link: str) -> None:
    primeiro = (nome or "").strip().split(" ")[0] or "Olá"
    _enviar(
        destino,
        "Seu acesso ao Sistema Porsche foi criado",
        f"{primeiro}, seu acesso ao Sistema Porsche foi criado.\n\n"
        f"Defina sua senha pelo link abaixo (válido por {HORAS_CRIACAO} horas):\n{link}\n\n"
        f"Seu usuário é o próprio e-mail: {destino}\n\n"
        f"Se você não esperava este e-mail, ignore-o.",
        _html(
            "Seu acesso foi criado",
            f"{primeiro}, uma conta foi criada para você no Sistema Porsche. "
            f"Defina sua senha para entrar pela primeira vez. "
            f"Seu usuário é o próprio e-mail: <strong>{destino}</strong>.",
            link, "Definir minha senha", f"{HORAS_CRIACAO} horas",
            "Se você não esperava este e-mail, ignore-o."),
    )


def enviar_recuperacao(destino: str, nome: str, link: str) -> None:
    primeiro = (nome or "").strip().split(" ")[0] or "Olá"
    _enviar(
        destino,
        "Redefinição de senha — Sistema Porsche",
        f"{primeiro}, use o link abaixo para definir uma nova senha "
        f"(válido por {HORAS_RECUPERACAO} horas):\n{link}\n\n"
        f"Se não foi você, ignore este e-mail — sua senha continua a mesma.",
        _html(
            "Redefinição de senha",
            f"{primeiro}, recebemos um pedido para redefinir a senha desta conta.",
            link, "Definir nova senha", f"{HORAS_RECUPERACAO} horas",
            "Se não foi você, ignore este e-mail — sua senha continua a mesma."),
    )


def url_base(request) -> str:
    """Endereço público do sistema, para montar o link do e-mail.

    Atrás de proxy, request.base_url costuma vir como http://localhost:8000,
    que não abre para quem recebe. Por isso a variável de ambiente manda.
    """
    base = (os.getenv("APP_URL") or "").strip().rstrip("/")
    return base or str(request.base_url).rstrip("/")
