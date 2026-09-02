"""Barra de filtros compartilhada pelos painéis e pelas telas de cadastro.

Vivia dentro de indicadores.py. Passou para cá quando a mesma caixa de
marcação múltipla precisou aparecer também na tela de Vagas Abertas — duplicar
o CSS e o comportamento em dois lugares garantiria que um dia divergissem.
"""

from __future__ import annotations

CSS_FILTROS = """<style>
.ind-filtros{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 14px}
.ind-filtro{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:8px 14px;min-width:150px}
.ind-filtro label{display:block;font-size:10px;font-weight:700;color:#9ca3af;
  text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px}
.ind-filtro select{width:100%;border:0;background:transparent;outline:none;
  color:#111827;font-size:13px;font-weight:600;cursor:pointer}
.ind-limpar{font-size:12px;color:#6b7280;text-decoration:none;padding:0 4px}
.ind-limpar:hover{color:#111827}
/* caixa de marcação múltipla */
.ind-multi{position:relative}
.ind-multi.tem-selecao{border-color:#c9ced6;box-shadow:0 0 0 2px rgba(213,0,50,.10)}
.ind-multi-botao{width:100%;display:flex;align-items:center;justify-content:space-between;
  gap:6px;border:0;background:transparent;padding:0;cursor:pointer;
  color:#111827;font-size:13px;font-weight:600;text-align:left;font-family:inherit}
.ind-multi-botao span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ind-multi-botao i{font-style:normal;color:#6b7280;font-size:11px;flex:none}
.ind-multi-painel{position:absolute;z-index:60;top:calc(100% + 6px);left:0;min-width:100%;
  max-width:280px;background:#fff;border:1px solid #e1e3e7;border-radius:10px;
  box-shadow:0 12px 30px rgba(0,0,0,.16);padding:8px}
.ind-multi-painel[hidden]{display:none}
.ind-multi-acoes{display:flex;gap:6px;margin-bottom:6px}
.ind-multi-acoes button{flex:1;border:1px solid #e1e3e7;background:#fff;border-radius:6px;
  padding:4px 6px;font-size:10px;font-weight:700;color:#4b5158;cursor:pointer;font-family:inherit}
.ind-multi-acoes button:hover{background:#f5f6f8}
.ind-multi-itens{max-height:220px;overflow:auto}
.ind-multi-item{display:flex;align-items:center;gap:7px;padding:5px 6px;border-radius:6px;
  font-size:12px;font-weight:500;color:#22252a;cursor:pointer;white-space:nowrap}
.ind-multi-item:hover{background:#f5f6f8}
.ind-multi-item input{margin:0;flex:none}
.ind-multi-aplicar{width:100%;margin-top:7px;border:0;border-radius:7px;background:#111827;
  color:#fff;padding:6px;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit}
.ind-multi-aplicar:hover{background:#000}
</style>"""


# Comportamento das caixas: abrir, marcar vários e aplicar de uma vez. Enviar a
# cada clique recarregaria a página no meio da escolha.
JS_FILTROS = """<script>
(function () {
  var form = document.getElementById('indFiltros');
  if (!form || form.dataset.pronto) return;
  form.dataset.pronto = '1';

  function fecharTodos(exceto) {
    form.querySelectorAll('.ind-multi-painel').forEach(function (p) {
      if (p !== exceto) p.hidden = true;
    });
  }

  form.querySelectorAll('.ind-multi').forEach(function (caixa) {
    var botao = caixa.querySelector('.ind-multi-botao');
    var painel = caixa.querySelector('.ind-multi-painel');

    botao.addEventListener('click', function (ev) {
      ev.stopPropagation();
      var abrindo = painel.hidden;
      fecharTodos(painel);
      painel.hidden = !abrindo;
    });

    painel.addEventListener('click', function (ev) { ev.stopPropagation(); });

    painel.querySelectorAll('[data-multi]').forEach(function (b) {
      b.addEventListener('click', function () {
        var marcar = b.dataset.multi === 'todos';
        painel.querySelectorAll('input[type=checkbox]').forEach(function (c) {
          c.checked = marcar;
        });
      });
    });

    painel.querySelector('.ind-multi-aplicar').addEventListener('click', function () {
      form.submit();
    });
  });

  // clicar fora aplica o que foi marcado, em vez de descartar em silêncio
  document.addEventListener('click', function () {
    var aberto = form.querySelector('.ind-multi-painel:not([hidden])');
    if (!aberto) return;
    fecharTodos();
    if (aberto.dataset.mudou === '1') form.submit();
  });
  form.querySelectorAll('.ind-multi-painel input[type=checkbox]').forEach(function (c) {
    c.addEventListener('change', function () {
      c.closest('.ind-multi-painel').dataset.mudou = '1';
    });
  });
  form.querySelectorAll('[data-multi]').forEach(function (b) {
    b.addEventListener('click', function () {
      b.closest('.ind-multi-painel').dataset.mudou = '1';
    });
  });
})();
</script>"""


def lista_sel(valor) -> list[str]:
    """Aceita string ou lista e devolve sempre lista, sem vazios.

    Os filtros passaram a aceitar mais de um valor; as rotas antigas ainda
    mandam string única, e os dois formatos precisam conviver.
    """
    if valor is None:
        return []
    if isinstance(valor, str):
        return [valor] if valor.strip() else []
    return [str(v) for v in valor if str(v).strip()]


def caixa_multi(nome: str, rotulo: str, opcoes: list[tuple[str, str]],
                 selecionados: list[str], rotulo_vazio: str = "Todos") -> str:
    """Caixa de filtro com marcação múltipla.

    Um <select multiple> nativo obriga a segurar Ctrl e não deixa enviar o
    formulário a cada clique. Aqui a caixa abre um painel de marcação e só
    aplica ao fechar, então dá para escolher vários meses de uma vez.
    """
    marcados = [v for v, _ in opcoes if v in selecionados]
    rotulos = {v: l for v, l in opcoes}
    if not marcados:
        resumo = rotulo_vazio
    elif len(marcados) == 1:
        resumo = rotulos.get(marcados[0], marcados[0])
    else:
        resumo = f"{rotulos.get(marcados[0], marcados[0])} +{len(marcados) - 1}"

    itens = "".join(
        f'<label class="ind-multi-item">'
        f'<input type="checkbox" name="{nome}" value="{v}"'
        f'{" checked" if v in selecionados else ""}><span>{l}</span></label>'
        for v, l in opcoes
    )
    return f"""
  <div class="ind-filtro ind-multi{' tem-selecao' if marcados else ''}">
    <label>{rotulo}</label>
    <button type="button" class="ind-multi-botao" title="{len(marcados)} selecionado(s)">
      <span>{resumo}</span><i>▾</i>
    </button>
    <div class="ind-multi-painel" hidden>
      <div class="ind-multi-acoes">
        <button type="button" data-multi="todos">Marcar todos</button>
        <button type="button" data-multi="nenhum">Limpar</button>
      </div>
      <div class="ind-multi-itens">{itens}</div>
      <button type="button" class="ind-multi-aplicar">Aplicar</button>
    </div>
  </div>"""


