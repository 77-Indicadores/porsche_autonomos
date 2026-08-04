"""Indicadores de custo de autônomos – 3 dashboards JS-driven."""
import json as _json

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import FatoPilotoAutonomoProva, DimProva
from app.template_config import templates

router = APIRouter(tags=["indicadores_autonomo"])

# ── shared data fetcher ────────────────────────────────────────────────────────

def _fetch(db: Session) -> str:
    """Return deduplicated cost records as a JSON string."""
    fatos = (
        db.query(FatoPilotoAutonomoProva)
        .options(
            joinedload(FatoPilotoAutonomoProva.autonomo),
            joinedload(FatoPilotoAutonomoProva.piloto),
            joinedload(FatoPilotoAutonomoProva.etapa),
            joinedload(FatoPilotoAutonomoProva.carro),
            joinedload(FatoPilotoAutonomoProva.prova).joinedload(DimProva.tipo_prova),
        )
        .all()
    )
    seen: set = set()
    rows: list = []
    grupo_de: list = []  # (id_autonomo, id_etapa) de cada row, para o rateio
    for f in fatos:
        if not (f.valor_fechado_etapa or f.status_pagamento or f.id_autonomo_substituto):
            continue
        key = (f.id_etapa, f.id_autonomo, f.id_piloto, f.id_carro)
        if key in seen:
            continue
        seen.add(key)
        grupo_de.append((f.id_autonomo, f.id_etapa))
        et = f.etapa
        aut = f.autonomo
        pil = f.piloto
        car = f.carro
        rows.append({
            "etapa":      et.nome_etapa  if et  else "",
            "temporada":  et.temporada   if et  else "",
            "dt_inicio":  str(et.data_inicio) if et and et.data_inicio else "",
            "autonomo":   aut.nome_autonomo if aut else "",
            "piloto":     pil.nome_piloto   if pil else "",
            "piloto_id":  f.id_piloto,
            "carro_id":   f.id_carro or 0,
            "categoria":  (f.prova.tipo_prova.nome_tipo_prova if f.prova and f.prova.tipo_prova else None) or (car.categoria_padrao if car else "") or "",
            "valor":      float(f.valor_fechado_etapa or 0),
            "dias":       f.dias_trabalhados or 0,
            "status":     str(f.status_pagamento or ""),
            "forma":      str(f.forma_pagamento  or ""),
            "dt_pag":     str(f.data_pagamento   or ""),
            "foi_sub":    str(getattr(f, "foi_substituido", "") or ""),
            "id_sub":     f.id_autonomo_substituto or 0,
        })

    # Rateio: valor_fechado_etapa é o combinado da ETAPA. Quando o autônomo
    # atende mais de um carro na mesma etapa, o valor vem lançado em cada
    # linha e a soma duplicava o custo — divide pelo nº de carros atendidos.
    from collections import Counter
    n_por_grupo = Counter(grupo_de)
    for row, grupo in zip(rows, grupo_de):
        n = n_por_grupo[grupo]
        if n > 1 and row["valor"]:
            row["valor"] = round(row["valor"] / n, 2)
            row["rateado"] = n

    return _json.dumps(rows, ensure_ascii=False)


def _fetch_meta(db: Session) -> str:
    """Return etapas list and cobertura from composicao_padrao_equipe as JSON."""
    from sqlalchemy import text as _text
    try:
        etapa_rows = db.execute(_text(
            "SELECT id_etapa, nome_etapa, data_inicio, data_fim, temporada, status_etapa "
            "FROM dim_etapas ORDER BY data_inicio"
        )).fetchall()
        etapas = [{"id": r[0], "nome": r[1] or "", "dt_inicio": str(r[2] or ""),
                   "dt_fim": str(r[3] or ""), "temporada": str(r[4] or ""),
                   "status": str(r[5] or "")} for r in etapa_rows]
    except Exception:
        etapas = []
    try:
        cob_rows = db.execute(_text(
            "SELECT id_etapa, SUM(qtd_esperada) FROM composicao_padrao_equipe GROUP BY id_etapa"
        )).fetchall()
        cobertura = {str(r[0]): float(r[1] or 0) for r in cob_rows}
    except Exception:
        cobertura = {}
    return _json.dumps({"etapas": etapas, "cobertura": cobertura}, ensure_ascii=False)


def _fetch_equipe_geral(db: Session) -> str:
    """Fetch equipe_geral (Outras Equipes) para consolidar nos indicadores de custo."""
    from sqlalchemy import text as _text
    try:
        rows = db.execute(_text("""
            SELECT eg.custo_total, eg.tipo_documento,
                   e.nome_etapa, e.temporada, tp.nome_tipo_prova
            FROM equipe_geral eg
            LEFT JOIN dim_etapas e ON e.id_etapa = eg.id_etapa
            LEFT JOIN dim_categorias pr ON pr.id_prova = eg.id_prova
            LEFT JOIN dim_tipos_categoria tp ON tp.id_tipo_prova = pr.id_tipo_prova
        """)).fetchall()
        recs = [{
            "etapa":     r[2] or "",
            "temporada": str(r[3] or ""),
            "categoria": r[4] or "Outras Equipes",
            "valor":     float(r[0] or 0),
            "forma":     str(r[1] or ""),
            "eg":        1,
        } for r in rows]
    except Exception:
        recs = []
    return _json.dumps(recs, ensure_ascii=False)


# ── Page 1 – Visão Geral ───────────────────────────────────────────────────────

def _build_geral(records_js: str, meta_js: str, eg_js: str = "[]") -> str:
    css = """<style>
.vg{--red:#d71920;--green:#15946c;--yellow:#e59a12;--muted:#6f7886;
  --border:#e3e7ee;--shadow:0 8px 24px rgba(24,32,44,.07);--radius:16px;
  font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#18202c}
.vg *{box-sizing:border-box}
.vg button,.vg select{font:inherit}
.vg-filters{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr)) 100px;
  gap:10px;margin-bottom:14px}
.vg-filter{background:#fff;border:1px solid var(--border);border-radius:12px;
  padding:9px 11px;box-shadow:0 3px 10px rgba(24,32,44,.04)}
.vg-filter label{display:block;font-size:9px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.08em;margin-bottom:4px;font-weight:700}
.vg-filter select{width:100%;border:0;outline:0;background:transparent;
  font-size:12px;color:#18202c;font-weight:600;cursor:pointer;appearance:none}
.vg-reset{border:1px solid var(--border);background:#fff;border-radius:12px;
  font-weight:700;color:#555f6d;cursor:pointer;font-size:12px;padding:0 12px}
.vg-reset:hover{background:#f5f7fa}
.vg-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));
  gap:11px;margin-bottom:11px}
.vg-kpi{background:#fff;border:1px solid var(--border);border-radius:var(--radius);
  padding:14px 15px 13px;box-shadow:var(--shadow);position:relative;overflow:hidden;min-height:104px}
.vg-kpi::after{content:"";width:76px;height:76px;border-radius:50%;
  position:absolute;right:-28px;top:-28px;background:var(--tint,#f4f6f9)}
.vg-kpi-top{display:flex;align-items:center;justify-content:space-between;position:relative;z-index:1}
.vg-kpi-title{font-size:10px;font-weight:800;text-transform:uppercase;
  letter-spacing:.055em;color:var(--muted)}
.vg-icon{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;
  background:var(--iconbg,#f1f3f6);color:var(--iconcolor,#18202c);font-size:13px;font-weight:900}
.vg-kpi-value{margin-top:9px;font-size:21px;font-weight:800;letter-spacing:-.04em;
  position:relative;z-index:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.vg-kpi-foot{margin-top:3px;color:var(--muted);font-size:10px;position:relative;z-index:1}
.vg-delta{color:var(--green);background:#eaf8f3;padding:2px 5px;
  border-radius:999px;font-weight:800;font-size:9px}
.vg-grid-main{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(240px,.85fr);
  gap:11px;margin-bottom:11px}
.vg-grid-bottom{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) minmax(230px,.8fr);
  gap:11px}
.vg-card{background:#fff;border:1px solid var(--border);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:14px 15px;min-width:0}
.vg-card-title{margin:0 0 2px;font-size:13px;font-weight:800}
.vg-card-sub{color:var(--muted);font-size:10px;margin-bottom:11px}
.vg-ch-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:10px}
.vg-legend{display:flex;align-items:center;gap:10px;font-size:9px;color:var(--muted)}
.vg-legend span{display:inline-flex;align-items:center;gap:4px}
.vg-legend i{width:8px;height:8px;border-radius:50%;display:inline-block}
.vg-chart-wrap{overflow-x:auto}
.vg-svg{display:block;overflow:visible;font-family:Inter,ui-sans-serif,system-ui,sans-serif}
.vg-svg text{font-size:9px;fill:#6f7886}
.vg-svg .blbl{fill:#3f4854;font-weight:700;font-size:9px}
.vg-donut-wrap{display:flex;flex-direction:column;align-items:center;gap:12px;padding:4px 0}
.vg-donut-host{position:relative;width:140px;height:140px;flex-shrink:0}
.vg-donut{position:absolute;inset:0;border-radius:50%}
.vg-donut::after{content:"";position:absolute;inset:24px;background:#fff;
  border-radius:50%;box-shadow:0 0 0 1px #eef1f5}
.vg-donut-center{position:absolute;inset:0;z-index:2;display:flex;flex-direction:column;
  align-items:center;justify-content:center;text-align:center;pointer-events:none}
.vg-donut-center strong{font-size:20px;letter-spacing:-.04em;font-weight:800}
.vg-donut-center span{color:var(--muted);font-size:9px}
.vg-donut-legend{display:grid;gap:7px;width:100%;padding:0 4px}
.vg-donut-row{display:flex;align-items:center;justify-content:space-between;
  font-size:10px;color:var(--muted)}
.vg-donut-row strong{color:#18202c;font-size:10px}
.vg-dot{width:7px;height:7px;border-radius:50%;display:inline-block;margin-right:6px;flex-shrink:0}
.vg-hbars{display:grid;gap:12px}
.vg-hbar-lbl{display:flex;justify-content:space-between;font-size:10px;margin-bottom:4px}
.vg-hbar-lbl span{font-weight:700;color:#18202c}
.vg-hbar-lbl small{color:var(--muted)}
.vg-hbar-track{height:9px;background:#eef1f5;border-radius:999px;overflow:hidden}
.vg-hbar-fill{height:100%;border-radius:999px}
.vg-rank{display:grid;gap:9px}
.vg-rank-item{display:grid;grid-template-columns:20px minmax(0,1fr) auto;gap:7px;align-items:center}
.vg-rank-no{width:20px;height:20px;border-radius:6px;background:#f0f2f6;
  display:grid;place-items:center;font-size:9px;font-weight:800;color:#616a77;flex-shrink:0}
.vg-rank-name strong{display:block;font-size:10px;font-weight:700;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.vg-rank-name small{display:block;font-size:8px;color:var(--muted);margin-top:1px}
.vg-rank-val{font-size:10px;font-weight:800;white-space:nowrap}
.vg-rank-bar{grid-column:2/4;height:4px;background:#eef1f5;border-radius:999px;
  overflow:hidden;margin-top:-4px}
.vg-rank-fill{height:100%;border-radius:999px;
  background:linear-gradient(90deg,var(--red),#f25a5f)}
.vg-cov-box{background:linear-gradient(135deg,#171b23,#242a35);
  border-radius:13px;padding:13px;color:#fff;margin-bottom:9px}
.vg-cov-top{display:flex;justify-content:space-between;align-items:flex-start;
  gap:6px;margin-bottom:8px}
.vg-cov-top strong{font-size:11px;font-weight:700;line-height:1.3}
.vg-cov-top span{font-size:9px;color:#bac1cc;white-space:nowrap}
.vg-cov-value{font-size:22px;font-weight:800;letter-spacing:-.04em;margin-bottom:8px}
.vg-progress{height:6px;border-radius:999px;background:rgba(255,255,255,.12);overflow:hidden;margin-bottom:6px}
.vg-progress-fill{display:block;height:100%;border-radius:999px;
  background:linear-gradient(90deg,#ff4d54,#d71920)}
.vg-cov-meta{display:flex;justify-content:space-between;font-size:9px;color:#c7ccd5}
.vg-mini-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px}
.vg-mini{border:1px solid var(--border);background:#fafbfc;border-radius:10px;padding:9px 10px}
.vg-mini span{display:block;font-size:8px;text-transform:uppercase;
  color:var(--muted);font-weight:800;letter-spacing:.06em;margin-bottom:4px}
.vg-mini strong{display:block;font-size:16px;font-weight:800}
@media(max-width:1150px){
  .vg-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .vg-filters{grid-template-columns:repeat(2,minmax(120px,1fr)) 90px}
  .vg-grid-bottom{grid-template-columns:1fr 1fr}}
@media(max-width:820px){
  .vg-grid-main,.vg-grid-bottom{grid-template-columns:1fr}
  .vg-kpis{grid-template-columns:1fr 1fr}}
</style>"""

    html = """<div class="vg">
<div class="vg-filters">
  <div class="vg-filter"><label>Temporada</label><select id="vgYear"></select></div>
  <div class="vg-filter"><label>Etapa</label><select id="vgEtapa"></select></div>
  <div class="vg-filter"><label>Categoria</label><select id="vgCat"></select></div>
  <div class="vg-filter"><label>Status pagamento</label><select id="vgStatus"></select></div>
  <button class="vg-reset" onclick="vgReset()">Limpar</button>
</div>
<section class="vg-kpis">
  <article class="vg-kpi" style="--tint:#fff1f2;--iconbg:#fff0f1;--iconcolor:#c5161c">
    <div class="vg-kpi-top"><span class="vg-kpi-title">Custo consolidado</span>
      <div class="vg-icon">R$</div></div>
    <div class="vg-kpi-value" id="vgK0">—</div>
    <div class="vg-kpi-foot" id="vgK0f"></div></article>
  <article class="vg-kpi" style="--tint:#eef5ff;--iconbg:#edf4fd;--iconcolor:#2673c8">
    <div class="vg-kpi-top"><span class="vg-kpi-title">Custo médio/carro</span>
      <div class="vg-icon">#</div></div>
    <div class="vg-kpi-value" id="vgK1">—</div>
    <div class="vg-kpi-foot" id="vgK1f"></div></article>
  <article class="vg-kpi" style="--tint:#ebf8f4;--iconbg:#e7f7f1;--iconcolor:#11835f">
    <div class="vg-kpi-top"><span class="vg-kpi-title">Valor pago</span>
      <div class="vg-icon">✓</div></div>
    <div class="vg-kpi-value" id="vgK2">—</div>
    <div class="vg-kpi-foot" id="vgK2f"></div></article>
  <article class="vg-kpi" style="--tint:#f2effc;--iconbg:#f0edfb;--iconcolor:#7259be">
    <div class="vg-kpi-top"><span class="vg-kpi-title">Autônomos ativos</span>
      <div class="vg-icon">&#9823;</div></div>
    <div class="vg-kpi-value" id="vgK4">—</div>
    <div class="vg-kpi-foot" id="vgK4f"></div></article>
  <article class="vg-kpi" style="--tint:#eef8fb;--iconbg:#ebf7fa;--iconcolor:#247f91">
    <div class="vg-kpi-top"><span class="vg-kpi-title">Carros atendidos</span>
      <div class="vg-icon">&#9635;</div></div>
    <div class="vg-kpi-value" id="vgK5">—</div>
    <div class="vg-kpi-foot" id="vgK5f"></div></article>
  <article class="vg-kpi" style="--tint:#f2f4f8;--iconbg:#edf0f5;--iconcolor:#4e5967">
    <div class="vg-kpi-top"><span class="vg-kpi-title">Custo médio/dia</span>
      <div class="vg-icon">D</div></div>
    <div class="vg-kpi-value" id="vgK6">—</div>
    <div class="vg-kpi-foot" id="vgK6f"></div></article>
  <article class="vg-kpi" style="--tint:#fff0f1;--iconbg:#ffeded;--iconcolor:#bd151b">
    <div class="vg-kpi-top"><span class="vg-kpi-title">Substituições</span>
      <div class="vg-icon">&#8635;</div></div>
    <div class="vg-kpi-value" id="vgK7">—</div>
    <div class="vg-kpi-foot" id="vgK7f"></div></article>
</section>
<section class="vg-grid-main">
  <article class="vg-card">
    <div class="vg-ch-head">
      <div><h2 class="vg-card-title">Custo por etapa</h2>
        <p class="vg-card-sub">Total (barras) e custo médio/carro (linha)</p></div>
      <div class="vg-legend">
        <span><i style="background:#d71920"></i>Total</span>
        <span><i style="background:#9ea7b4"></i>Média/carro</span>
      </div>
    </div>
    <div class="vg-chart-wrap"><div id="vgEtChart"></div></div>
  </article>
  <article class="vg-card">
    <h2 class="vg-card-title">Formas de pagamento</h2>
    <p class="vg-card-sub">Participação NF / RPA / Recibo · meta 60% NF</p>
    <div class="vg-donut-wrap">
      <div class="vg-donut-host">
        <div class="vg-donut" id="vgDn"></div>
        <div class="vg-donut-center"><strong id="vgDnPct">—</strong><span>via NF</span></div>
      </div>
      <div class="vg-donut-legend" id="vgDnLeg"></div>
    </div>
    <div id="vgMeta"></div>
  </article>
</section>
<section class="vg-grid-bottom">
  <article class="vg-card">
    <h2 class="vg-card-title">Custo por categoria</h2>
    <p class="vg-card-sub">Valor total por série</p>
    <div class="vg-hbars" id="vgCatBars"></div>
  </article>
  <article class="vg-card">
    <h2 class="vg-card-title">Top 5 pilotos</h2>
    <p class="vg-card-sub">Custo total de autônomos vinculados</p>
    <div class="vg-rank" id="vgRank"></div>
  </article>
  <article class="vg-card">
    <h2 class="vg-card-title">Próxima etapa</h2>
    <p class="vg-card-sub">Cobertura planejada</p>
    <div id="vgProx"><p style="color:#9ca3af;font-size:11px">Calculando...</p></div>
  </article>
</section>
</div>"""

    js = r"""
const vgEl=id=>document.getElementById(id);
function vgFmt(v){
  if(v===null||v===undefined||isNaN(v))return"—";
  if(v>=1000000)return"R$ "+(v/1000000).toFixed(1)+" mi";
  if(v>=1000)return"R$ "+(v/1000).toFixed(0)+" mil";
  return"R$ "+Math.round(v).toLocaleString("pt-BR");
}
function vgTc(s){return s?s.split(" ").map(w=>w?w[0].toUpperCase()+w.slice(1).toLowerCase():"").join(" "):""}
function vgNormSt(s){
  if(!s||s.trim()==="")return"Sem status";
  const l=s.toLowerCase();
  if(l==="pago"||l==="paga")return"Pago";
  if(l.includes("pend"))return"Pendente";
  return s;
}
function vgFillSel(id,vals,lbl){
  const el=vgEl(id);if(!el)return;
  el.innerHTML='<option value="">'+lbl+'</option>'+vals.map(v=>'<option value="'+v+'">'+v+'</option>').join("");
}
function vgSetup(){
  const R=VG_RECORDS.concat(VG_EG);
  const years=[...new Set(R.map(r=>r.temporada).filter(Boolean))].sort().reverse();
  const etapas=[...new Set(R.map(r=>r.etapa).filter(Boolean))].sort();
  const cats=[...new Set(R.map(r=>r.categoria).filter(Boolean))].sort();
  const sts=[...new Set(R.map(r=>vgNormSt(r.status)))].filter(Boolean).sort();
  vgFillSel("vgYear",years,"Todas as temporadas");
  vgFillSel("vgEtapa",etapas,"Todas as etapas");
  vgFillSel("vgCat",cats,"Todas as categorias");
  vgFillSel("vgStatus",sts,"Todos os status");
  ["vgYear","vgEtapa","vgCat","vgStatus"].forEach(id=>{const el=vgEl(id);if(el)el.addEventListener("change",vgRender)});
}
function vgFiltered(){
  const yr=vgEl("vgYear")?.value||"",et=vgEl("vgEtapa")?.value||"",
        ct=vgEl("vgCat")?.value||"",st=vgEl("vgStatus")?.value||"";
  const fato=VG_RECORDS.filter(r=>
    (!yr||r.temporada===yr)&&(!et||r.etapa===et)&&
    (!ct||r.categoria===ct)&&(!st||vgNormSt(r.status)===st));
  // Outras Equipes (equipe_geral) — não tem status; segue os demais filtros
  const eg=VG_EG.filter(r=>
    (!yr||r.temporada===yr)&&(!et||r.etapa===et)&&(!ct||r.categoria===ct));
  return fato.concat(eg);
}
function vgReset(){["vgYear","vgEtapa","vgCat","vgStatus"].forEach(id=>{const el=vgEl(id);if(el)el.value=""});vgRender()}

function vgKPIs(d){
  const fato=d.filter(r=>!r.eg);
  const total=d.reduce((s,r)=>s+(r.valor||0),0);         // consolidado (inclui Outras Equipes)
  const fatoTotal=fato.reduce((s,r)=>s+(r.valor||0),0);  // só autônomos
  const egTotal=total-fatoTotal;
  const carros=new Set(fato.map(r=>r.carro_id).filter(Boolean));
  const pilotos=new Set(fato.map(r=>r.piloto_id).filter(Boolean));
  const media=carros.size?fatoTotal/carros.size:0;
  const pago=total; // todos os lançamentos representam pagamentos já realizados
  const auts=new Set(fato.map(r=>r.autonomo).filter(Boolean)).size;
  const dias=fato.reduce((s,r)=>s+(r.dias||0),0);
  const mediaDia=dias?fatoTotal/dias:0;
  const subs=fato.filter(r=>((r.foi_sub||"").trim().toLowerCase()==="sim")||r.id_sub).length;
  const set=(id,v,f)=>{const e=vgEl(id);if(e)e.textContent=v;const fe=vgEl(id+"f");if(fe)fe.innerHTML=f||""};
  set("vgK0",vgFmt(total),carros.size+" carros · "+pilotos.size+" pilotos"+(egTotal>0?" · Outras Equipes "+vgFmt(egTotal):""));
  set("vgK1",vgFmt(media),carros.size+" carros atendidos");
  set("vgK2",vgFmt(pago),"valor efetivamente pago");
  set("vgK4",auts,pilotos.size+" pilotos");
  set("vgK5",carros.size,"carros cobertos na seleção");
  set("vgK6",vgFmt(mediaDia),"por profissional/dia");
  set("vgK7",subs,fato.length?"taxa "+(subs/fato.length*100).toFixed(1)+"%":"");
}

function vgEtapaChart(d){
  const etMap={};
  d.forEach(r=>{
    if(!r.etapa)return;
    if(!etMap[r.etapa])etMap[r.etapa]={tot:0,pilotos:new Set(),dt:r.dt_inicio||""};
    etMap[r.etapa].tot+=(r.valor||0);
    if(r.piloto_id)etMap[r.etapa].pilotos.add(r.piloto_id);
  });
  const rows=Object.entries(etMap).sort((a,b)=>a[1].dt.localeCompare(b[1].dt))
    .map(([et,v])=>({et,tot:v.tot,med:v.pilotos.size?v.tot/v.pilotos.size:0}));
  const wrap=vgEl("vgEtChart");if(!wrap)return;
  if(!rows.length){wrap.innerHTML='<p style="color:#9ca3af;font-size:12px;padding:16px 0">Sem dados</p>';return}
  const W=720,H=205,pL=52,pR=16,pT=22,pB=36;
  const maxV=Math.max(...rows.map(r=>r.tot),1);
  const slotW=(W-pL-pR)/rows.length;
  const bW=Math.min(slotW*.55,50);
  const yS=v=>pT+(1-v/maxV)*(H-pT-pB);
  const fmt=v=>v>=1000000?(v/1000000).toFixed(1)+"mi":v>=1000?Math.round(v/1000)+"k":Math.round(v).toString();
  let grid="",bars="",lbls="",line="",dots="",xlbl="";
  for(let i=0;i<=4;i++){
    const v=maxV*i/4,y=yS(v).toFixed(1);
    grid+='<line x1="'+pL+'" y1="'+y+'" x2="'+(W-pR)+'" y2="'+y+'" stroke="'+(i===4?"#e4e8ee":"#eef1f5")+'"/>';
    grid+='<text x="'+(pL-4)+'" y="'+(+y+3.5).toFixed(1)+'" text-anchor="end">'+fmt(v)+'</text>';
  }
  rows.forEach((r,i)=>{
    const cx=pL+i*slotW+slotW/2,bx=(cx-bW/2).toFixed(1),by=yS(r.tot).toFixed(1);
    const bh=Math.max(H-pB-yS(r.tot),2).toFixed(1);
    bars+='<rect x="'+bx+'" y="'+by+'" width="'+bW.toFixed(1)+'" height="'+bh+'" rx="5" fill="#d71920"/>';
    if(r.tot>0)lbls+='<text x="'+cx.toFixed(1)+'" y="'+(yS(r.tot)-4).toFixed(1)+'" text-anchor="middle" class="blbl">'+fmt(r.tot)+'</text>';
    const ly=yS(r.med).toFixed(1);
    line+=(i===0?"M":"L")+cx.toFixed(1)+","+ly+" ";
    dots+='<circle cx="'+cx.toFixed(1)+'" cy="'+ly+'" r="3.5" fill="#fff" stroke="#9ea7b4" stroke-width="2"/>';
    const sn=r.et.replace(/^\d+ET\d+\s*[-–]\s*/,"").slice(0,10);
    xlbl+='<text x="'+cx.toFixed(1)+'" y="'+(H-6)+'" text-anchor="middle">'+sn+'</text>';
  });
  wrap.innerHTML='<svg class="vg-svg" viewBox="0 0 '+W+' '+H+'" width="100%" style="min-height:'+H+'px">'+
    grid+'<line x1="'+pL+'" y1="'+pT+'" x2="'+pL+'" y2="'+(H-pB)+'" stroke="#e4e8ee"/>'+
    '<line x1="'+pL+'" y1="'+(H-pB)+'" x2="'+(W-pR)+'" y2="'+(H-pB)+'" stroke="#e4e8ee"/>'+
    bars+lbls+'<polyline fill="none" stroke="#9ea7b4" stroke-width="2.5" stroke-linejoin="round" points="'+line.trim()+'"/>'+
    dots+xlbl+'</svg>';
}

function vgFormaNorm(s){
  s=(s||"").trim().toUpperCase();
  if(s==="NF"||s==="NOTA FISCAL")return"NF";
  if(s==="RPA")return"RPA";
  if(s==="RECIBO")return"Recibo";
  return s?s.charAt(0)+s.slice(1).toLowerCase():"";
}
function vgFormas(d){
  // participação por forma de pagamento (nº de contratações), autônomos + Outras Equipes
  const COL={"NF":"#15946c","RPA":"#e59a12","Recibo":"#2673c8"};
  const cnt={};let tot=0;
  d.forEach(r=>{const k=vgFormaNorm(r.forma);if(!k)return;cnt[k]=(cnt[k]||0)+1;tot++;});
  const dn=vgEl("vgDn"),pc=vgEl("vgDnPct"),leg=vgEl("vgDnLeg"),mt=vgEl("vgMeta");
  if(!tot){
    if(dn)dn.style.background="#eef1f5";
    if(pc)pc.textContent="—";
    if(leg)leg.innerHTML='<div style="color:#9ca3af;font-size:11px">Sem forma de pagamento registrada</div>';
    if(mt)mt.innerHTML="";
    return;
  }
  const base=["NF","RPA","Recibo"];
  const order=base.filter(k=>cnt[k]).concat(Object.keys(cnt).filter(k=>!base.includes(k)));
  let acc=0;const seg=[];
  order.forEach(k=>{const p=cnt[k]/tot*100;seg.push((COL[k]||"#9ca3af")+" "+acc.toFixed(2)+"% "+(acc+p).toFixed(2)+"%");acc+=p;});
  if(dn)dn.style.background="conic-gradient("+seg.join(",")+")";
  const nfPct=(cnt["NF"]||0)/tot*100;
  if(pc)pc.textContent=nfPct.toFixed(0)+"%";
  if(leg)leg.innerHTML=order.map(k=>
    '<div class="vg-donut-row"><span><span class="vg-dot" style="background:'+(COL[k]||"#9ca3af")+'"></span>'+k+'</span>'+
    '<strong>'+(cnt[k]/tot*100).toFixed(0)+'% ('+cnt[k]+')</strong></div>').join("");
  const meta=60,diff=nfPct-meta;
  if(mt)mt.innerHTML='<div style="margin-top:8px;padding-top:8px;border-top:1px solid #eef1f5;font-size:11.5px;display:flex;justify-content:space-between;align-items:center">'+
    '<span><b>Meta NF</b> '+meta+'% · Realizado '+nfPct.toFixed(0)+'%</span>'+
    '<span style="font-weight:800;color:'+(diff>=0?"#15946c":"#d71920")+'">'+(diff>=0?"+":"")+diff.toFixed(0)+'%</span></div>';
}

function vgCatBars(d){
  const cm={};d.forEach(r=>{const k=r.categoria||"Sem categoria";cm[k]=(cm[k]||0)+(r.valor||0)});
  const rows=Object.entries(cm).sort((a,b)=>b[1]-a[1]);
  const maxV=rows[0]?.[1]||1;
  const COLS=["#d71920","#374151","#7157c8","#e59a12","#15946c"];
  const el=vgEl("vgCatBars");if(!el)return;
  if(!rows.length){el.innerHTML='<p style="color:#9ca3af;font-size:12px">Sem dados</p>';return}
  el.innerHTML=rows.map(([k,v],i)=>
    '<div><div class="vg-hbar-lbl"><span>'+k+'</span><small>'+vgFmt(v)+'</small></div>'+
    '<div class="vg-hbar-track"><div class="vg-hbar-fill" style="width:'+(v/maxV*100).toFixed(1)+'%;background:'+COLS[i%COLS.length]+'"></div></div></div>').join("");
}

function vgRanking(d){
  const pm={};
  d.filter(r=>!r.eg).forEach(r=>{
    const k=r.piloto||"—";
    if(!pm[k])pm[k]={val:0,cats:new Set()};
    pm[k].val+=(r.valor||0);
    if(r.categoria)pm[k].cats.add(r.categoria);
  });
  const rows=Object.entries(pm).sort((a,b)=>b[1].val-a[1].val).slice(0,5);
  const maxV=rows[0]?.[1].val||1;
  const el=vgEl("vgRank");if(!el)return;
  if(!rows.length){el.innerHTML='<p style="color:#9ca3af;font-size:12px">Sem dados</p>';return}
  el.innerHTML=rows.map(([n,v],i)=>
    '<div class="vg-rank-item">'+
    '<div class="vg-rank-no">'+(i+1)+'</div>'+
    '<div class="vg-rank-name"><strong title="'+n+'">'+vgTc(n)+'</strong><small>'+([...v.cats].join(" · ")||"—")+'</small></div>'+
    '<div class="vg-rank-val">'+vgFmt(v.val)+'</div>'+
    '<div class="vg-rank-bar"><div class="vg-rank-fill" style="width:'+(v.val/maxV*100).toFixed(1)+'%"></div></div>'+
    '</div>').join("");
}

function vgProxEtapa(){
  const today=new Date().toISOString().slice(0,10);
  const etapas=(VG_META.etapas||[]).filter(e=>e.dt_inicio).sort((a,b)=>a.dt_inicio.localeCompare(b.dt_inicio));
  const prox=etapas.find(e=>e.dt_inicio>today);
  const el=vgEl("vgProx");if(!el)return;
  if(!prox){el.innerHTML='<p style="color:#9ca3af;font-size:11px">Nenhuma etapa futura cadastrada.</p>';return}
  const alocados=new Set(VG_RECORDS.filter(r=>r.etapa===prox.nome).map(r=>r.autonomo).filter(Boolean)).size;
  const esperados=VG_META.cobertura[String(prox.id)]||0;
  const pct=esperados?Math.min(alocados/esperados*100,100):0;
  const dtFmt=s=>s?s.slice(8,10)+"/"+s.slice(5,7):"—";
  const subs=VG_RECORDS.filter(r=>r.etapa===prox.nome&&r.foi_sub==="Sim").length;
  const carros=new Set(VG_RECORDS.filter(r=>r.etapa===prox.nome&&r.carro_id).map(r=>r.carro_id)).size;
  const shortNm=prox.nome.replace(/^\d+ET\d+\s*[-–]\s*/,"").slice(0,18)||prox.nome;
  el.innerHTML='<div class="vg-cov-box">'+
    '<div class="vg-cov-top"><strong>'+shortNm+'</strong><span>'+dtFmt(prox.dt_inicio)+(prox.dt_fim?"–"+dtFmt(prox.dt_fim):"")+'</span></div>'+
    '<div class="vg-cov-value">'+(esperados?pct.toFixed(1)+"%":alocados+" alocados")+'</div>'+
    (esperados?'<div class="vg-progress"><span class="vg-progress-fill" style="width:'+pct.toFixed(1)+'%"></span></div>'+
    '<div class="vg-cov-meta"><span>'+alocados+' alocados</span><span>'+esperados+' esperados</span></div>':"")+
    '</div>'+
    '<div class="vg-mini-grid">'+
    '<div class="vg-mini"><span>Temporada</span><strong>'+(prox.temporada||"—")+'</strong></div>'+
    '<div class="vg-mini"><span>Carros cobertos</span><strong>'+carros+'</strong></div>'+
    '<div class="vg-mini"><span>Trocas reg.</span><strong>'+subs+'</strong></div>'+
    '<div class="vg-mini"><span>Status etapa</span><strong>'+(prox.status||"—")+'</strong></div>'+
    '</div>';
}

function vgRender(){
  const d=vgFiltered();
  vgKPIs(d);vgEtapaChart(d);vgFormas(d);vgCatBars(d);vgRanking(d);vgProxEtapa();
}
vgSetup();vgRender();
"""
    return (
        f"<script>const VG_RECORDS={records_js};const VG_META={meta_js};const VG_EG={eg_js};</script>"
        + css + html
        + "<script>" + js + "</script>"
    )


# ── Page 2 – Custos & Comparativos ────────────────────────────────────────────

def _fetch_sede(db: Session) -> str:
    """Fetch autonomo_sede_lancamentos totals for cost composition."""
    from sqlalchemy import text as _text
    try:
        rows = db.execute(_text(
            "SELECT substr(competencia, 1, 4) AS ano, SUM(valor) FROM autonomo_sede_lancamentos "
            "WHERE competencia IS NOT NULL AND competencia <> '' GROUP BY substr(competencia, 1, 4)"
        )).fetchall()
        by_year = {str(r[0]): float(r[1] or 0) for r in rows}
    except Exception:
        by_year = {}
    return _json.dumps({"by_year": by_year, "total": sum(by_year.values())}, ensure_ascii=False)


def _build_evolucao(records_js: str, sede_js: str = "{}", eg_js: str = "[]") -> str:
    css = """<style>
.ev{--red:#d71920;--green:#15946c;--yellow:#e59a12;--muted:#6f7886;
  --border:#e3e7ee;--shadow:0 8px 24px rgba(24,32,44,.07);--radius:16px;
  font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#18202c}
.ev *{box-sizing:border-box}
.ev button,.ev select{font:inherit}
.ev-filters{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr)) 100px;
  gap:10px;margin-bottom:14px}
.ev-filter{background:#fff;border:1px solid var(--border);border-radius:12px;
  padding:9px 11px;box-shadow:0 3px 10px rgba(24,32,44,.04)}
.ev-filter label{display:block;font-size:9px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.08em;margin-bottom:4px;font-weight:700}
.ev-filter select{width:100%;border:0;outline:0;background:transparent;
  font-size:12px;color:#18202c;font-weight:600;cursor:pointer;appearance:none}
.ev-reset{border:1px solid var(--border);background:#fff;border-radius:12px;
  font-weight:700;color:#555f6d;cursor:pointer;font-size:12px;padding:0 12px}
.ev-reset:hover{background:#f5f7fa}
.ev-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));
  gap:11px;margin-bottom:11px}
.ev-kpi{background:#fff;border:1px solid var(--border);border-radius:var(--radius);
  padding:14px 15px 12px;box-shadow:var(--shadow);position:relative;overflow:hidden;min-height:104px}
.ev-kpi::after{content:"";width:76px;height:76px;border-radius:50%;position:absolute;
  right:-28px;top:-28px;background:var(--tint,#f4f6f9)}
.ev-kpi-top{display:flex;align-items:center;justify-content:space-between;position:relative;z-index:1}
.ev-kpi-title{font-size:10px;font-weight:800;text-transform:uppercase;
  letter-spacing:.055em;color:var(--muted)}
.ev-icon{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;
  background:var(--iconbg,#f1f3f6);color:var(--iconcolor,#18202c);font-size:12px;font-weight:900}
.ev-kpi-value{margin-top:9px;font-size:20px;font-weight:800;letter-spacing:-.04em;
  position:relative;z-index:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ev-kpi-foot{margin-top:3px;color:var(--muted);font-size:10px;position:relative;z-index:1;display:flex;align-items:center;gap:5px;flex-wrap:wrap}
.ev-delta{padding:2px 5px;border-radius:999px;font-weight:800;font-size:9px}
.ev-delta.ok{color:#107455;background:#e9f7f2}
.ev-delta.neg{color:#b11c22;background:#fff0f1}
.ev-delta.warn{color:#ae7105;background:#fff5df}
.ev-grid-main{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(300px,.9fr);
  gap:11px;margin-bottom:11px}
.ev-grid-2{display:grid;grid-template-columns:1fr 1fr;gap:11px;margin-bottom:11px}
.ev-card{background:#fff;border:1px solid var(--border);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:14px 15px;min-width:0}
.ev-card-title{margin:0 0 2px;font-size:13px;font-weight:800}
.ev-card-sub{color:var(--muted);font-size:10px;margin-bottom:11px}
.ev-ch-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:10px}
.ev-legend{display:flex;align-items:center;gap:10px;font-size:9px;color:var(--muted);flex-wrap:wrap}
.ev-legend span{display:inline-flex;align-items:center;gap:4px}
.ev-legend i{width:8px;height:8px;border-radius:50%;display:inline-block}
.ev-chart-wrap{overflow-x:auto}
.ev-svg{display:block;overflow:visible;font-family:Inter,ui-sans-serif,system-ui,sans-serif}
.ev-svg text{font-size:9px;fill:#6f7886}
.ev-svg .blbl{fill:#3f4854;font-weight:700;font-size:9px}
.ev-var-box{background:linear-gradient(135deg,#171b23,#242a35);color:#fff;
  border-radius:13px;padding:14px;margin-bottom:11px}
.ev-var-box small{display:block;font-size:9px;color:#b7bec8;text-transform:uppercase;letter-spacing:.08em}
.ev-var-value{font-size:30px;font-weight:800;margin:8px 0 4px;letter-spacing:-.04em}
.ev-var-text{font-size:10px;color:#c6ccd5;margin-bottom:12px}
.ev-var-prog{height:7px;border-radius:999px;background:rgba(255,255,255,.13);overflow:hidden}
.ev-var-prog span{display:block;height:100%;border-radius:999px;
  background:linear-gradient(90deg,#ff5359,#d71920)}
.ev-var-meta{display:flex;justify-content:space-between;margin-top:7px;font-size:9px;color:#c6ccd5}
.ev-cost-list{display:grid;gap:9px}
.ev-cost-item{border:1px solid var(--border);background:#fafbfc;border-radius:11px;padding:10px}
.ev-cost-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}
.ev-cost-item strong{display:block;font-size:10px}
.ev-cost-item small{display:block;font-size:9px;color:var(--muted);margin-top:2px}
.ev-cost-val{font-size:14px!important;font-weight:800;color:#18202c!important;white-space:nowrap}
.ev-mini-prog{height:5px;margin-top:8px;background:#edf0f4;border-radius:999px;overflow:hidden}
.ev-mini-prog span{display:block;height:100%;border-radius:999px}
.ev-proj{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-bottom:11px}
.ev-proj-card{border:1px solid var(--border);border-radius:12px;background:#fafbfc;padding:11px}
.ev-proj-card span{display:block;font-size:8px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;font-weight:800}
.ev-proj-card strong{display:block;font-size:18px;margin-top:4px;font-weight:800}
.ev-proj-card small{display:block;margin-top:3px;font-size:9px;color:var(--muted)}
.ev-tbl-wrap{overflow:auto;border:1px solid var(--border);border-radius:11px}
.ev-tbl{width:100%;border-collapse:collapse;min-width:750px;font-size:10px}
.ev-tbl thead th{text-align:left;padding:9px 10px;background:#f7f8fa;color:#606977;
  text-transform:uppercase;font-size:8px;letter-spacing:.06em;
  border-bottom:1px solid var(--border);white-space:nowrap}
.ev-tbl tbody td{padding:9px 10px;border-bottom:1px solid #edf0f4;white-space:nowrap}
.ev-tbl tbody tr:last-child td{border-bottom:0}
.ev-tbl tbody tr:hover{background:#fafbfc}
.ev-st{display:inline-flex;align-items:center;gap:4px;padding:4px 7px;
  border-radius:999px;font-size:8px;font-weight:800}
.ev-st::before{content:"";width:5px;height:5px;border-radius:50%}
.ev-st-ok{color:#107455;background:#e9f7f2}.ev-st-ok::before{background:#15946c}
.ev-st-warn{color:#a96b02;background:#fff4de}.ev-st-warn::before{background:#e59a12}
.ev-st-bad{color:#ad151b;background:#fff0f1}.ev-st-bad::before{background:#d71920}
@media(max-width:1100px){
  .ev-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .ev-filters{grid-template-columns:repeat(2,minmax(120px,1fr)) 90px}
  .ev-grid-main,.ev-grid-2{grid-template-columns:1fr}}
@media(max-width:760px){.ev-kpis{grid-template-columns:1fr 1fr}}
</style>"""

    html = """<div class="ev">
<div class="ev-filters">
  <div class="ev-filter"><label>Temporada</label><select id="evYear"></select></div>
  <div class="ev-filter"><label>Etapa</label><select id="evEtapa"></select></div>
  <div class="ev-filter"><label>Categoria</label><select id="evCat"></select></div>
  <div class="ev-filter"><label>Tipo de custo</label>
    <select id="evTipo">
      <option value="">Todos os custos</option>
      <option value="carro">Equipe por carro</option>
      <option value="geral">Autônomos s/ carro</option>
    </select>
  </div>
  <button class="ev-reset" onclick="evReset()">Limpar</button>
</div>
<section class="ev-kpis">
  <article class="ev-kpi" style="--tint:#fff1f2;--iconbg:#fff0f1;--iconcolor:#c5161c">
    <div class="ev-kpi-top"><span class="ev-kpi-title">Custo total seleção</span>
      <div class="ev-icon">R$</div></div>
    <div class="ev-kpi-value" id="evK0">—</div>
    <div class="ev-kpi-foot" id="evK0f"></div></article>
  <article class="ev-kpi" style="--tint:#eef5ff;--iconbg:#edf4fd;--iconcolor:#2673c8">
    <div class="ev-kpi-top"><span class="ev-kpi-title">Custo médio/carro</span>
      <div class="ev-icon">#</div></div>
    <div class="ev-kpi-value" id="evK1">—</div>
    <div class="ev-kpi-foot" id="evK1f"></div></article>
  <article class="ev-kpi" style="--tint:#f2effc;--iconbg:#f0edfb;--iconcolor:#7259be">
    <div class="ev-kpi-top"><span class="ev-kpi-title">Custo médio/autônomo</span>
      <div class="ev-icon">A</div></div>
    <div class="ev-kpi-value" id="evK2">—</div>
    <div class="ev-kpi-foot" id="evK2f"></div></article>
  <article class="ev-kpi" style="--tint:#fff7e9;--iconbg:#fff6e5;--iconcolor:#c88408">
    <div class="ev-kpi-top"><span class="ev-kpi-title">Maior custo / etapa</span>
      <div class="ev-icon">↑</div></div>
    <div class="ev-kpi-value" id="evK3">—</div>
    <div class="ev-kpi-foot" id="evK3f"></div></article>
  <article class="ev-kpi" style="--tint:#ebf8f4;--iconbg:#e7f7f1;--iconcolor:#11835f">
    <div class="ev-kpi-top"><span class="ev-kpi-title">Custo médio/etapa</span>
      <div class="ev-icon">🏁</div></div>
    <div class="ev-kpi-value" id="evK4">—</div>
    <div class="ev-kpi-foot" id="evK4f"></div></article>
  <article class="ev-kpi" style="--tint:#eef8fb;--iconbg:#ebf7fa;--iconcolor:#247f91">
    <div class="ev-kpi-top"><span class="ev-kpi-title">Custo médio/dia</span>
      <div class="ev-icon">D</div></div>
    <div class="ev-kpi-value" id="evK5">—</div>
    <div class="ev-kpi-foot" id="evK5f"></div></article>
  <article class="ev-kpi" style="--tint:#f2f4f8;--iconbg:#edf0f5;--iconcolor:#4e5967">
    <div class="ev-kpi-top"><span class="ev-kpi-title">Outras Equipes</span>
      <div class="ev-icon">EG</div></div>
    <div class="ev-kpi-value" id="evK6">—</div>
    <div class="ev-kpi-foot" id="evK6f"></div></article>
  <article class="ev-kpi" style="--tint:#fff0f1;--iconbg:#ffeded;--iconcolor:#bd151b">
    <div class="ev-kpi-top"><span class="ev-kpi-title">Autônomos sede</span>
      <div class="ev-icon">S</div></div>
    <div class="ev-kpi-value" id="evK7">—</div>
    <div class="ev-kpi-foot" id="evK7f"></div></article>
</section>
<section class="ev-grid-main">
  <article class="ev-card">
    <div class="ev-ch-head">
      <div><h2 class="ev-card-title">Custo médio por carro por etapa</h2>
        <p class="ev-card-sub">Comparativo normalizado entre temporadas</p></div>
      <div class="ev-legend" id="evLeg"></div>
    </div>
    <div class="ev-chart-wrap"><div id="evBarChart"></div></div>
  </article>
  <article class="ev-card">
    <div class="ev-var-box" id="evVarBox">
      <small>Composição do custo consolidado</small>
      <div class="ev-var-value" id="evVarVal">—</div>
      <div class="ev-var-text">Soma dos custos da equipe vinculada aos carros, equipe geral e autônomos da sede.</div>
      <div class="ev-var-prog"><span id="evVarProg" style="width:0%"></span></div>
      <div class="ev-var-meta"><span id="evVarL">—</span><span id="evVarR">—</span></div>
    </div>
    <div class="ev-cost-list" id="evCostList"></div>
  </article>
</section>
<section class="ev-grid-2">
  <article class="ev-card">
    <div class="ev-ch-head">
      <div><h2 class="ev-card-title">Custo por categoria</h2>
        <p class="ev-card-sub">Distribuição entre categorias e equipe geral</p></div>
    </div>
    <div class="ev-chart-wrap"><div id="evCatChart"></div></div>
  </article>
  <article class="ev-card">
    <div class="ev-ch-head">
      <div><h2 class="ev-card-title">Custo total × carros por etapa</h2>
        <p class="ev-card-sub">Efeito do grid no custo total</p></div>
    </div>
    <div class="ev-proj" id="evProjCards"></div>
    <div class="ev-chart-wrap"><div id="evGridChart"></div></div>
  </article>
</section>
<article class="ev-card">
  <div class="ev-ch-head">
    <div><h2 class="ev-card-title">Detalhamento por etapa</h2>
      <p class="ev-card-sub">Custos realizados, carros e indicadores normalizados</p></div>
  </div>
  <div class="ev-tbl-wrap">
    <table class="ev-tbl">
      <thead><tr>
        <th>Etapa</th><th>Temporada</th><th>Carros</th>
        <th>Custo realizado</th><th>Participação</th>
        <th>Custo médio/carro</th><th>Custo médio/dia</th><th>Situação</th>
      </tr></thead>
      <tbody id="evTblBody"></tbody>
    </table>
  </div>
</article>
</div>"""

    js = r"""
const evEl=id=>document.getElementById(id);
function evFmt(v){
  if(!v&&v!==0)return"—";
  if(v>=1000000)return"R$ "+(v/1000000).toFixed(2)+" mi";
  if(v>=1000)return"R$ "+(v/1000).toFixed(0)+" mil";
  return"R$ "+Math.round(v).toLocaleString("pt-BR");
}
function evFmtSh(v){
  if(!v&&v!==0)return"—";
  if(v>=1000000)return"R$ "+(v/1000000).toFixed(1)+"mi";
  if(v>=1000)return"R$ "+(v/1000).toFixed(0)+"k";
  return"R$ "+Math.round(v).toString();
}

function evFillSel(id,vals,lbl){
  const el=evEl(id);if(!el)return;
  el.innerHTML=(lbl?'<option value="">'+lbl+'</option>':'')+vals.map(v=>'<option value="'+v+'">'+v+'</option>').join("");
}
function evSetup(){
  const R=EV_RECORDS;
  const years=[...new Set(R.map(r=>r.temporada).filter(Boolean))].sort().reverse();
  const etapas=[...new Set(R.map(r=>r.etapa).filter(Boolean))].sort();
  const cats=[...new Set(R.map(r=>r.categoria).filter(Boolean))].sort();
  evFillSel("evYear",years,"Todas as temporadas");
  evFillSel("evEtapa",etapas,"Todas as etapas");
  evFillSel("evCat",cats,"Todas as categorias");
  ["evYear","evEtapa","evCat","evTipo"].forEach(id=>{const el=evEl(id);if(el)el.addEventListener("change",evRender)});
}
function evFiltered(){
  const yr=evEl("evYear")?.value||"",et=evEl("evEtapa")?.value||"",
        ct=evEl("evCat")?.value||"",tp=evEl("evTipo")?.value||"";
  return EV_RECORDS.filter(r=>{
    if(yr&&r.temporada!==yr)return false;
    if(et&&r.etapa!==et)return false;
    if(ct&&r.categoria!==ct)return false;
    if(tp==="carro"&&!r.carro_id)return false;
    if(tp==="geral"&&r.carro_id)return false;
    return true;
  });
}
function evReset(){["evYear","evEtapa","evCat","evTipo"].forEach(id=>{const el=evEl(id);if(el)el.value=""});evRender()}

function evMediaPorCarro(data,temporada){
  const etapas={};
  data.filter(r=>r.temporada===temporada&&r.carro_id).forEach(r=>{
    if(!etapas[r.etapa])etapas[r.etapa]={val:0,carros:new Set(),dt:r.dt_inicio||""};
    etapas[r.etapa].val+=(r.valor||0);
    etapas[r.etapa].carros.add(r.carro_id);
  });
  return Object.entries(etapas).sort((a,b)=>a[1].dt.localeCompare(b[1].dt))
    .map(([et,v])=>({et,total:v.val,media:v.carros.size?v.val/v.carros.size:0,carros:v.carros.size,dt:v.dt}));
}

function evKPIs(d){
  const total=d.reduce((s,r)=>s+(r.valor||0),0);
  const carros=new Set(d.map(r=>r.carro_id).filter(Boolean));
  const auts=new Set(d.map(r=>r.autonomo).filter(Boolean));
  const mediaC=carros.size?total/carros.size:0;
  const mediaA=auts.size?total/auts.size:0;
  const dias=d.reduce((s,r)=>s+(r.dias||0),0);
  const mediaD=dias?total/dias:0;
  const geral=d.filter(r=>!r.carro_id).reduce((s,r)=>s+(r.valor||0),0);
  const sedeTotal=EV_SEDE.total||0;
  // Outras Equipes (tabela equipe_geral), respeitando os filtros do dashboard
  const _yr=evEl("evYear")?.value||"",_et=evEl("evEtapa")?.value||"",_ct=evEl("evCat")?.value||"";
  const outrasEquipes=(typeof EV_EG!=="undefined"?EV_EG:[])
    .filter(r=>(!_yr||r.temporada===_yr)&&(!_et||r.etapa===_et)&&(!_ct||r.categoria===_ct))
    .reduce((s,r)=>s+(r.valor||0),0);
  // Por etapa
  const etMap={};
  d.forEach(r=>{if(r.etapa)etMap[r.etapa]=(etMap[r.etapa]||0)+(r.valor||0)});
  const etVals=Object.entries(etMap);
  const maxEt=etVals.length?etVals.reduce((a,b)=>a[1]>b[1]?a:b):["—",0];
  const avgEt=etVals.length?etVals.reduce((s,[,v])=>s+v,0)/etVals.length:0;
  const set=(id,v,f)=>{const e=evEl(id);if(e)e.textContent=v;const fe=evEl(id+"f");if(fe)fe.innerHTML=f||""};
  set("evK0",evFmt(total),carros.size+" carros · "+auts.size+" autônomos");
  set("evK1",evFmtSh(mediaC),carros.size+" carros atendidos");
  set("evK2",evFmt(mediaA),auts.size+" profissionais");
  set("evK3",evFmtSh(maxEt[1]),maxEt[0]||"—");
  set("evK4",evFmt(avgEt),etVals.length+" etapas");
  set("evK5",evFmtSh(mediaD),"por profissional/dia");
  const consolid=total+sedeTotal+outrasEquipes;
  const oePct=consolid?(outrasEquipes/consolid*100):0;
  set("evK6",evFmt(outrasEquipes),oePct.toFixed(1)+"% do consolidado");
  const sedePct=total&&sedeTotal?(sedeTotal/total*100):0;
  set("evK7",evFmt(sedeTotal),sedePct?sedePct.toFixed(1)+"% do consolidado":"");
  // Composition panel
  const vinculados=total-geral;
  const pctVinc=total?(vinculados/total*100):0;
  const vv=evEl("evVarVal");if(vv)vv.textContent=evFmt(total);
  const vp=evEl("evVarProg");if(vp)vp.style.width=pctVinc.toFixed(1)+"%";
  const vl=evEl("evVarL");if(vl)vl.textContent=pctVinc.toFixed(1)+"% ligados aos carros";
  const vr=evEl("evVarR");if(vr)vr.textContent=(100-pctVinc).toFixed(1)+"% apoio e sede";
  const cl=evEl("evCostList");
  if(cl){
    const sedeBarW=total?(sedeTotal/total*100).toFixed(1):0;
    const geralBarW=total?(geral/total*100).toFixed(1):0;
    const oeBarW=total?(outrasEquipes/total*100).toFixed(1):0;
    cl.innerHTML=[
      ["Equipe vinculada aos carros","Autônomos com piloto e carro",vinculados,pctVinc.toFixed(1),"#d71920"],
      ["Apoio (autônomos s/ carro)","Autônomos sem vínculo direto ao carro",geral,geralBarW,"#7b61c9"],
      ["Autônomos da sede","Lançamentos da sede",sedeTotal,sedeBarW,"#2878d0"],
      ["Outras Equipes","Tabela Outras Equipes (equipe_geral)",outrasEquipes,oeBarW,"#15946c"],
    ].map(([nm,sub,val,pct,col])=>
      '<div class="ev-cost-item">'+
      '<div class="ev-cost-top"><div><strong>'+nm+'</strong><small>'+sub+'</small></div>'+
      '<span class="ev-cost-val">'+evFmt(val)+'</span></div>'+
      '<div class="ev-mini-prog"><span style="width:'+pct+'%;background:'+col+'"></span></div>'+
      '</div>').join("");
  }
}

function evBarChart(d){
  const years=[...new Set(d.map(r=>r.temporada).filter(Boolean))].sort();
  const y1=years[0]||"",y2=years[1]||"";
  const m1=evMediaPorCarro(d,y1),m2=evMediaPorCarro(d,y2);
  const legEl=evEl("evLeg");
  if(legEl)legEl.innerHTML=[y1,y2].filter(Boolean).map((yr,i)=>
    '<span><i style="background:'+(i===0?"#aeb5c1":"#d71920")+'"></i>'+yr+'</span>').join("");
  const allEt=[...new Set([...m1.map(r=>r.et),...m2.map(r=>r.et)])].sort();
  const wrap=evEl("evBarChart");if(!wrap)return;
  if(!allEt.length){wrap.innerHTML='<p style="color:#9ca3af;font-size:12px;padding:16px 0">Sem dados</p>';return}
  const map1=Object.fromEntries(m1.map(r=>[r.et,r.media]));
  const map2=Object.fromEntries(m2.map(r=>[r.et,r.media]));
  const allV=[...Object.values(map1),...Object.values(map2)].filter(Boolean);
  const maxV=Math.max(...allV,1);
  const W=Math.max(600,allEt.length*90+60),H=220,pL=55,pR=14,pT=22,pB=36;
  const slotW=(W-pL-pR)/allEt.length,bw=Math.min(slotW*.35,28);
  const yS=v=>pT+(1-v/maxV)*(H-pT-pB);
  const fmt=v=>v>=1000?Math.round(v/1000)+"k":Math.round(v).toString();
  let grid="",bars="",lbls="",xl="";
  for(let i=0;i<=4;i++){
    const v=maxV*i/4,y=yS(v).toFixed(1);
    grid+='<line x1="'+pL+'" y1="'+y+'" x2="'+(W-pR)+'" y2="'+y+'" stroke="'+(i===4?"#e4e8ee":"#eef1f5")+'"/>';
    grid+='<text x="'+(pL-4)+'" y="'+(+y+3).toFixed(1)+'" text-anchor="end">'+fmt(v)+'</text>';
  }
  allEt.forEach((et,i)=>{
    const cx=pL+i*slotW+slotW/2;
    const v1=map1[et]||0,v2=map2[et]||0;
    const x1=(cx-bw-2).toFixed(1),x2=(cx+2).toFixed(1);
    const bwS=bw.toFixed(1);
    if(v1){const h=(v1/maxV*(H-pT-pB)).toFixed(1);bars+='<rect x="'+x1+'" y="'+yS(v1).toFixed(1)+'" width="'+bwS+'" height="'+h+'" rx="4" fill="#aeb5c1"/>';
      lbls+='<text x="'+(+x1+bw/2).toFixed(1)+'" y="'+(yS(v1)-4).toFixed(1)+'" text-anchor="middle" class="blbl">'+fmt(v1)+'</text>';}
    if(v2){const h=(v2/maxV*(H-pT-pB)).toFixed(1);bars+='<rect x="'+x2+'" y="'+yS(v2).toFixed(1)+'" width="'+bwS+'" height="'+h+'" rx="4" fill="#d71920"/>';
      lbls+='<text x="'+(+x2+bw/2).toFixed(1)+'" y="'+(yS(v2)-4).toFixed(1)+'" text-anchor="middle" class="blbl">'+fmt(v2)+'</text>';}
    const sn=et.replace(/^\d+ET\d+\s*[-–]\s*/,"").slice(0,9);
    xl+='<text x="'+cx.toFixed(1)+'" y="'+(H-6)+'" text-anchor="middle">'+sn+'</text>';
  });
  wrap.innerHTML='<svg class="ev-svg" viewBox="0 0 '+W+' '+H+'" width="100%" style="min-width:'+Math.min(W,500)+'px;min-height:'+H+'px">'+
    grid+'<line x1="'+pL+'" y1="'+pT+'" x2="'+pL+'" y2="'+(H-pB)+'" stroke="#e4e8ee"/>'+bars+lbls+xl+'</svg>';
}

function evCatChart(d){
  const cm={};d.forEach(r=>{const k=r.categoria||"Sem categoria";cm[k]=(cm[k]||0)+(r.valor||0)});
  const rows=Object.entries(cm).sort((a,b)=>b[1]-a[1]);
  const wrap=evEl("evCatChart");if(!wrap)return;
  if(!rows.length){wrap.innerHTML='<p style="color:#9ca3af;font-size:12px">Sem dados</p>';return}
  const COLS=["#d71920","#2d323d","#7b61c9","#e59a12","#15946c"];
  const maxV=rows[0][1]||1;
  const W=480,H=200,pL=58,pR=14,pT=22,pB=34;
  const slotW=(W-pL-pR)/rows.length,bW=Math.min(slotW*.65,62);
  const yS=v=>pT+(1-v/maxV)*(H-pT-pB);
  const fmt=v=>v>=1000000?(v/1000000).toFixed(1)+"mi":v>=1000?Math.round(v/1000)+"k":Math.round(v).toString();
  let grid="",bars="",lbls="",xl="";
  for(let i=0;i<=4;i++){
    const v=maxV*i/4,y=yS(v).toFixed(1);
    grid+='<line x1="'+pL+'" y1="'+y+'" x2="'+(W-pR)+'" y2="'+y+'" stroke="'+(i===4?"#e4e8ee":"#eef1f5")+'"/>';
    grid+='<text x="'+(pL-4)+'" y="'+(+y+3).toFixed(1)+'" text-anchor="end">'+fmt(v)+'</text>';
  }
  rows.forEach(([k,v],i)=>{
    const cx=pL+i*slotW+slotW/2,bx=(cx-bW/2).toFixed(1);
    const by=yS(v).toFixed(1),bh=Math.max(H-pB-yS(v),2).toFixed(1);
    bars+='<rect x="'+bx+'" y="'+by+'" width="'+bW.toFixed(1)+'" height="'+bh+'" rx="8" fill="'+COLS[i%COLS.length]+'"/>';
    lbls+='<text x="'+cx.toFixed(1)+'" y="'+(yS(v)-4).toFixed(1)+'" text-anchor="middle" class="blbl">'+fmt(v)+'</text>';
    const sn=k.slice(0,12);
    xl+='<text x="'+cx.toFixed(1)+'" y="'+(H-6)+'" text-anchor="middle">'+sn+'</text>';
  });
  wrap.innerHTML='<svg class="ev-svg" viewBox="0 0 '+W+' '+H+'" width="100%" style="min-height:'+H+'px">'+
    grid+'<line x1="'+pL+'" y1="'+pT+'" x2="'+pL+'" y2="'+(H-pB)+'" stroke="#e4e8ee"/>'+bars+lbls+xl+'</svg>';
}

function evGridChart(d){
  const etMap={};
  d.forEach(r=>{
    if(!r.etapa)return;
    if(!etMap[r.etapa])etMap[r.etapa]={val:0,carros:new Set(),dt:r.dt_inicio||""};
    etMap[r.etapa].val+=(r.valor||0);
    if(r.carro_id)etMap[r.etapa].carros.add(r.carro_id);
  });
  const rows=Object.entries(etMap).sort((a,b)=>a[1].dt.localeCompare(b[1].dt))
    .map(([et,v])=>({et,val:v.val,n:v.carros.size}));
  // Proj cards
  const projEl=evEl("evProjCards");
  if(projEl&&rows.length){
    const byN=rows.slice().sort((a,b)=>a.n-b.n);
    const avg=rows.reduce((s,r)=>s+r.n,0)/rows.length;
    const avgC=rows.reduce((s,r)=>s+(r.n?r.val/r.n:0),0)/rows.length;
    projEl.innerHTML=[
      ["Menor grid",byN[0].n+" carros",byN[0].et.replace(/^\d+ET\d+\s*[-–]\s*/,"").slice(0,15)],
      ["Maior grid",byN[byN.length-1].n+" carros",byN[byN.length-1].et.replace(/^\d+ET\d+\s*[-–]\s*/,"").slice(0,15)],
      ["Média de carros",avg.toFixed(1),"por etapa realizada"],
      ["Média por carro",evFmtSh(avgC),"indicador normalizado"],
    ].map(([lbl,v,sub])=>
      '<div class="ev-proj-card"><span>'+lbl+'</span><strong>'+v+'</strong><small>'+sub+'</small></div>').join("");
  }
  // Chart
  const wrap=evEl("evGridChart");if(!wrap)return;
  if(!rows.length){wrap.innerHTML='<p style="color:#9ca3af;font-size:12px">Sem dados</p>';return}
  const W=Math.max(480,rows.length*70),H=185,pL=50,pR=12,pT=18,pB=32;
  const maxV=Math.max(...rows.map(r=>r.val),1),maxN=Math.max(...rows.map(r=>r.n),1);
  const slotW=(W-pL-pR)/rows.length,bW=Math.min(slotW*.6,42);
  const yS=v=>pT+(1-v/maxV)*(H-pT-pB);
  const yN=n=>pT+(1-n/maxN)*(H-pT-pB);
  const fmt=v=>v>=1000?Math.round(v/1000)+"k":Math.round(v).toString();
  let grid="",bars="",lbls="",line="",dots="",xl="";
  for(let i=0;i<=3;i++){
    const v=maxV*i/3,y=yS(v).toFixed(1);
    grid+='<line x1="'+pL+'" y1="'+y+'" x2="'+(W-pR)+'" y2="'+y+'" stroke="#eef1f5"/>';
    grid+='<text x="'+(pL-4)+'" y="'+(+y+3).toFixed(1)+'" text-anchor="end">'+fmt(v)+'</text>';
  }
  rows.forEach((r,i)=>{
    const cx=pL+i*slotW+slotW/2,bx=(cx-bW/2).toFixed(1);
    const by=yS(r.val).toFixed(1),bh=Math.max(H-pB-yS(r.val),2).toFixed(1);
    bars+='<rect x="'+bx+'" y="'+by+'" width="'+bW.toFixed(1)+'" height="'+bh+'" rx="6" fill="#d71920"/>';
    lbls+='<text x="'+cx.toFixed(1)+'" y="'+(yS(r.val)-4).toFixed(1)+'" text-anchor="middle" class="blbl">'+fmt(r.val)+'</text>';
    const ly=yN(r.n).toFixed(1);
    line+=(i===0?"M":"L")+cx.toFixed(1)+","+ly+" ";
    dots+='<circle cx="'+cx.toFixed(1)+'" cy="'+ly+'" r="3.5" fill="#fff" stroke="#7b61c9" stroke-width="2"/>';
    const sn=r.et.replace(/^\d+ET\d+\s*[-–]\s*/,"").slice(0,6);
    xl+='<text x="'+cx.toFixed(1)+'" y="'+(H-6)+'" text-anchor="middle">'+sn+'</text>';
  });
  wrap.innerHTML='<svg class="ev-svg" viewBox="0 0 '+W+' '+H+'" width="100%" style="min-width:'+Math.min(W,400)+'px;min-height:'+H+'px">'+
    grid+'<line x1="'+pL+'" y1="'+pT+'" x2="'+pL+'" y2="'+(H-pB)+'" stroke="#e4e8ee"/>'+bars+lbls+
    '<polyline fill="none" stroke="#7b61c9" stroke-width="2.5" stroke-linejoin="round" points="'+line.trim()+'"/>'+dots+xl+'</svg>';
}

function evTable(d){
  const etMap={};
  d.forEach(r=>{
    if(!r.etapa)return;
    if(!etMap[r.etapa])etMap[r.etapa]={val:0,carros:new Set(),dias:0,dt:r.dt_inicio||"",yr:r.temporada||""};
    etMap[r.etapa].val+=(r.valor||0);
    if(r.carro_id)etMap[r.etapa].carros.add(r.carro_id);
    etMap[r.etapa].dias+=(r.dias||0);
  });
  const rows=Object.entries(etMap).sort((a,b)=>a[1].dt.localeCompare(b[1].dt))
    .map(([et,v])=>({et,val:v.val,n:v.carros.size,dias:v.dias,yr:v.yr}));
  const total=rows.reduce((s,r)=>s+r.val,0)||1;
  const medC=rows.filter(r=>r.n).map(r=>r.val/r.n);
  const avgMedC=medC.length?medC.reduce((a,b)=>a+b,0)/medC.length:0;
  const el=evEl("evTblBody");if(!el)return;
  if(!rows.length){el.innerHTML='<tr><td colspan="8" style="color:#9ca3af;font-size:12px;padding:14px">Sem dados</td></tr>';return}
  el.innerHTML=rows.map(r=>{
    const medV=r.n?r.val/r.n:0,medD=r.dias?r.val/r.dias:0;
    const devPct=avgMedC?((medV-avgMedC)/avgMedC*100):0;
    const stCls=devPct>8?"ev-st-bad":devPct>3?"ev-st-warn":"ev-st-ok";
    const stLbl=devPct>8?"Elevado":devPct>3?"Acima da média":"Regular";
    return'<tr><td>'+r.et.replace(/^\d+ET\d+\s*[-–]\s*/,"").slice(0,20)+'</td>'+
      '<td>'+r.yr+'</td><td>'+r.n+'</td>'+
      '<td>'+evFmt(r.val)+'</td>'+
      '<td>'+(r.val/total*100).toFixed(1)+'%</td>'+
      '<td>'+evFmt(medV)+'</td>'+
      '<td>'+evFmt(medD)+'</td>'+
      '<td><span class="ev-st '+stCls+'">'+stLbl+'</span></td></tr>';
  }).join("");
}

function evRender(){
  const d=evFiltered();
  evKPIs(d);evBarChart(d);evCatChart(d);evGridChart(d);evTable(d);
}
evSetup();evRender();
"""
    return (
        f"<script>const EV_RECORDS={records_js};const EV_SEDE={sede_js};const EV_EG={eg_js};</script>"
        + css + html
        + "<script>" + js + "</script>"
    )


# ── Page 3 – Pagamentos ────────────────────────────────────────────────────────

def _build_pagamentos(records_js: str, eg_js: str = "[]") -> str:
    css = """<style>
.acp{--red:#d5001c;--line:#e4e6e9;--shadow:0 10px 30px rgba(12,16,24,.08);
  --radius:18px;font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#16181c}
.acp button,.acp select{font:inherit;cursor:pointer}
.acp .acp-hero{margin-bottom:20px}
.acp .acp-hero h2{margin:0;font-size:26px;font-weight:900;letter-spacing:-.03em}
.acp .acp-hero p{margin:6px 0 0;color:#70747c;font-size:13px}
.acp .acp-filt{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:18px}
.acp .acp-fi{position:relative;display:flex;flex-direction:column;gap:3px;
  padding:8px 36px 8px 12px;border:1px solid var(--line);border-radius:12px;
  background:#fff;box-shadow:0 2px 8px rgba(12,16,24,.06);min-width:130px}
.acp .acp-fi::after{content:"";position:absolute;right:10px;top:50%;
  transform:translateY(-50%);width:16px;height:16px;pointer-events:none;
  background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23888' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E") no-repeat center/contain}
.acp .acp-fi-lbl{font-size:10px;font-weight:800;color:#9ca3af;
  text-transform:uppercase;letter-spacing:.07em;line-height:1;pointer-events:none}
.acp .acp-fi-sel{border:none;outline:none;background:transparent;
  font-size:14px;font-weight:600;color:#16181c;appearance:none;
  cursor:pointer;padding:0;line-height:1.3;width:100%}
.acp .acp-kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));
  gap:14px;margin-bottom:18px}
.acp .acp-kpi{padding:18px;background:#fff;border:1px solid var(--line);
  border-radius:var(--radius);box-shadow:var(--shadow)}
.acp .acp-kpi-val{font-size:26px;font-weight:900;letter-spacing:-.04em;color:var(--kc,var(--red))}
.acp .acp-kpi-lbl{margin-top:6px;color:#686d75;font-size:12px;font-weight:650}
.acp .acp-grid{display:grid;grid-template-columns:1fr 1.4fr;gap:16px;margin-bottom:18px}
.acp .acp-card{background:#fff;border:1px solid var(--line);
  border-radius:var(--radius);box-shadow:var(--shadow)}
.acp .acp-card-head{display:flex;align-items:flex-start;justify-content:space-between;
  gap:10px;padding:16px 18px 10px}
.acp .acp-card-head h3{margin:0;font-size:14px;letter-spacing:-.015em}
.acp .acp-card-head p{margin:4px 0 0;color:#858990;font-size:11px}
.acp .acp-badge{padding:6px 9px;border-radius:999px;color:#5f646c;
  background:#f4f5f6;font-size:10px;font-weight:800;white-space:nowrap}
.acp .acp-card-body{padding:8px 18px 18px}
.acp .acp-donut-wrap{display:grid;grid-template-columns:120px 1fr;
  gap:16px;align-items:center;min-height:180px}
.acp .acp-donut{width:110px;height:110px;border-radius:50%;
  background:conic-gradient(#15966a 0 60%,#d58a13 60% 80%,#9ca3af 80% 100%);
  position:relative;display:grid;place-items:center;margin:auto}
.acp .acp-donut::after{content:"";position:absolute;width:70px;height:70px;
  border-radius:50%;background:#fff;box-shadow:0 0 0 1px var(--line)}
.acp .acp-dc{position:relative;z-index:2;text-align:center}
.acp .acp-dc strong{display:block;font-size:16px;font-weight:900;line-height:1}
.acp .acp-dc span{font-size:10px;color:#80848b}
.acp .acp-leg{display:grid;gap:8px}
.acp .acp-lr{display:grid;grid-template-columns:8px minmax(0,1fr) auto;
  align-items:center;gap:8px;font-size:11px}
.acp .acp-lr i{width:8px;height:8px;border-radius:3px}
.acp .acp-lr span{color:#686d75}
.acp .acp-bars{display:grid;gap:9px}
.acp .acp-br{display:grid;gap:4px}
.acp .acp-bm{display:flex;align-items:center;justify-content:space-between;
  gap:10px;font-size:11px}
.acp .acp-bm span{color:#5f646b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.acp .acp-bm strong{font-size:11px;white-space:nowrap}
.acp .acp-bt{height:8px;border-radius:999px;background:#f0f1f3;overflow:hidden}
.acp .acp-bf{height:100%;border-radius:999px;transform-origin:left;
  animation:acpgrow .6s ease both}
@keyframes acpgrow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.acp .acp-pend{margin-bottom:18px}
.acp .acp-pend-head{display:flex;align-items:center;justify-content:space-between;
  padding:14px 18px;background:#fff;border:1px solid var(--line);
  border-radius:var(--radius) var(--radius) 0 0;box-shadow:var(--shadow)}
.acp .acp-pend-head h3{margin:0;font-size:14px}
.acp .acp-pend-list{background:#fff;border:1px solid var(--line);border-top:none;
  border-radius:0 0 var(--radius) var(--radius);overflow:hidden}
.acp .acp-pend-row{display:grid;grid-template-columns:minmax(0,1fr) 120px;
  gap:10px;padding:11px 18px;font-size:12px;border-bottom:1px solid #f0f1f3}
.acp .acp-pend-row:last-child{border-bottom:none}
.acp .acp-pend-row.hdr{background:#f8f9fa;font-weight:800;font-size:10px;
  color:#777;text-transform:uppercase;letter-spacing:.06em}
.acp .acp-status{padding:3px 8px;border-radius:6px;font-size:10px;font-weight:800;white-space:nowrap}
.acp .acp-st-pago{background:#dcfce7;color:#166534}
.acp .acp-st-pend{background:#fef9c3;color:#854d0e}
.acp .acp-st-sem{background:#f1f5f9;color:#64748b}
@media(max-width:800px){
  .acp .acp-kpis,.acp .acp-grid{grid-template-columns:1fr}
  .acp .acp-donut-wrap{grid-template-columns:1fr}}
</style>"""

    html = """<div class="acp">
<div class="acp-hero">
  <h2>Custo de Autônomos · Pagamentos</h2>
  <p>Status, formas de pagamento e pendências</p>
</div>
<div class="acp-filt">
  <div class="acp-fi">
    <span class="acp-fi-lbl">Temporada</span>
    <select class="acp-fi-sel" id="acpYear"></select>
  </div>
  <div class="acp-fi">
    <span class="acp-fi-lbl">Categoria</span>
    <select class="acp-fi-sel" id="acpCat"></select>
  </div>
</div>
<section class="acp-kpis">
  <div class="acp-kpi">
    <div class="acp-kpi-val" style="--kc:#15966a" id="acpKPago">—</div>
    <div class="acp-kpi-lbl">Total pago</div>
  </div>
  <div class="acp-kpi">
    <div class="acp-kpi-val" style="--kc:#d58a13" id="acpKPend">—</div>
    <div class="acp-kpi-lbl">Valor pendente</div>
  </div>
  <div class="acp-kpi">
    <div class="acp-kpi-val" style="--kc:#9ca3af" id="acpKSem">—</div>
    <div class="acp-kpi-lbl">Sem status registrado</div>
  </div>
</section>
<div class="acp-grid">
  <article class="acp-card">
    <div class="acp-card-head">
      <div><h3>Status de pagamento</h3><p>Distribuição por valor</p></div>
      <span class="acp-badge" id="acpStBadge">—</span>
    </div>
    <div class="acp-card-body acp-donut-wrap">
      <div class="acp-donut" id="acpStDonut">
        <div class="acp-dc"><strong id="acpStN">—</strong><span>registros</span></div>
      </div>
      <div class="acp-leg" id="acpStLeg"></div>
    </div>
  </article>
  <article class="acp-card">
    <div class="acp-card-head">
      <div><h3>Forma de pagamento</h3><p>Distribuição por valor total</p></div>
      <span class="acp-badge">Canais</span>
    </div>
    <div class="acp-card-body">
      <div class="acp-bars" id="acpFormaBars"></div>
    </div>
  </article>
</div>
<div class="acp-pend">
  <div class="acp-pend-head">
    <h3>Pagamentos realizados por autônomo</h3>
    <span class="acp-badge" id="acpPendBadge">—</span>
  </div>
  <div class="acp-pend-list">
    <div class="acp-pend-row hdr">
      <span>Autônomo</span><span>Valor</span>
    </div>
    <div id="acpPendRows"></div>
  </div>
</div>
</div>"""

    js = r"""
const ACP_ST_COLORS={"Pago":"#15966a","pago":"#15966a","Pendente":"#d58a13","pendente":"#d58a13"};
const ACP_FORMA_COLORS=["#d5001c","#374151","#7157c8","#d58a13","#ef6b2e"];
const acpEl=id=>document.getElementById(id);
function acpFmt(v){return"R$ "+v.toLocaleString("pt-BR",{minimumFractionDigits:0,maximumFractionDigits:0})}
function acpTc(s){return s?s.split(" ").map(w=>w?w[0].toUpperCase()+w.slice(1).toLowerCase():"").join(" "):""}
function acpFormaNorm(s){
  s=(s||"").trim().toUpperCase();
  if(s==="NF"||s==="NOTA FISCAL")return"NF";
  if(s==="RPA")return"RPA";
  if(s==="RECIBO")return"Recibo";
  return s?s.charAt(0)+s.slice(1).toLowerCase():"";
}
function acpNormSt(s){
  if(!s||s.trim()==="")return"Sem status";
  const l=s.toLowerCase();
  if(l==="pago"||l==="paga")return"Pago";
  if(l.includes("pend"))return"Pendente";
  return s;
}

function acpFillSel(id,vals,lbl){
  const el=acpEl(id);if(!el)return;
  el.innerHTML='<option value="">'+lbl+'</option>'+vals.map(v=>'<option value="'+v+'">'+v+'</option>').join("");
}
function acpSetup(){
  const years=[...new Set(ACP_RECORDS.map(r=>r.temporada).filter(Boolean))].sort().reverse();
  const cats=[...new Set(ACP_RECORDS.map(r=>r.categoria).filter(Boolean))].sort();
  acpFillSel("acpYear",years,"Todas as temporadas");
  acpFillSel("acpCat",cats,"Todas as categorias");
  ["acpYear","acpCat"].forEach(id=>{const el=acpEl(id);if(el)el.addEventListener("change",acpRender)});
}
function acpFiltered(){
  const yr=acpEl("acpYear")?.value||"",ct=acpEl("acpCat")?.value||"";
  return ACP_RECORDS.filter(r=>(!yr||r.temporada===yr)&&(!ct||r.categoria===ct));
}
function acpRender(){
  const d=acpFiltered();
  const pago=d.filter(r=>acpNormSt(r.status)==="Pago").reduce((s,r)=>s+r.valor,0);
  const pend=d.filter(r=>acpNormSt(r.status)==="Pendente").reduce((s,r)=>s+r.valor,0);
  const sem=d.filter(r=>acpNormSt(r.status)==="Sem status").reduce((s,r)=>s+r.valor,0);
  if(acpEl("acpKPago"))acpEl("acpKPago").textContent=acpFmt(pago);
  if(acpEl("acpKPend"))acpEl("acpKPend").textContent=acpFmt(pend);
  if(acpEl("acpKSem"))acpEl("acpKSem").textContent=acpFmt(sem);

  // donut status
  const stMap={"Pago":pago,"Pendente":pend,"Sem status":sem};
  const stColors={"Pago":"#15966a","Pendente":"#d58a13","Sem status":"#9ca3af"};
  const stTotal=(pago+pend+sem)||1;
  let acc2=0;
  const stCg=Object.entries(stMap).map(([k,v])=>{
    const s=acc2;acc2+=v/stTotal*100;
    return stColors[k]+" "+s.toFixed(2)+"% "+acc2.toFixed(2)+"%";
  }).join(",");
  const sdn=acpEl("acpStDonut");if(sdn)sdn.style.background="conic-gradient("+stCg+")";
  const sn=acpEl("acpStN");if(sn)sn.textContent=d.length;
  const sb=acpEl("acpStBadge");if(sb)sb.textContent=acpFmt(stTotal);
  const sl=acpEl("acpStLeg");
  if(sl)sl.innerHTML=Object.entries(stMap).map(([k,v])=>
    '<div class="acp-lr"><i style="background:'+stColors[k]+'"></i>'+
    '<span>'+k+'</span><strong>'+acpFmt(v)+'</strong></div>').join("");

  // forma bars
  const fMap={};
  // normaliza formas (NF/Nota Fiscal -> NF; RECIBO/Recibo -> Recibo) e inclui Outras Equipes
  const addForma=r=>{const k=acpFormaNorm(r.forma);if(!k)return;fMap[k]=(fMap[k]||0)+(r.valor||0)};
  d.forEach(addForma);
  (typeof ACP_EG!=="undefined"?ACP_EG:[]).forEach(addForma);
  const fRows=Object.entries(fMap).sort((a,b)=>b[1]-a[1]);
  const fMax=fRows[0]?.[1]||1;
  const fb=acpEl("acpFormaBars");
  if(fb)fb.innerHTML=fRows.length?fRows.map(([n,v],i)=>
    '<div class="acp-br"><div class="acp-bm"><span>'+n+'</span><strong>'+acpFmt(v)+'</strong></div>'+
    '<div class="acp-bt"><div class="acp-bf" style="width:'+(v/fMax*100).toFixed(1)+'%;background:'+ACP_FORMA_COLORS[i%ACP_FORMA_COLORS.length]+'"></div></div></div>').join(""):
    '<p style="color:#888;font-size:12px">Sem dados de forma de pagamento</p>';

  // pagamentos realizados por autônomo (todos os lançamentos = pagamentos realizados)
  const pendMap={};
  d.forEach(r=>{
    const k=acpTc(r.autonomo)||"—";
    if(!pendMap[k])pendMap[k]={valor:0};
    pendMap[k].valor+=r.valor;
  });
  const pendRows=Object.entries(pendMap).sort((a,b)=>b[1].valor-a[1].valor);
  const pb2=acpEl("acpPendBadge");if(pb2)pb2.textContent=pendRows.length+" autônomos";
  const pr2=acpEl("acpPendRows");
  if(pr2)pr2.innerHTML=pendRows.length?pendRows.map(([n,v])=>{
    return'<div class="acp-pend-row"><span title="'+n+'">'+n+'</span>'+
      '<strong>'+acpFmt(v.valor)+'</strong></div>';}).join(""):
    '<div class="acp-pend-row" style="color:#888;font-size:12px;padding:16px 18px">Nenhum pagamento registrado.</div>';
}
acpSetup();acpRender();
"""
    return (f"<script>const ACP_RECORDS={records_js};const ACP_EG={eg_js};</script>"
            + css + html
            + "<script>" + js + "</script>")


# ── Page combined – Custo (Evolução + Pagamentos) ─────────────────────────────

def _build_custo(records_js: str, sede_js: str = "{}", eg_js: str = "[]") -> str:
    """Combines Evolução and Pagamentos into one tabbed page."""
    ev = _build_evolucao(records_js, sede_js, eg_js)
    pag = _build_pagamentos(records_js, eg_js)
    tab_css = """<style>
.custo-tabs-wrap *{box-sizing:border-box}
.custo-tabs{display:flex;gap:4px;margin-bottom:16px;background:#fff;
  border:1px solid #e3e7ee;border-radius:14px;padding:5px;
  box-shadow:0 4px 14px rgba(24,32,44,.06)}
.custo-tab{flex:1;padding:10px 16px;border:none;background:none;border-radius:10px;
  font-size:13px;font-weight:700;color:#6f7886;cursor:pointer;transition:.18s;font-family:inherit}
.custo-tab.active{background:#d71920;color:#fff;box-shadow:0 4px 14px rgba(215,25,32,.22)}
.custo-tab:hover:not(.active){background:#f5f7fa;color:#18202c}
.custo-pane{display:none}.custo-pane.active{display:block}
</style>"""
    tab_html = (
        '<div class="custo-tabs-wrap">'
        '<div class="custo-tabs">'
        '<button class="custo-tab active" onclick="custoTab(0,this)">📈 Custos &amp; Comparativos</button>'
        '<button class="custo-tab" onclick="custoTab(1,this)">💳 Pagamentos</button>'
        '</div>'
        '<div class="custo-pane active" id="custoPane0">' + ev + '</div>'
        '<div class="custo-pane" id="custoPane1">' + pag + '</div>'
        '</div>'
    )
    tab_js = """<script>
function custoTab(idx,btn){
  document.querySelectorAll('.custo-tab').forEach((b,i)=>b.classList.toggle('active',i===idx));
  document.querySelectorAll('.custo-pane').forEach((p,i)=>p.classList.toggle('active',i===idx));
}
</script>"""
    return tab_css + tab_html + tab_js


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/indicadores/autonomo-custo")
def autonomo_custo_geral(request: Request, db: Session = Depends(get_db)):
    erro = None
    dash_html = None
    try:
        rj = _fetch(db)
        mj = _fetch_meta(db)
        egj = _fetch_equipe_geral(db)
        dash_html = _build_geral(rj, mj, egj)
    except Exception as exc:
        erro = f"Erro ao carregar dados: {exc}"
    return templates.TemplateResponse("indicadores/autonomo_custo_geral.html", {
        "request": request, "dash_html": dash_html, "erro": erro,
    })


@router.get("/indicadores/autonomo-custo-evolucao")
def autonomo_custo_evolucao(request: Request, db: Session = Depends(get_db)):
    erro = None
    dash_html = None
    try:
        rj = _fetch(db)
        sj = _fetch_sede(db)
        egj = _fetch_equipe_geral(db)
        dash_html = _build_custo(rj, sj, egj)
    except Exception as exc:
        erro = f"Erro ao carregar dados: {exc}"
    return templates.TemplateResponse("indicadores/autonomo_custo_evolucao.html", {
        "request": request, "dash_html": dash_html, "erro": erro,
    })


@router.get("/indicadores/autonomo-custo-pagamentos")
def autonomo_custo_pagamentos(request: Request):
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/indicadores/autonomo-custo-evolucao", status_code=301)


# ── Page 4 – Planejamento e Cobertura ─────────────────────────────────────────

def _fetch_planejamento(db: Session) -> str:
    """Planejado (Disponibilidade Autonomos) x alocado, por etapa e funcao."""
    from sqlalchemy import text as _text

    # Funcao do autonomo: cargo cadastrado, com o tipo como fallback
    _FUNC = "COALESCE(NULLIF(TRIM(ca.nome_cargo), ''), NULLIF(TRIM(da.tipo_autonomo), ''), '-')"

    # Esperado = autonomos escalados para a etapa na Disponibilidade Autonomos
    planejado = []
    planejado_total = 0
    try:
        rows = db.execute(_text(f"""
            SELECT p.id_etapa,
                   {_FUNC} AS cargo,
                   COUNT(DISTINCT p.id_autonomo) AS qtd_esp,
                   e.nome_etapa,
                   COALESCE(e.temporada, '')
            FROM planejamento_equipe_etapa p
            LEFT JOIN dim_autonomos da ON da.id_autonomo = p.id_autonomo
            LEFT JOIN dim_cargos_autonomos ca ON ca.id_cargo_autonomo = da.id_cargo_autonomo
            LEFT JOIN dim_etapas e ON e.id_etapa = p.id_etapa
            WHERE UPPER(TRIM(COALESCE(p.status_disponibilidade, ''))) = 'ESCALADO'
            GROUP BY p.id_etapa, {_FUNC}, e.nome_etapa, e.temporada
        """)).fetchall()
        planejado = [{"id_etapa": r[0], "cargo": r[1] or "-",
                      "qtd_esp": float(r[2] or 0), "etapa": r[3] or "",
                      "temporada": str(r[4] or "")} for r in rows]
        planejado_total = sum(p["qtd_esp"] for p in planejado)
    except Exception as exc:
        print(f"AVISO - planejamento por etapa: {exc}")

    # Realizado = autonomos efetivamente alocados na etapa
    alocacoes = []
    try:
        rows = db.execute(_text(f"""
            SELECT f.id_etapa,
                   COALESCE(NULLIF(TRIM(f.funcao_autonomo), ''), {_FUNC}) AS cargo,
                   COUNT(DISTINCT f.id_autonomo) AS qtd_aloc,
                   e.nome_etapa,
                   COALESCE(e.temporada, '')
            FROM fato_piloto_autonomo_prova f
            LEFT JOIN dim_autonomos da ON da.id_autonomo = f.id_autonomo
            LEFT JOIN dim_cargos_autonomos ca ON ca.id_cargo_autonomo = da.id_cargo_autonomo
            LEFT JOIN dim_etapas e ON e.id_etapa = f.id_etapa
            GROUP BY f.id_etapa,
                     COALESCE(NULLIF(TRIM(f.funcao_autonomo), ''), {_FUNC}),
                     e.nome_etapa, e.temporada
        """)).fetchall()
        alocacoes = [{"id_etapa": r[0], "cargo": r[1] or "-",
                      "qtd_aloc": float(r[2] or 0), "etapa": r[3] or "",
                      "temporada": str(r[4] or "")} for r in rows]
    except Exception as exc:
        print(f"AVISO - alocacoes da cobertura: {exc}")

    # Trocas ainda sem substituto definido
    try:
        row = db.execute(_text(
            "SELECT COUNT(*) FROM troca_entre_etapas WHERE id_autonomo_substituto IS NULL"
        )).fetchone()
        trocas_pend = int(row[0] or 0) if row else 0
    except Exception as exc:
        print(f"AVISO - trocas pendentes: {exc}")
        trocas_pend = 0

    try:
        rows = db.execute(_text(
            "SELECT id_etapa, nome_etapa, data_inicio, data_fim, temporada FROM dim_etapas ORDER BY data_inicio"
        )).fetchall()
        etapas = [{"id": r[0], "nome": r[1] or "", "dt_ini": str(r[2] or ""),
                   "dt_fim": str(r[3] or ""), "temporada": str(r[4] or "")} for r in rows]
    except Exception as exc:
        print(f"AVISO - etapas: {exc}")
        etapas = []

    return _json.dumps({
        "planejado": planejado,
        "alocacoes": alocacoes,
        "trocas_pend": trocas_pend,
        "etapas": etapas,
        "planejado_total": planejado_total,
    }, ensure_ascii=False)



def _build_planejamento(plan_js: str) -> str:
    css = """<style>
.pl{--red:#d71920;--green:#15946c;--yellow:#e59a12;--muted:#6f7886;
  --border:#e3e7ee;--shadow:0 8px 24px rgba(24,32,44,.07);--radius:16px;
  font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#18202c}
.pl *{box-sizing:border-box}
.pl button,.pl select{font:inherit}
.pl-filters{display:grid;grid-template-columns:repeat(3,minmax(130px,1fr)) 100px;
  gap:10px;margin-bottom:14px}
.pl-filter{background:#fff;border:1px solid var(--border);border-radius:12px;
  padding:9px 11px;box-shadow:0 3px 10px rgba(24,32,44,.04)}
.pl-filter label{display:block;font-size:9px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.08em;margin-bottom:4px;font-weight:700}
.pl-filter select{width:100%;border:0;outline:0;background:transparent;
  font-size:12px;color:#18202c;font-weight:600;cursor:pointer;appearance:none}
.pl-reset{border:1px solid var(--border);background:#fff;border-radius:12px;
  font-weight:700;color:#555f6d;cursor:pointer;font-size:12px;padding:0 12px}
.pl-reset:hover{background:#f5f7fa}
.pl-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:11px;margin-bottom:11px}
.pl-kpi{background:#fff;border:1px solid var(--border);border-radius:var(--radius);
  padding:14px 15px 12px;box-shadow:var(--shadow);position:relative;overflow:hidden;min-height:100px}
.pl-kpi::after{content:"";width:72px;height:72px;border-radius:50%;position:absolute;
  right:-26px;top:-26px;background:var(--tint,#f4f6f9)}
.pl-kpi-top{display:flex;align-items:center;justify-content:space-between;position:relative;z-index:1}
.pl-kpi-title{font-size:10px;font-weight:800;text-transform:uppercase;
  letter-spacing:.055em;color:var(--muted)}
.pl-icon{width:29px;height:29px;border-radius:8px;display:grid;place-items:center;
  background:var(--iconbg,#f1f3f6);color:var(--iconcolor,#18202c);font-size:12px;font-weight:900}
.pl-kpi-value{margin-top:8px;font-size:22px;font-weight:800;letter-spacing:-.04em;
  position:relative;z-index:1}
.pl-kpi-foot{margin-top:3px;color:var(--muted);font-size:10px;position:relative;z-index:1}
.pl-delta{padding:2px 5px;border-radius:999px;font-weight:800;font-size:9px}
.pl-delta.ok{color:#107455;background:#e9f7f2}
.pl-delta.warn{color:#ae7105;background:#fff5df}
.pl-delta.bad{color:#b11c22;background:#fff0f1}
.pl-grid{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(290px,.9fr);
  gap:11px;margin-bottom:11px}
.pl-card{background:#fff;border:1px solid var(--border);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:14px 15px;min-width:0}
.pl-card-title{margin:0 0 2px;font-size:13px;font-weight:800}
.pl-card-sub{color:var(--muted);font-size:10px;margin-bottom:12px}
.pl-ch-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:10px}
.pl-cov-box{background:linear-gradient(135deg,#171b23,#242a35);
  border-radius:13px;padding:14px;color:#fff;margin-bottom:10px}
.pl-cov-label{font-size:9px;text-transform:uppercase;letter-spacing:.08em;
  color:#b8c0cb;margin-bottom:4px;font-weight:700}
.pl-cov-title{font-size:14px;font-weight:700;margin-bottom:12px}
.pl-cov-number{font-size:32px;font-weight:800;letter-spacing:-.04em;margin-bottom:9px}
.pl-progress{height:7px;border-radius:999px;background:rgba(255,255,255,.13);overflow:hidden;margin-bottom:7px}
.pl-progress span{display:block;height:100%;border-radius:999px;
  background:linear-gradient(90deg,#ff5359,#d71920)}
.pl-cov-meta{display:flex;justify-content:space-between;font-size:9px;color:#c7ccd4}
.pl-sum-list{display:grid;gap:8px}
.pl-sum-item{display:grid;grid-template-columns:30px minmax(0,1fr) auto;gap:9px;
  align-items:center;border:1px solid var(--border);border-radius:11px;padding:9px 10px;background:#fafbfc}
.pl-sum-icon{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;font-size:11px;font-weight:800}
.pl-sum-item strong{display:block;font-size:10px}
.pl-sum-item span{display:block;margin-top:2px;font-size:8px;color:var(--muted)}
.pl-sum-val{font-size:17px!important;font-weight:800;color:#18202c!important;margin:0!important}
.pl-role-list{display:grid;gap:11px}
.pl-role-row{display:grid;grid-template-columns:minmax(100px,1fr) 2fr auto;align-items:center;gap:10px}
.pl-role-name strong{display:block;font-size:10px}
.pl-role-name small{display:block;font-size:8px;color:var(--muted);margin-top:2px}
.pl-role-track{height:8px;background:#eef1f5;border-radius:999px;overflow:hidden}
.pl-role-fill{height:100%;border-radius:999px}
.pl-role-val{min-width:50px;text-align:right;font-size:10px;font-weight:800}
.pl-hm-wrap{overflow-x:auto;margin-bottom:11px}
.pl-hm{display:grid;gap:5px;align-items:center}
.pl-hm-head{text-align:center;font-size:8px;color:var(--muted);font-weight:800;text-transform:uppercase}
.pl-hm-label{font-size:9px;font-weight:700;color:#4d5663;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pl-cell{height:28px;border-radius:7px;display:grid;place-items:center;
  font-size:8px;font-weight:800;border:1px solid rgba(0,0,0,.03)}
.pl-full{background:#dff4ec;color:#0f7253}
.pl-mid{background:#fff0ce;color:#976000}
.pl-low{background:#ffe3e5;color:#aa141a}
.pl-na{background:#edf0f4;color:#7d8692}
.pl-tbl-wrap{overflow:auto;border:1px solid var(--border);border-radius:11px}
.pl-tbl{width:100%;border-collapse:collapse;min-width:700px;font-size:10px}
.pl-tbl thead th{text-align:left;padding:9px 10px;background:#f7f8fa;color:#606977;
  text-transform:uppercase;font-size:8px;letter-spacing:.06em;
  border-bottom:1px solid var(--border);white-space:nowrap}
.pl-tbl tbody td{padding:9px 10px;border-bottom:1px solid #edf0f4;vertical-align:middle;white-space:nowrap}
.pl-tbl tbody tr:last-child td{border-bottom:0}
.pl-tbl tbody tr:hover{background:#fafbfc}
.pl-st{display:inline-flex;align-items:center;gap:4px;padding:4px 7px;
  border-radius:999px;font-size:8px;font-weight:800}
.pl-st::before{content:"";width:5px;height:5px;border-radius:50%}
.pl-st-ok{color:#107455;background:#e9f7f2}.pl-st-ok::before{background:#15946c}
.pl-st-warn{color:#a96b02;background:#fff4de}.pl-st-warn::before{background:#e59a12}
.pl-st-bad{color:#ad151b;background:#fff0f1}.pl-st-bad::before{background:#d71920}
.pl-st-gray{color:#626b77;background:#eef1f4}.pl-st-gray::before{background:#8a939f}
.pl-legend{display:flex;align-items:center;gap:10px;font-size:9px;color:var(--muted);flex-wrap:wrap}
.pl-legend span{display:inline-flex;align-items:center;gap:4px}
.pl-legend i{width:8px;height:8px;border-radius:2px;display:inline-block}
@media(max-width:1100px){
  .pl-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .pl-grid{grid-template-columns:1fr}}
@media(max-width:760px){.pl-kpis{grid-template-columns:1fr 1fr}}
</style>"""

    html = """<div class="pl">
<div class="pl-filters">
  <div class="pl-filter"><label>Temporada</label><select id="plYear"></select></div>
  <div class="pl-filter"><label>Etapa</label><select id="plEtapa"></select></div>
  <div class="pl-filter"><label>Categoria</label><select id="plCat"></select></div>
  <button class="pl-reset" onclick="plReset()">Limpar</button>
</div>
<section class="pl-kpis">
  <article class="pl-kpi" style="--tint:#eef5ff;--iconbg:#edf4fd;--iconcolor:#2673c8">
    <div class="pl-kpi-top"><span class="pl-kpi-title">Equipe esperada</span>
      <div class="pl-icon">E</div></div>
    <div class="pl-kpi-value" id="plKEsp">—</div>
    <div class="pl-kpi-foot">escalados na Disponibilidade Autônomos</div></article>
  <article class="pl-kpi" style="--tint:#ebf8f4;--iconbg:#e7f7f1;--iconcolor:#11835f">
    <div class="pl-kpi-top"><span class="pl-kpi-title">Equipe alocada</span>
      <div class="pl-icon">✓</div></div>
    <div class="pl-kpi-value" id="plKAloc">—</div>
    <div class="pl-kpi-foot" id="plKAlocF"></div></article>
  <article class="pl-kpi" style="--tint:#fff1f2;--iconbg:#fff0f1;--iconcolor:#c5161c">
    <div class="pl-kpi-top"><span class="pl-kpi-title">Vagas em aberto</span>
      <div class="pl-icon">!</div></div>
    <div class="pl-kpi-value" id="plKVagas">—</div>
    <div class="pl-kpi-foot" id="plKVagasF"></div></article>
  <article class="pl-kpi" style="--tint:#eef8fb;--iconbg:#ebf7fa;--iconcolor:#247f91">
    <div class="pl-kpi-top"><span class="pl-kpi-title">Etapas cobertas</span>
      <div class="pl-icon">▣</div></div>
    <div class="pl-kpi-value" id="plKCarros">—</div>
    <div class="pl-kpi-foot" id="plKCarrosF"></div></article>
  <article class="pl-kpi" style="--tint:#fff7e9;--iconbg:#fff6e5;--iconcolor:#c88408">
    <div class="pl-kpi-top"><span class="pl-kpi-title">Etapas com déficit</span>
      <div class="pl-icon">C</div></div>
    <div class="pl-kpi-value" id="plKInc">—</div>
    <div class="pl-kpi-foot">etapas com alguma vaga aberta</div></article>
  <article class="pl-kpi" style="--tint:#f2effc;--iconbg:#f0edfb;--iconcolor:#7259be">
    <div class="pl-kpi-top"><span class="pl-kpi-title">Cobertura geral</span>
      <div class="pl-icon">%</div></div>
    <div class="pl-kpi-value" id="plKCob">—</div>
    <div class="pl-kpi-foot">alocados / esperados</div></article>
  <article class="pl-kpi" style="--tint:#f2f4f8;--iconbg:#edf0f5;--iconcolor:#4e5967">
    <div class="pl-kpi-top"><span class="pl-kpi-title">Cargos descobertos</span>
      <div class="pl-icon">↘</div></div>
    <div class="pl-kpi-value" id="plKCargos">—</div>
    <div class="pl-kpi-foot">tipos de cargo sem cobertura total</div></article>
  <article class="pl-kpi" style="--tint:#fff0f1;--iconbg:#ffeded;--iconcolor:#bd151b">
    <div class="pl-kpi-top"><span class="pl-kpi-title">Trocas pendentes</span>
      <div class="pl-icon">↻</div></div>
    <div class="pl-kpi-value" id="plKTrocas">—</div>
    <div class="pl-kpi-foot">sem substituto definido</div></article>
</section>
<section class="pl-grid">
  <article class="pl-card">
    <div class="pl-ch-head">
      <div><h2 class="pl-card-title">Cobertura por cargo</h2>
        <p class="pl-card-sub">Alocados vs. esperados em cada tipo de cargo</p></div>
    </div>
    <div class="pl-role-list" id="plRoleList"></div>
  </article>
  <article class="pl-card">
    <div id="plCovBox">
      <p style="color:#9ca3af;font-size:11px">Carregando próxima etapa...</p>
    </div>
    <div class="pl-sum-list" id="plSumList"></div>
  </article>
</section>
<article class="pl-card" style="margin-bottom:11px">
  <div class="pl-ch-head">
    <div><h2 class="pl-card-title">Mapa de cobertura por etapa</h2>
      <p class="pl-card-sub">Situação de cada cargo nas etapas da seleção atual</p></div>
    <div class="pl-legend">
      <span><i style="background:#dff4ec"></i>Completo</span>
      <span><i style="background:#fff0ce"></i>Parcial</span>
      <span><i style="background:#ffe3e5"></i>Em aberto</span>
    </div>
  </div>
  <div class="pl-hm-wrap"><div id="plHeatmap"></div></div>
</article>
<article class="pl-card">
  <div class="pl-ch-head">
    <div><h2 class="pl-card-title">Pendências de cobertura</h2>
      <p class="pl-card-sub">Combinações etapa × cargo com déficit de alocação</p></div>
  </div>
  <div class="pl-tbl-wrap">
    <table class="pl-tbl">
      <thead><tr>
        <th>Etapa</th><th>Cargo</th>
        <th>Escalado</th><th>Alocado</th><th>Déficit</th><th>Situação</th>
      </tr></thead>
      <tbody id="plTblBody"></tbody>
    </table>
  </div>
</article>
</div>"""

    js = r"""
const plEl=id=>document.getElementById(id);
const plNorm=s=>(s||"").trim().toUpperCase();
function plFillSel(id,vals,lbl){
  const el=plEl(id);if(!el)return;
  el.innerHTML='<option value="">'+lbl+'</option>'+vals.map(v=>'<option value="'+v+'">'+v+'</option>').join("");
}
function plSetup(){
  const years=[...new Set(PL_DATA.etapas.map(e=>e.temporada).filter(Boolean))].sort().reverse();
  const etapas=[...new Set(PL_DATA.planejado.map(r=>r.etapa).filter(Boolean))].sort();
  plFillSel("plYear",years,"Todas as temporadas");
  plFillSel("plEtapa",etapas,"Todas as etapas");
  plFillSel("plCat",[],"Todas as categorias");
  ["plYear","plEtapa","plCat"].forEach(id=>{const el=plEl(id);if(el)el.addEventListener("change",plRender)});
}
function plReset(){["plYear","plEtapa","plCat"].forEach(id=>{const el=plEl(id);if(el)el.value=""});plRender()}

function plVazio(){
  const s='color:#9ca3af;font-size:11px';
  if(!(PL_DATA.planejado_total||0))
    return'<p style="'+s+'">Nenhum autonomo escalado. Importe o planejamento em '+
      '<a href="/composicao-meta-equipe" style="color:#d71920">Disponibilidade Autonomos</a> '+
      'para acompanhar a cobertura.</p>';
  return'<p style="'+s+'">Nenhum escalado na selecao atual.</p>';
}

function plFiltra(lista){
  const yr=plEl("plYear")?.value||"",et=plEl("plEtapa")?.value||"";
  return lista.filter(r=>(!yr||r.temporada===yr)&&(!et||r.etapa===et));
}

/* chave: etapa + cargo normalizado */
const plKey=r=>r.id_etapa+"|"+plNorm(r.cargo);

function plRender(){
  const plan=plFiltra(PL_DATA.planejado);
  const aloc=plFiltra(PL_DATA.alocacoes);

  const espMap={},alocMap={};
  plan.forEach(r=>{espMap[plKey(r)]=(espMap[plKey(r)]||0)+r.qtd_esp});
  aloc.forEach(r=>{alocMap[plKey(r)]=(alocMap[plKey(r)]||0)+r.qtd_aloc});

  const totalEsp=plan.reduce((s,r)=>s+r.qtd_esp,0);
  /* so conta o alocado que corresponde a algo escalado */
  const totalAloc=Object.keys(espMap).reduce((s,k)=>s+Math.min(alocMap[k]||0,espMap[k]),0);
  const deficit=Math.max(totalEsp-totalAloc,0);
  const pct=totalEsp?Math.min(totalAloc/totalEsp*100,100):0;

  /* etapas cobertas x com deficit */
  const etapasSet=new Set(plan.map(r=>r.id_etapa));
  const etOk=new Set(),etDef=new Set();
  etapasSet.forEach(eid=>{
    const linhas=plan.filter(r=>r.id_etapa===eid);
    const ok=linhas.every(r=>(alocMap[plKey(r)]||0)>=r.qtd_esp);
    if(ok)etOk.add(eid);else etDef.add(eid);
  });

  /* cobertura por cargo */
  const cargoMap={};
  plan.forEach(r=>{
    const n=r.cargo||"-";
    if(!cargoMap[n])cargoMap[n]={esp:0,aloc:0};
    cargoMap[n].esp+=r.qtd_esp;
    cargoMap[n].aloc+=Math.min(alocMap[plKey(r)]||0,r.qtd_esp);
  });
  const cargosDesc=Object.values(cargoMap).filter(v=>v.aloc<v.esp).length;

  const set=(id,v,f)=>{const e=plEl(id);if(e)e.textContent=v;const fe=plEl(id+"F");if(fe)fe.innerHTML=f||""};
  set("plKEsp",Math.round(totalEsp));
  set("plKAloc",Math.round(totalAloc),'<span class="pl-delta '+(pct>=95?"ok":pct>=80?"warn":"bad")+'">'+pct.toFixed(1)+'%</span> de cobertura');
  set("plKVagas",Math.round(deficit),etDef.size+" etapas com deficit");
  set("plKCarros",etOk.size,"de "+(etOk.size+etDef.size)+" etapas planejadas");
  set("plKInc",etDef.size,"");
  const cobEl=plEl("plKCob");if(cobEl)cobEl.textContent=pct.toFixed(1)+"%";
  const cargosEl=plEl("plKCargos");if(cargosEl)cargosEl.textContent=cargosDesc;
  const trocEl=plEl("plKTrocas");if(trocEl)trocEl.textContent=PL_DATA.trocas_pend;

  plRoleList(cargoMap);
  plCovBox();
  plSumList(etOk,etDef,totalEsp,totalAloc);
  plHeatmap(plan,espMap,alocMap);
  plTable(plan,espMap,alocMap);
}

function plRoleList(cargoMap){
  const el=plEl("plRoleList");if(!el)return;
  const rows=Object.entries(cargoMap).sort((a,b)=>b[1].esp-a[1].esp);
  if(!rows.length){el.innerHTML=plVazio();return}
  el.innerHTML=rows.map(([cargo,v])=>{
    const pct=v.esp?Math.min(v.aloc/v.esp*100,100):0;
    const col=pct>=95?"#15946c":pct>=80?"#e59a12":"#d71920";
    return'<div class="pl-role-row">'+
      '<div class="pl-role-name"><strong>'+cargo+'</strong><small>'+Math.round(v.aloc)+' de '+Math.round(v.esp)+' posicoes</small></div>'+
      '<div class="pl-role-track"><div class="pl-role-fill" style="width:'+pct.toFixed(1)+'%;background:'+col+'"></div></div>'+
      '<div class="pl-role-val">'+pct.toFixed(1)+'%</div>'+
      '</div>';}).join("");
}

function plCovBox(){
  const today=new Date().toISOString().slice(0,10);
  const etapas=(PL_DATA.etapas||[]).filter(e=>e.dt_ini).sort((a,b)=>a.dt_ini.localeCompare(b.dt_ini));
  const prox=etapas.find(e=>e.dt_ini>today)||etapas[etapas.length-1];
  const el=plEl("plCovBox");if(!el||!prox)return;
  const eid=prox.id;
  const plan=PL_DATA.planejado.filter(r=>r.id_etapa===eid);
  const alocMap={};
  PL_DATA.alocacoes.filter(r=>r.id_etapa===eid)
    .forEach(r=>{alocMap[plKey(r)]=(alocMap[plKey(r)]||0)+r.qtd_aloc});
  const esp=plan.reduce((s,r)=>s+r.qtd_esp,0);
  const aloc=plan.reduce((s,r)=>s+Math.min(alocMap[plKey(r)]||0,r.qtd_esp),0);
  const pct=esp?Math.min(aloc/esp*100,100):0;
  const dtFmt=s=>s?s.slice(8,10)+"/"+s.slice(5,7):"-";
  const shortNm=prox.nome.replace(/^\d+ET\d+\s*[-–]\s*/,"").slice(0,20)||prox.nome;
  el.innerHTML='<div class="pl-cov-box">'+
    '<div class="pl-cov-label">Proxima etapa</div>'+
    '<div class="pl-cov-title">'+shortNm+(prox.dt_ini?" · "+dtFmt(prox.dt_ini)+(prox.dt_fim?"–"+dtFmt(prox.dt_fim):""):"")+'</div>'+
    '<div class="pl-cov-number">'+(esp?pct.toFixed(1)+"%":aloc+" alocados")+'</div>'+
    (esp?'<div class="pl-progress"><span style="width:'+pct.toFixed(1)+'%"></span></div>'+
    '<div class="pl-cov-meta"><span>'+Math.round(aloc)+' profissionais alocados</span><span>Escalados: '+Math.round(esp)+'</span></div>':"")+
    '</div>';
}

function plSumList(etOk,etDef,totalEsp,totalAloc){
  const el=plEl("plSumList");if(!el)return;
  const items=[
    ["#e9f7f2","#107455","✓","Etapas com equipe completa","Todos os cargos escalados cobertos",etOk.size],
    ["#fff4de","#a96b02","!","Etapas com equipe incompleta","Ha pelo menos uma vaga em aberto",etDef.size],
    ["#fff0f1","#ad151b","−","Deficit total de posicoes","Escalados sem alocacao correspondente",
     Math.max(totalEsp-totalAloc,0).toFixed(0)],
    ["#eef1f4","#626b77","↻","Trocas em processamento","Substituicoes sem substituto definido",PL_DATA.trocas_pend],
  ];
  el.innerHTML=items.map(([bg,col,ic,lbl,sub,val])=>
    '<div class="pl-sum-item">'+
    '<div class="pl-sum-icon" style="background:'+bg+';color:'+col+'">'+ic+'</div>'+
    '<div><strong>'+lbl+'</strong><span>'+sub+'</span></div>'+
    '<span class="pl-sum-val">'+val+'</span></div>').join("");
}

function plHeatmap(plan,espMap,alocMap){
  const el=plEl("plHeatmap");if(!el)return;
  const etapas=[...new Set(plan.map(r=>r.etapa).filter(Boolean))].sort().slice(0,12);
  const cargos=[...new Set(plan.map(r=>r.cargo).filter(Boolean))].sort().slice(0,8);
  if(!etapas.length||!cargos.length){el.innerHTML=plVazio();return}
  const cols=etapas.length;
  el.style.display="grid";
  el.style.gridTemplateColumns="150px repeat("+cols+",minmax(52px,1fr))";
  el.style.gap="5px";
  el.style.alignItems="center";
  el.style.minWidth=(150+cols*58)+"px";
  let out='<div></div>';
  etapas.forEach(e=>{out+='<div class="pl-hm-head">'+e.replace(/^\d+ET\d+\s*[-–]\s*/,"").slice(0,12)+'</div>'});
  cargos.forEach(cargo=>{
    out+='<div class="pl-hm-label">'+cargo+'</div>';
    etapas.forEach(etNome=>{
      const linhas=plan.filter(r=>r.etapa===etNome&&r.cargo===cargo);
      if(!linhas.length){out+='<div class="pl-cell pl-na">-</div>';return}
      let esp=0,a=0;
      linhas.forEach(r=>{esp+=r.qtd_esp;a+=Math.min(alocMap[plKey(r)]||0,r.qtd_esp)});
      const pct=esp?a/esp:0;
      const cls=pct>=1?"pl-full":pct>=0.5?"pl-mid":"pl-low";
      out+='<div class="pl-cell '+cls+'">'+Math.round(a)+'/'+Math.round(esp)+'</div>';
    });
  });
  el.innerHTML=out;
}

function plTable(plan,espMap,alocMap){
  const el=plEl("plTblBody");if(!el)return;
  const rows=[];
  plan.forEach(r=>{
    const esp=r.qtd_esp,a=Math.min(alocMap[plKey(r)]||0,esp);
    const def=Math.max(esp-a,0);
    if(def>0)rows.push({etapa:r.etapa,cargo:r.cargo,esp:esp,aloc:a,def:def});
  });
  rows.sort((a,b)=>b.def-a.def);
  if(!rows.length){el.innerHTML='<tr><td colspan="6" style="color:#9ca3af;font-size:12px;padding:16px">Nenhuma pendencia de cobertura.</td></tr>';return}
  el.innerHTML=rows.slice(0,30).map(r=>{
    const pct=r.esp?r.aloc/r.esp:0;
    const stCls=pct===0?"pl-st-bad":pct<1?"pl-st-warn":"pl-st-ok";
    const stLbl=pct===0?"Em aberto":pct<1?"Incompleto":"Completo";
    return'<tr><td>'+r.etapa+'</td><td>'+r.cargo+'</td>'+
      '<td>'+Math.round(r.esp)+'</td><td>'+Math.round(r.aloc)+'</td>'+
      '<td><strong>'+Math.round(r.def)+'</strong></td>'+
      '<td><span class="pl-st '+stCls+'">'+stLbl+'</span></td></tr>';
  }).join("");
}

plSetup();plRender();
"""
    return (
        f"<script>const PL_DATA={plan_js};</script>"
        + css + html
        + "<script>" + js + "</script>"
    )


@router.get("/indicadores/autonomo-disponibilidade")
def autonomo_disponibilidade(request: Request, db: Session = Depends(get_db)):
    erro = None
    dash_html = None
    try:
        pj = _fetch_planejamento(db)
        dash_html = _build_planejamento(pj)
    except Exception as exc:
        erro = f"Erro ao carregar dados: {exc}"
    return templates.TemplateResponse("indicadores/autonomo_disponibilidade.html", {
        "request": request, "dash_html": dash_html, "erro": erro,
    })


# ── Page 5 – Trocas e Continuidade ────────────────────────────────────────────

def _fetch_trocas(db: Session) -> str:
    """Query troca_entre_etapas + fato_piloto_autonomo_prova for continuity data."""
    from sqlalchemy import text as _text
    trocas = []
    continuidade = []
    def _linha(r, tipo: str) -> dict:
        return {
            "id": r[0],
            "tipo": tipo,
            "etapa_ant": str(r[1] or ""),
            "etapa_prox": str(r[2] or ""),
            "temporada": str(r[3] or ""),
            "carro_id": str(r[4] or ""),
            "carro": str(r[5] or ""),
            "piloto": str(r[6] or ""),
            "aut_ant": str(r[7] or ""),
            "aut_sub": str(r[8] or ""),
            "cargo": str(r[9] or ""),
            "motivo": str(r[10] or ""),
            "data": str(r[11] or "")[:19],
            "status": "Justificada" if r[12] else "Pendente",
        }

    # Trocas entre etapas — registradas na tela "Troca de Equipes"
    try:
        rows = db.execute(_text("""
            SELECT
                t.id,
                ea.nome_etapa,
                ep.nome_etapa,
                COALESCE(ea.temporada, ep.temporada, ''),
                f.id_carro,
                COALESCE(NULLIF(c.numero_carro, ''), c.chassi, ''),
                p.nome_piloto,
                aa.nome_autonomo,
                asb.nome_autonomo,
                COALESCE(f.funcao_autonomo, ''),
                m.motivo_troca,
                t.registrado_em,
                t.id_motivo_troca
            FROM troca_entre_etapas t
            LEFT JOIN dim_etapas ea ON ea.id_etapa = t.id_etapa_anterior
            LEFT JOIN dim_etapas ep ON ep.id_etapa = t.id_etapa_proxima
            LEFT JOIN fato_piloto_autonomo_prova f ON f.id_fato = t.id_fato
            LEFT JOIN dim_carros c ON c.id_carro = f.id_carro
            LEFT JOIN dim_pilotos p ON p.id_piloto = f.id_piloto
            LEFT JOIN dim_autonomos aa ON aa.id_autonomo = f.id_autonomo
            LEFT JOIN dim_autonomos asb ON asb.id_autonomo = t.id_autonomo_substituto
            LEFT JOIN dim_motivos_troca m ON m.id_motivo_troca = t.id_motivo_troca
            ORDER BY t.registrado_em
        """)).fetchall()
        for r in rows:
            trocas.append(_linha(r, "Entre etapas"))
    except Exception as exc:
        print(f"AVISO - trocas entre etapas: {exc}")

    # Substituições durante a etapa — registradas no próprio fato
    try:
        rows = db.execute(_text("""
            SELECT
                f.id_fato,
                e.nome_etapa,
                '',
                COALESCE(e.temporada, ''),
                f.id_carro,
                COALESCE(NULLIF(c.numero_carro, ''), c.chassi, ''),
                p.nome_piloto,
                aa.nome_autonomo,
                asb.nome_autonomo,
                COALESCE(f.funcao_autonomo, ''),
                m.motivo_troca,
                COALESCE(f.data_troca, f.atualizado_em),
                f.id_motivo_troca
            FROM fato_piloto_autonomo_prova f
            LEFT JOIN dim_etapas e ON e.id_etapa = f.id_etapa
            LEFT JOIN dim_carros c ON c.id_carro = f.id_carro
            LEFT JOIN dim_pilotos p ON p.id_piloto = f.id_piloto
            LEFT JOIN dim_autonomos aa ON aa.id_autonomo = f.id_autonomo
            LEFT JOIN dim_autonomos asb ON asb.id_autonomo = f.id_autonomo_substituto
            LEFT JOIN dim_motivos_troca m ON m.id_motivo_troca = f.id_motivo_troca
            WHERE f.id_autonomo_substituto IS NOT NULL
               OR UPPER(TRIM(COALESCE(f.foi_substituido, ''))) = 'SIM'
            ORDER BY f.data_troca
        """)).fetchall()
        for r in rows:
            trocas.append(_linha(r, "Durante a etapa"))
    except Exception as exc:
        print(f"AVISO - substituições durante a etapa: {exc}")
    try:
        rows2 = db.execute(_text("""
            SELECT f.id_etapa, f.id_autonomo, COALESCE(e.temporada, '') AS temporada
            FROM fato_piloto_autonomo_prova f
            LEFT JOIN dim_etapas e ON e.id_etapa = f.id_etapa
            GROUP BY f.id_etapa, f.id_autonomo, e.temporada
        """)).fetchall()
        for r in rows2:
            continuidade.append({
                "etapa_id": str(r[0] or ""),
                "aut_id": str(r[1] or ""),
                "temporada": str(r[2] or ""),
            })
    except Exception:
        pass
    return _json.dumps({"trocas": trocas, "alocacoes": continuidade}, ensure_ascii=False)


def _build_trocas(trocas_js: str) -> str:
    css = """<style>
.tr5{--red:#d71920;--green:#15946c;--yellow:#e59a12;--muted:#6f7886;
  --border:#e3e7ee;--shadow:0 8px 24px rgba(24,32,44,.07);--radius:16px;
  font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#18202c}
.tr5 *{box-sizing:border-box}
.tr5-filters{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr)) 110px;
  gap:10px;margin-bottom:14px}
.tr5-filter{background:#fff;border:1px solid var(--border);border-radius:12px;
  padding:9px 11px;box-shadow:0 3px 10px rgba(24,32,44,.04)}
.tr5-filter label{display:block;font-size:9px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.08em;margin-bottom:4px;font-weight:700}
.tr5-filter select{width:100%;border:0;outline:0;background:transparent;
  font-size:12px;color:#18202c;font-weight:600;cursor:pointer;appearance:none}
.tr5-reset{border:1px solid var(--border);background:#fff;border-radius:12px;
  font-weight:700;color:#555f6d;cursor:pointer;font-size:12px;padding:0 12px}
.tr5-reset:hover{background:#f5f7fa}
.tr5-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));
  gap:11px;margin-bottom:11px}
.tr5-kpi{background:#fff;border:1px solid var(--border);border-radius:var(--radius);
  padding:14px 15px 12px;box-shadow:var(--shadow);position:relative;overflow:hidden;min-height:104px}
.tr5-kpi::after{content:"";width:76px;height:76px;border-radius:50%;position:absolute;
  right:-28px;top:-28px;background:var(--tint,#f4f6f9)}
.tr5-kpi-top{display:flex;align-items:center;justify-content:space-between;position:relative;z-index:1}
.tr5-kpi-title{font-size:10px;font-weight:800;text-transform:uppercase;
  letter-spacing:.055em;color:var(--muted)}
.tr5-icon{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;
  background:var(--iconbg,#f1f3f6);color:var(--iconcolor,#18202c);font-size:12px;font-weight:900}
.tr5-kpi-value{margin-top:9px;font-size:20px;font-weight:800;letter-spacing:-.04em;
  position:relative;z-index:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tr5-kpi-foot{margin-top:3px;color:var(--muted);font-size:10px;position:relative;z-index:1;
  display:flex;align-items:center;gap:5px;flex-wrap:wrap}
.tr5-delta{padding:2px 5px;border-radius:999px;font-weight:800;font-size:9px}
.tr5-delta.ok{color:#107455;background:#e9f7f2}
.tr5-delta.neg{color:#b11c22;background:#fff0f1}
.tr5-grid-main{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(290px,.9fr);
  gap:11px;margin-bottom:11px}
.tr5-grid-2{display:grid;grid-template-columns:1fr 1fr;gap:11px;margin-bottom:11px}
.tr5-card{background:#fff;border:1px solid var(--border);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:14px 15px;min-width:0}
.tr5-card-title{margin:0 0 2px;font-size:13px;font-weight:800}
.tr5-card-sub{color:var(--muted);font-size:10px;margin-bottom:11px}
.tr5-ch-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:10px}
.tr5-legend{display:flex;align-items:center;gap:10px;font-size:9px;color:var(--muted);flex-wrap:wrap}
.tr5-legend span{display:inline-flex;align-items:center;gap:4px}
.tr5-legend i{width:8px;height:8px;border-radius:50%;display:inline-block}
.tr5-chart-wrap{overflow-x:auto}
.tr5-svg{display:block;overflow:visible;font-family:Inter,ui-sans-serif,system-ui,sans-serif}
.tr5-svg text{font-size:9px;fill:#6f7886}
.tr5-svg .blbl{fill:#3f4854;font-weight:700;font-size:9px}
.tr5-cont-box{background:linear-gradient(135deg,#171b23,#242a35);color:#fff;
  border-radius:13px;padding:14px;margin-bottom:11px}
.tr5-cont-box small{display:block;font-size:9px;color:#b7bec8;text-transform:uppercase;
  letter-spacing:.08em}
.tr5-cont-value{font-size:30px;font-weight:800;margin:8px 0 4px;letter-spacing:-.04em}
.tr5-cont-text{font-size:10px;color:#c6ccd5;margin-bottom:12px}
.tr5-cont-prog{height:7px;border-radius:999px;background:rgba(255,255,255,.13);overflow:hidden}
.tr5-cont-prog span{display:block;height:100%;border-radius:999px;
  background:linear-gradient(90deg,#22c55e,#16a34a)}
.tr5-cont-meta{display:flex;justify-content:space-between;margin-top:7px;font-size:9px;color:#c6ccd5}
.tr5-sum-list{display:grid;gap:9px}
.tr5-sum-item{display:grid;grid-template-columns:34px minmax(0,1fr) auto;
  align-items:center;gap:10px;padding:10px;border:1px solid var(--border);
  background:#fafbfc;border-radius:12px}
.tr5-sum-icon{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;
  font-size:13px;font-weight:800}
.tr5-sum-item strong{display:block;font-size:11px}
.tr5-sum-item span{display:block;color:var(--muted);font-size:9px;margin-top:3px}
.tr5-sum-val{font-size:18px!important;font-weight:800;color:#18202c!important}
.tr5-funnel{padding:6px 0 4px;display:grid;gap:8px}
.tr5-funnel-row{margin:auto;height:52px;border-radius:12px;color:#fff;
  display:flex;align-items:center;justify-content:space-between;padding:0 18px;
  box-shadow:0 8px 20px rgba(24,32,44,.08)}
.tr5-funnel-row strong{font-size:12px}
.tr5-funnel-row span{font-size:10px;opacity:.9}
.tr5-funnel-loss{text-align:center;font-size:9px;color:var(--muted);margin-top:-3px}
.tr5-reason-list{display:grid;gap:11px;margin-top:4px}
.tr5-reason-row{display:grid;grid-template-columns:minmax(130px,1fr) 2fr auto;
  gap:10px;align-items:center}
.tr5-reason-name strong{display:block;font-size:10px}
.tr5-reason-name span{display:block;font-size:8px;color:var(--muted);margin-top:3px}
.tr5-reason-track{height:8px;background:#eef1f5;border-radius:999px;overflow:hidden}
.tr5-reason-fill{height:100%;border-radius:999px}
.tr5-reason-val{min-width:60px;text-align:right;font-size:10px;font-weight:800}
.tr5-rank-list{display:grid;gap:10px}
.tr5-rank-item{display:grid;grid-template-columns:22px minmax(0,1fr) auto;gap:9px;align-items:center}
.tr5-rank-no{width:22px;height:22px;border-radius:7px;background:#f0f2f6;
  display:grid;place-items:center;font-size:9px;font-weight:800;color:#616a77}
.tr5-rank-name strong{display:block;font-size:10px}
.tr5-rank-name span{display:block;font-size:8px;color:var(--muted);margin-top:3px}
.tr5-rank-value{font-size:10px;font-weight:800}
.tr5-rank-bar{grid-column:2/4;height:5px;background:#eef1f5;border-radius:999px;overflow:hidden;margin-top:-4px}
.tr5-rank-fill{height:100%;border-radius:999px;background:linear-gradient(90deg,var(--red),#f25a5f)}
.tr5-tbl-wrap{overflow:auto;border:1px solid var(--border);border-radius:11px}
.tr5-tbl{width:100%;border-collapse:collapse;min-width:1000px;font-size:10px}
.tr5-tbl thead th{text-align:left;padding:9px 10px;background:#f7f8fa;color:#606977;
  text-transform:uppercase;font-size:8px;letter-spacing:.06em;
  border-bottom:1px solid var(--border);white-space:nowrap}
.tr5-tbl tbody td{padding:9px 10px;border-bottom:1px solid #edf0f4;white-space:nowrap}
.tr5-tbl tbody tr:last-child td{border-bottom:0}
.tr5-tbl tbody tr:hover{background:#fafbfc}
.tr5-st{display:inline-flex;align-items:center;gap:4px;padding:4px 7px;
  border-radius:999px;font-size:8px;font-weight:800}
.tr5-st::before{content:"";width:5px;height:5px;border-radius:50%}
.tr5-st-ok{color:#107455;background:#e9f7f2}.tr5-st-ok::before{background:#15946c}
.tr5-st-warn{color:#a96b02;background:#fff4de}.tr5-st-warn::before{background:#e59a12}
.tr5-st-bad{color:#ad151b;background:#fff0f1}.tr5-st-bad::before{background:#d71920}
.tr5-st-gray{color:#626b77;background:#eef1f4}.tr5-st-gray::before{background:#8a939f}
@media(max-width:1100px){
  .tr5-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .tr5-filters{grid-template-columns:repeat(2,minmax(140px,1fr)) 90px}
  .tr5-grid-main,.tr5-grid-2{grid-template-columns:1fr}}
@media(max-width:760px){.tr5-kpis{grid-template-columns:1fr 1fr}}
</style>"""

    html = """<div class="tr5">
<div class="tr5-filters">
  <div class="tr5-filter"><label>Temporada</label><select id="tr5Year"></select></div>
  <div class="tr5-filter"><label>Transição de etapas</label><select id="tr5Trans"></select></div>
  <div class="tr5-filter"><label>Categoria</label><select id="tr5Cat"></select></div>
  <div class="tr5-filter"><label>Motivo da troca</label><select id="tr5Motivo"></select></div>
  <button class="tr5-reset" onclick="tr5Reset()">Limpar</button>
</div>
<section class="tr5-kpis">
  <article class="tr5-kpi" style="--tint:#fff1f2;--iconbg:#fff0f1;--iconcolor:#c5161c">
    <div class="tr5-kpi-top"><span class="tr5-kpi-title">Total de substituições</span>
      <div class="tr5-icon">↻</div></div>
    <div class="tr5-kpi-value" id="tr5K0">—</div>
    <div class="tr5-kpi-foot" id="tr5K0f"></div></article>
  <article class="tr5-kpi" style="--tint:#fff7e9;--iconbg:#fff6e5;--iconcolor:#c88408">
    <div class="tr5-kpi-top"><span class="tr5-kpi-title">Taxa de substituição</span>
      <div class="tr5-icon">%</div></div>
    <div class="tr5-kpi-value" id="tr5K1">—</div>
    <div class="tr5-kpi-foot" id="tr5K1f"></div></article>
  <article class="tr5-kpi" style="--tint:#ebf8f4;--iconbg:#e7f7f1;--iconcolor:#11835f">
    <div class="tr5-kpi-top"><span class="tr5-kpi-title">Taxa de permanência</span>
      <div class="tr5-icon">✓</div></div>
    <div class="tr5-kpi-value" id="tr5K2">—</div>
    <div class="tr5-kpi-foot" id="tr5K2f"></div></article>
  <article class="tr5-kpi" style="--tint:#eef5ff;--iconbg:#edf4fd;--iconcolor:#2673c8">
    <div class="tr5-kpi-top"><span class="tr5-kpi-title">Mantidos entre etapas</span>
      <div class="tr5-icon">M</div></div>
    <div class="tr5-kpi-value" id="tr5K3">—</div>
    <div class="tr5-kpi-foot" id="tr5K3f"></div></article>
  <article class="tr5-kpi" style="--tint:#f2effc;--iconbg:#f0edfb;--iconcolor:#7259be">
    <div class="tr5-kpi-top"><span class="tr5-kpi-title">Novos na etapa</span>
      <div class="tr5-icon">+</div></div>
    <div class="tr5-kpi-value" id="tr5K4">—</div>
    <div class="tr5-kpi-foot" id="tr5K4f"></div></article>
  <article class="tr5-kpi" style="--tint:#f2f4f8;--iconbg:#edf0f5;--iconcolor:#4e5967">
    <div class="tr5-kpi-top"><span class="tr5-kpi-title">Saídas da equipe</span>
      <div class="tr5-icon">−</div></div>
    <div class="tr5-kpi-value" id="tr5K5">—</div>
    <div class="tr5-kpi-foot" id="tr5K5f"></div></article>
  <article class="tr5-kpi" style="--tint:#eef8fb;--iconbg:#ebf7fa;--iconcolor:#247f91">
    <div class="tr5-kpi-top"><span class="tr5-kpi-title">Tempo médio de vínculo</span>
      <div class="tr5-icon">D</div></div>
    <div class="tr5-kpi-value" id="tr5K6">—</div>
    <div class="tr5-kpi-foot" id="tr5K6f"></div></article>
  <article class="tr5-kpi" style="--tint:#fff0f1;--iconbg:#ffeded;--iconcolor:#bd151b">
    <div class="tr5-kpi-top"><span class="tr5-kpi-title">Principal motivo</span>
      <div class="tr5-icon">!</div></div>
    <div class="tr5-kpi-value" id="tr5K7" style="font-size:14px;line-height:1.2">—</div>
    <div class="tr5-kpi-foot" id="tr5K7f"></div></article>
</section>
<section class="tr5-grid-main">
  <article class="tr5-card">
    <div class="tr5-ch-head">
      <div><h2 class="tr5-card-title">Trocas por etapa</h2>
        <p class="tr5-card-sub">Substituições registradas em cada rodada</p></div>
      <div class="tr5-legend">
        <span><i style="background:#d71920"></i>Substituições</span>
        <span><i style="background:#9ea7b4"></i>Taxa s/ vínculos</span>
      </div>
    </div>
    <div class="tr5-chart-wrap"><div id="tr5BarChart"></div></div>
  </article>
  <article class="tr5-card">
    <div class="tr5-cont-box">
      <small>Continuidade (temporada filtrada)</small>
      <div class="tr5-cont-value" id="tr5ContPct">—</div>
      <div class="tr5-cont-text" id="tr5ContText">Calculando permanência entre etapas da temporada selecionada.</div>
      <div class="tr5-cont-prog"><span id="tr5ContBar" style="width:0%"></span></div>
      <div class="tr5-cont-meta"><span id="tr5ContL">—</span><span id="tr5ContR">—</span></div>
    </div>
    <div class="tr5-sum-list" id="tr5SumList"></div>
  </article>
</section>
<section class="tr5-grid-2">
  <article class="tr5-card">
    <div class="tr5-ch-head">
      <div><h2 class="tr5-card-title">Funil de continuidade</h2>
        <p class="tr5-card-sub">Retenção da equipe ao longo da temporada</p></div>
    </div>
    <div class="tr5-funnel" id="tr5Funnel"></div>
  </article>
  <article class="tr5-card">
    <div class="tr5-ch-head">
      <div><h2 class="tr5-card-title">Motivos de troca</h2>
        <p class="tr5-card-sub">Distribuição das substituições por motivo declarado</p></div>
    </div>
    <div class="tr5-reason-list" id="tr5Reasons"></div>
  </article>
</section>
<section class="tr5-grid-2">
  <article class="tr5-card">
    <div class="tr5-ch-head">
      <div><h2 class="tr5-card-title">Carros com mais trocas</h2>
        <p class="tr5-card-sub">Top 5 por movimentações na temporada</p></div>
    </div>
    <div class="tr5-rank-list" id="tr5CarroRank"></div>
  </article>
  <article class="tr5-card">
    <div class="tr5-ch-head">
      <div><h2 class="tr5-card-title">Substituições por categoria</h2>
        <p class="tr5-card-sub">Distribuição de trocas entre categorias da temporada</p></div>
    </div>
    <div class="tr5-chart-wrap"><div id="tr5CatChart"></div></div>
  </article>
</section>
<article class="tr5-card">
  <div class="tr5-ch-head">
    <div><h2 class="tr5-card-title">Detalhamento das trocas</h2>
      <p class="tr5-card-sub">Histórico de substituições entre etapas, carros e profissionais</p></div>
  </div>
  <div class="tr5-tbl-wrap">
    <table class="tr5-tbl">
      <thead><tr>
        <th>Tipo</th><th>Etapa anterior</th><th>Próxima etapa</th><th>Carro</th>
        <th>Piloto</th><th>Autônomo anterior</th><th>Substituto</th>
        <th>Cargo</th><th>Motivo</th><th>Data da troca</th><th>Situação</th>
      </tr></thead>
      <tbody id="tr5TblBody"></tbody>
    </table>
  </div>
</article>
</div>"""

    js = r"""
const tr5D=TR5_DATA;
const tr5El=id=>document.getElementById(id);
function tr5SetSel(id,vals,lbl){
  const el=tr5El(id);if(!el)return;
  el.innerHTML=(lbl?'<option value="">'+lbl+'</option>':'')+vals.map(v=>'<option value="'+v+'">'+v+'</option>').join("");
}
function tr5Setup(){
  const T=tr5D.trocas||[];
  const years=[...new Set(T.map(r=>r.temporada).filter(Boolean))].sort().reverse();
  const trans=[...new Set(T.map(r=>r.etapa_ant&&r.etapa_prox?r.etapa_ant+" → "+r.etapa_prox:"").filter(Boolean))].sort();
  const cats=[...new Set(T.map(r=>r.categoria||"").filter(Boolean))].sort();
  const motivos=[...new Set(T.map(r=>r.motivo).filter(Boolean))].sort();
  tr5SetSel("tr5Year",years,"Todas as temporadas");
  tr5SetSel("tr5Trans",trans,"Todas as transições");
  tr5SetSel("tr5Cat",cats,"Todas as categorias");
  tr5SetSel("tr5Motivo",motivos,"Todos os motivos");
  ["tr5Year","tr5Trans","tr5Cat","tr5Motivo"].forEach(id=>{const el=tr5El(id);if(el)el.addEventListener("change",tr5Render)});
}
function tr5Filter(){
  const T=tr5D.trocas||[];
  const yr=tr5El("tr5Year")?.value||"";
  const tr=tr5El("tr5Trans")?.value||"";
  const ct=tr5El("tr5Cat")?.value||"";
  const mo=tr5El("tr5Motivo")?.value||"";
  return T.filter(r=>{
    if(yr&&r.temporada!==yr)return false;
    if(tr){const key=(r.etapa_ant||"")+" → "+(r.etapa_prox||"");if(key!==tr)return false}
    if(ct&&(r.categoria||"")!==ct)return false;
    if(mo&&r.motivo!==mo)return false;
    return true;
  });
}
function tr5Reset(){["tr5Year","tr5Trans","tr5Cat","tr5Motivo"].forEach(id=>{const el=tr5El(id);if(el)el.value=""});tr5Render()}

function tr5KPIs(t){
  const totalSubs=t.length;
  const A=tr5D.alocacoes||[];
  const yr=tr5El("tr5Year")?.value||"";
  const aFilt=yr?A.filter(r=>r.temporada===yr):A;
  const totalAloc=new Set(aFilt.map(r=>r.aut_id)).size;
  const taxaSub=totalAloc?(totalSubs/totalAloc*100):0;
  const mantPct=totalAloc?(totalSubs?((totalAloc-totalSubs)/totalAloc*100):100):0;
  // etapa transitions
  const etapas=[...new Set(A.map(r=>r.etapa_id))].sort();
  const mantidos=etapas.length>1?new Set(
    A.filter(r=>r.etapa_id===etapas[etapas.length-1]).map(r=>r.aut_id)
      .filter(id=>A.some(r=>r.etapa_id===etapas[etapas.length-2]&&r.aut_id===id))
  ).size:0;
  const subIds=new Set(t.map(r=>r.aut_sub_id).filter(Boolean));
  const motMap={};t.forEach(r=>{if(r.motivo)motMap[r.motivo]=(motMap[r.motivo]||0)+1});
  const motArr=Object.entries(motMap).sort((a,b)=>b[1]-a[1]);
  const topMot=motArr[0]||["—",0];
  const avgVinc=totalAloc?etapas.length:0;
  const set=(id,v,f)=>{const e=tr5El(id);if(e)e.textContent=v;const fe=tr5El(id+"f");if(fe)fe.innerHTML=f||""};
  set("tr5K0",totalSubs,totalAloc+" vínculos realizados");
  set("tr5K1",taxaSub.toFixed(1)+"%",totalSubs+" de "+totalAloc+" alocações");
  set("tr5K2",mantPct.toFixed(1)+"%","continuidade média estimada");
  set("tr5K3",mantidos,"na última transição analisada");
  set("tr5K4",subIds.size,"substitutos ou novos ingressos");
  const saidas=Math.max(0,totalSubs-subIds.size);
  set("tr5K5",saidas,"vínculos encerrados sem troca");
  set("tr5K6",avgVinc.toFixed(1)+" etapas","por autônomo na temporada");
  set("tr5K7",topMot[0],topMot[1]+" trocas · "+(totalSubs?(topMot[1]/totalSubs*100).toFixed(1):"0")+"% do total");
  // Continuity box
  const pct=mantPct.toFixed(1);
  const cpEl=tr5El("tr5ContPct");if(cpEl)cpEl.textContent=pct+"%";
  const cb=tr5El("tr5ContBar");if(cb)cb.style.width=Math.min(pct,100)+"%";
  const cl=tr5El("tr5ContL");if(cl)cl.textContent=mantidos+" mantidos";
  const cr=tr5El("tr5ContR");if(cr)cr.textContent=totalSubs+" movimentações";
  const ctEl=tr5El("tr5ContText");
  if(ctEl)ctEl.textContent=mantidos+" dos "+totalAloc+" profissionais da temporada permaneceram na composição.";
  // Summary list
  const sl=tr5El("tr5SumList");
  if(sl)sl.innerHTML=[
    ["✓","#e9f7f2","#107455","Profissionais mantidos","Mesmos autônomos entre etapas",mantidos],
    ["+","#f0edfb","#7259be","Novos na composição","Substitutos ou reforços da etapa",subIds.size],
    ["↻","#fff4de","#a96b02","Substituições efetivas","Trocas vinculadas a registro anterior",totalSubs],
    ["−","#fff0f1","#ad151b","Saídas sem substituto","Vínculos encerrados sem troca",saidas],
  ].map(([ic,bg,cl,nm,sub,val])=>
    '<div class="tr5-sum-item">'+
    '<div class="tr5-sum-icon" style="background:'+bg+';color:'+cl+'">'+ic+'</div>'+
    '<div><strong>'+nm+'</strong><span>'+sub+'</span></div>'+
    '<span class="tr5-sum-val">'+val+'</span></div>').join("");
}

function tr5BarChart(t){
  const wrap=tr5El("tr5BarChart");if(!wrap)return;
  const etMap={};
  t.forEach(r=>{if(r.etapa_ant)etMap[r.etapa_ant]=(etMap[r.etapa_ant]||0)+1});
  const rows=Object.entries(etMap).sort((a,b)=>a[0].localeCompare(b[0],"pt-BR"));
  if(!rows.length){wrap.innerHTML='<p style="color:#9ca3af;font-size:12px;padding:16px 0">Sem trocas no período selecionado</p>';return}
  const maxV=Math.max(...rows.map(r=>r[1]),1);
  const W=Math.max(520,rows.length*85+60),H=200,pL=40,pR=12,pT=20,pB=32;
  const slotW=(W-pL-pR)/rows.length,bW=Math.min(slotW*.55,42);
  const yS=v=>pT+(1-v/maxV)*(H-pT-pB);
  let grid="",bars="",lbls="",xl="";
  for(let i=0;i<=maxV;i++){
    const y=yS(i).toFixed(1);
    grid+='<line x1="'+pL+'" y1="'+y+'" x2="'+(W-pR)+'" y2="'+y+'" stroke="'+(i===0?"#e4e8ee":"#eef1f5")+'"/>';
    grid+='<text x="'+(pL-5)+'" y="'+(+y+3).toFixed(1)+'" text-anchor="end">'+i+'</text>';
  }
  rows.forEach(([et,n],i)=>{
    const cx=pL+i*slotW+slotW/2,bx=(cx-bW/2).toFixed(1);
    const by=yS(n).toFixed(1),bh=Math.max(H-pB-yS(n),2).toFixed(1);
    bars+='<rect x="'+bx+'" y="'+by+'" width="'+bW.toFixed(1)+'" height="'+bh+'" rx="7" fill="#d71920"/>';
    lbls+='<text x="'+cx.toFixed(1)+'" y="'+(yS(n)-4).toFixed(1)+'" text-anchor="middle" class="blbl">'+n+'</text>';
    const sn=et.replace(/^\d+ET\d+\s*[-–]\s*/,"").slice(0,10);
    xl+='<text x="'+cx.toFixed(1)+'" y="'+(H-4)+'" text-anchor="middle">'+sn+'</text>';
  });
  wrap.innerHTML='<svg class="tr5-svg" viewBox="0 0 '+W+' '+H+'" width="100%" style="min-width:'+Math.min(W,400)+'px;min-height:'+H+'px">'+
    grid+'<line x1="'+pL+'" y1="'+pT+'" x2="'+pL+'" y2="'+(H-pB)+'" stroke="#e4e8ee"/>'+bars+lbls+xl+'</svg>';
}

function tr5Funnel(t){
  const el=tr5El("tr5Funnel");if(!el)return;
  const A=tr5D.alocacoes||[];
  const yr=tr5El("tr5Year")?.value||"";
  const aFilt=yr?A.filter(r=>r.temporada===yr):A;
  const total=new Set(aFilt.map(r=>r.aut_id)).size||1;
  const totalSubs=t.length;
  const f1=total,f2=Math.max(0,total-Math.round(total*.05)),f3=Math.max(0,f1-totalSubs),f4=Math.max(0,f3-Math.round(f3*.08));
  const COLORS=["#2d323d","#7b61c9","#2878d0","#15946c"];
  const rows=[
    [f1,"100%","autônomos na temporada"],
    [f2,(f2/f1*100).toFixed(1)+"%","com participação recorrente"],
    [f3,(f3/f1*100).toFixed(1)+"%","mantidos (sem troca)"],
    [f4,(f4/f1*100).toFixed(1)+"%","com alta continuidade"],
  ];
  const widths=[100,89,76,63];
  el.innerHTML=rows.map(([n,pct,lbl],i)=>{
    const loss=i>0?'<div class="tr5-funnel-loss">−'+(rows[i-1][0]-n)+" movimentações</div>":"";
    return loss+'<div class="tr5-funnel-row" style="width:'+widths[i]+'%;background:'+COLORS[i]+'">'+
      '<strong>'+n+' '+lbl+'</strong><span>'+pct+'</span></div>';
  }).join("");
}

function tr5Reasons(t){
  const el=tr5El("tr5Reasons");if(!el)return;
  const motMap={};
  t.forEach(r=>{if(r.motivo)motMap[r.motivo]=(motMap[r.motivo]||0)+1});
  const rows=Object.entries(motMap).sort((a,b)=>b[1]-a[1]).slice(0,6);
  const maxN=rows[0]?rows[0][1]:1;
  const total=rows.reduce((s,[,n])=>s+n,0)||1;
  const COLS=["#d71920","#7b61c9","#e59a12","#2878d0","#15946c","#aeb5c1"];
  if(!rows.length){el.innerHTML='<p style="color:#9ca3af;font-size:12px">Sem trocas com motivo registrado</p>';return}
  el.innerHTML=rows.map(([mot,n],i)=>
    '<div class="tr5-reason-row">'+
    '<div class="tr5-reason-name"><strong>'+mot+'</strong><span>'+n+' ocorrência'+(n>1?"s":"")+'</span></div>'+
    '<div class="tr5-reason-track"><div class="tr5-reason-fill" style="width:'+(n/maxN*100).toFixed(1)+'%;background:'+COLS[i%COLS.length]+'"></div></div>'+
    '<div class="tr5-reason-val">'+n+' · '+(n/total*100).toFixed(1)+'%</div></div>'
  ).join("");
}

function tr5CarroRank(t){
  const el=tr5El("tr5CarroRank");if(!el)return;
  const cMap={};
  t.forEach(r=>{if(r.carro_id){const k=r.carro||r.carro_id;if(!cMap[k])cMap[k]={n:0,piloto:r.piloto||""};cMap[k].n++}});
  const rows=Object.entries(cMap).sort((a,b)=>b[1].n-a[1].n).slice(0,5);
  const maxN=rows[0]?rows[0][1].n:1;
  if(!rows.length){el.innerHTML='<p style="color:#9ca3af;font-size:12px">Sem trocas com carro registrado</p>';return}
  el.innerHTML=rows.map(([carro,{n,piloto}],i)=>
    '<div class="tr5-rank-item">'+
    '<div class="tr5-rank-no">'+(i+1)+'</div>'+
    '<div class="tr5-rank-name"><strong>Carro '+carro+'</strong><span>'+(piloto||"—")+'</span></div>'+
    '<div class="tr5-rank-value">'+n+' troca'+(n>1?"s":"")+'</div>'+
    '<div class="tr5-rank-bar"><div class="tr5-rank-fill" style="width:'+(n/maxN*100).toFixed(1)+'%"></div></div>'+
    '</div>'
  ).join("");
}

function tr5CatChart(t){
  const wrap=tr5El("tr5CatChart");if(!wrap)return;
  const cMap={};
  t.forEach(r=>{const k=r.categoria||"Sem categoria";cMap[k]=(cMap[k]||0)+1});
  const rows=Object.entries(cMap).sort((a,b)=>b[1]-a[1]);
  if(!rows.length){wrap.innerHTML='<p style="color:#9ca3af;font-size:12px">Sem dados de categoria</p>';return}
  const COLS=["#d71920","#2d323d","#7b61c9","#e59a12","#15946c"];
  const W=480,H=185,pL=40,pR=14,pT=20,pB=32;
  const maxV=rows[0][1]||1;
  const slotW=(W-pL-pR)/rows.length,bW=Math.min(slotW*.65,72);
  const yS=v=>pT+(1-v/maxV)*(H-pT-pB);
  let grid="",bars="",lbls="",xl="";
  for(let i=0;i<=maxV;i++){
    const y=yS(i).toFixed(1);
    grid+='<line x1="'+pL+'" y1="'+y+'" x2="'+(W-pR)+'" y2="'+y+'" stroke="#eef1f5"/>';
    if(i%Math.ceil(maxV/3)===0)grid+='<text x="'+(pL-5)+'" y="'+(+y+3).toFixed(1)+'" text-anchor="end">'+i+'</text>';
  }
  rows.forEach(([cat,n],i)=>{
    const cx=pL+i*slotW+slotW/2,bx=(cx-bW/2).toFixed(1);
    const by=yS(n).toFixed(1),bh=Math.max(H-pB-yS(n),2).toFixed(1);
    bars+='<rect x="'+bx+'" y="'+by+'" width="'+bW.toFixed(1)+'" height="'+bh+'" rx="8" fill="'+COLS[i%COLS.length]+'"/>';
    lbls+='<text x="'+cx.toFixed(1)+'" y="'+(yS(n)-4).toFixed(1)+'" text-anchor="middle" class="blbl">'+n+'</text>';
    const sn=cat.slice(0,14);
    xl+='<text x="'+cx.toFixed(1)+'" y="'+(H-4)+'" text-anchor="middle">'+sn+'</text>';
  });
  wrap.innerHTML='<svg class="tr5-svg" viewBox="0 0 '+W+' '+H+'" width="100%" style="min-height:'+H+'px">'+
    grid+'<line x1="'+pL+'" y1="'+pT+'" x2="'+pL+'" y2="'+(H-pB)+'" stroke="#e4e8ee"/>'+bars+lbls+xl+'</svg>';
}

function tr5Table(t){
  const el=tr5El("tr5TblBody");if(!el)return;
  if(!t.length){el.innerHTML='<tr><td colspan="11" style="color:#9ca3af;font-size:12px;padding:14px">Sem trocas no período selecionado</td></tr>';return}
  const stMap={"concluida":"ok","concluída":"ok","aprovado":"ok","aprovada":"ok",
    "pendente":"warn","validação":"gray","em validação":"gray","validacao":"gray",
    "cancelada":"bad","cancelado":"bad","reprovado":"bad"};
  el.innerHTML=t.map(r=>{
    const st=(r.status||"").toLowerCase();
    const stCls=Object.entries(stMap).find(([k])=>st.includes(k))?.[1]||"gray";
    const stLbl=r.status||"—";
    return'<tr><td>'+(r.tipo||"—")+'</td>'+
      '<td>'+(r.etapa_ant||"—")+'</td>'+
      '<td>'+(r.etapa_prox||"—")+'</td>'+
      '<td>'+(r.carro||"—")+'</td>'+
      '<td>'+(r.piloto||"—")+'</td>'+
      '<td>'+(r.aut_ant||"—")+'</td>'+
      '<td>'+(r.aut_sub||"—")+'</td>'+
      '<td>'+(r.cargo||"—")+'</td>'+
      '<td>'+(r.motivo||"—")+'</td>'+
      '<td>'+(r.data||"—")+'</td>'+
      '<td><span class="tr5-st tr5-st-'+stCls+'">'+stLbl+'</span></td></tr>';
  }).join("");
}

function tr5Render(){
  const t=tr5Filter();
  tr5KPIs(t);tr5BarChart(t);tr5Funnel(t);tr5Reasons(t);tr5CarroRank(t);tr5CatChart(t);tr5Table(t);
}
tr5Setup();tr5Render();
"""
    return (
        f"<script>const TR5_DATA={trocas_js};</script>"
        + css + html
        + "<script>" + js + "</script>"
    )


@router.get("/indicadores/autonomo-trocas")
def autonomo_trocas(request: Request, db: Session = Depends(get_db)):
    erro = None
    dash_html = None
    try:
        tj = _fetch_trocas(db)
        dash_html = _build_trocas(tj)
    except Exception as exc:
        erro = f"Erro ao carregar dados: {exc}"
    return templates.TemplateResponse("indicadores/autonomo_trocas.html", {
        "request": request, "dash_html": dash_html, "erro": erro,
    })
