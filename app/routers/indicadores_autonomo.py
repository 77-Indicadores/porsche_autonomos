"""Indicadores de custo de autônomos – 3 dashboards JS-driven."""
import json as _json

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import FatoPilotoAutonomoProva
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
        )
        .all()
    )
    seen: set = set()
    rows: list = []
    for f in fatos:
        if not (f.valor_fechado_etapa or f.status_pagamento):
            continue
        key = (f.id_etapa, f.id_autonomo, f.id_piloto, f.id_carro)
        if key in seen:
            continue
        seen.add(key)
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
            "categoria":  (car.categoria_padrao or "") if car else "",
            "valor":      float(f.valor_fechado_etapa or 0),
            "dias":       f.dias_trabalhados or 0,
            "status":     str(f.status_pagamento or ""),
            "forma":      str(f.forma_pagamento  or ""),
            "dt_pag":     str(f.data_pagamento   or ""),
        })
    return _json.dumps(rows, ensure_ascii=False)


# ── Page 1 – Visão Geral ───────────────────────────────────────────────────────

def _build_geral(records_js: str) -> str:
    css = """<style>
.acg{--red:#d5001c;--line:#e4e6e9;--shadow:0 10px 30px rgba(12,16,24,.08);
  --radius:18px;font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#16181c}
.acg button,.acg select{font:inherit;cursor:pointer}
.acg .acg-hero{margin-bottom:20px}
.acg .acg-hero h2{margin:0;font-size:26px;font-weight:900;letter-spacing:-.03em}
.acg .acg-hero p{margin:6px 0 0;color:#70747c;font-size:13px}
.acg .acg-filt{display:flex;gap:12px;flex-wrap:wrap;align-items:center;
  padding:14px 16px;margin-bottom:18px;background:#fff;
  border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}
.acg .acg-filt label{font-size:11px;font-weight:800;color:#777;text-transform:uppercase;
  letter-spacing:.07em;margin-right:6px}
.acg .acg-filt select{height:38px;padding:0 32px 0 10px;border:1px solid var(--line);
  border-radius:10px;background:#fafafa;color:#2a2e34;appearance:none;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24'%3E%3Cpath fill='%23777' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 8px center}
.acg .acg-filt select:focus{outline:none;border-color:#aaa;background-color:#fff}
.acg .acg-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));
  gap:14px;margin-bottom:18px}
.acg .acg-kpi{position:relative;overflow:hidden;padding:18px;background:#fff;
  border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}
.acg .acg-kpi::after{content:"";position:absolute;right:-24px;top:-28px;
  width:88px;height:88px;border-radius:50%;background:var(--ks,rgba(213,0,28,.07))}
.acg .acg-kpi-top{position:relative;z-index:1;display:flex;align-items:center;
  justify-content:space-between}
.acg .acg-kpi-icon{width:36px;height:36px;border-radius:10px;display:grid;
  place-items:center;color:var(--kc,var(--red));background:var(--ks,rgba(213,0,28,.08))}
.acg .acg-kpi-icon svg{width:18px;height:18px}
.acg .acg-kpi small{color:#7c8189;font-size:11px;font-weight:750}
.acg .acg-kpi-val{position:relative;z-index:1;margin-top:12px;font-size:26px;
  font-weight:900;line-height:1;letter-spacing:-.04em}
.acg .acg-kpi-lbl{position:relative;z-index:1;margin-top:6px;
  color:#686d75;font-size:12px;font-weight:650}
.acg .acg-grid{display:grid;grid-template-columns:1fr 1.6fr;gap:16px;margin-bottom:18px}
.acg .acg-card{background:#fff;border:1px solid var(--line);
  border-radius:var(--radius);box-shadow:var(--shadow)}
.acg .acg-card-head{display:flex;align-items:flex-start;justify-content:space-between;
  gap:10px;padding:16px 18px 10px}
.acg .acg-card-head h3{margin:0;font-size:14px;letter-spacing:-.015em}
.acg .acg-card-head p{margin:4px 0 0;color:#858990;font-size:11px}
.acg .acg-badge{padding:6px 9px;border-radius:999px;color:#5f646c;
  background:#f4f5f6;font-size:10px;font-weight:800;white-space:nowrap}
.acg .acg-card-body{padding:8px 18px 18px}
.acg .acg-donut-wrap{display:grid;grid-template-columns:130px 1fr;
  gap:16px;align-items:center;min-height:200px}
.acg .acg-donut{width:120px;height:120px;border-radius:50%;
  background:conic-gradient(var(--red) 0 60%,#374151 60% 100%);
  position:relative;display:grid;place-items:center;margin:auto}
.acg .acg-donut::after{content:"";position:absolute;width:76px;height:76px;
  border-radius:50%;background:#fff;box-shadow:0 0 0 1px var(--line)}
.acg .acg-dc{position:relative;z-index:2;text-align:center}
.acg .acg-dc strong{display:block;font-size:18px;font-weight:900;line-height:1}
.acg .acg-dc span{font-size:10px;color:#80848b}
.acg .acg-leg{display:grid;gap:9px}
.acg .acg-lr{display:grid;grid-template-columns:8px minmax(0,1fr) auto;
  align-items:center;gap:8px;font-size:11px}
.acg .acg-lr i{width:8px;height:8px;border-radius:3px}
.acg .acg-lr span{color:#686d75}
.acg .acg-bars{display:grid;gap:9px}
.acg .acg-br{display:grid;gap:4px}
.acg .acg-bm{display:flex;align-items:center;justify-content:space-between;
  gap:10px;font-size:11px}
.acg .acg-bm span{color:#5f646b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.acg .acg-bm strong{font-size:11px;white-space:nowrap}
.acg .acg-bt{height:8px;border-radius:999px;background:#f0f1f3;overflow:hidden}
.acg .acg-bf{height:100%;border-radius:999px;
  background:linear-gradient(90deg,var(--red),#ff3f56);
  transform-origin:left;animation:acggrow .6s ease both}
@keyframes acggrow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.acg .acg-grid2{display:grid;grid-template-columns:1fr;gap:16px}
@media(max-width:900px){
  .acg .acg-kpis{grid-template-columns:repeat(2,1fr)}
  .acg .acg-grid,.acg .acg-grid2{grid-template-columns:1fr}
  .acg .acg-donut-wrap{grid-template-columns:1fr}}
@media(max-width:560px){.acg .acg-kpis{grid-template-columns:1fr}}
</style>"""

    html = """<div class="acg">
<div class="acg-hero">
  <h2>Custo de Autônomos · Visão Geral</h2>
  <p>Investimento total, médias e ranking por piloto</p>
</div>
<div class="acg-filt">
  <label>Temporada</label>
  <select id="acgYear"></select>
  <label style="margin-left:8px">Categoria</label>
  <select id="acgCat"></select>
</div>
<section class="acg-kpis">
  <article class="acg-kpi" style="--kc:#d5001c;--ks:rgba(213,0,28,.08)">
    <div class="acg-kpi-top">
      <div class="acg-kpi-icon">
        <svg fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>
        </svg>
      </div><small>Investimento</small>
    </div>
    <div class="acg-kpi-val" id="acgKTotal">—</div>
    <div class="acg-kpi-lbl">Total investido</div>
  </article>
  <article class="acg-kpi" style="--kc:#7157c8;--ks:rgba(113,87,200,.10)">
    <div class="acg-kpi-top">
      <div class="acg-kpi-icon">
        <svg fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
          <path d="M4 19V9m5 10V5m5 14v-7m5 7V3"/>
        </svg>
      </div><small>Eficiência</small>
    </div>
    <div class="acg-kpi-val" id="acgKMedia">—</div>
    <div class="acg-kpi-lbl">Custo médio / carro</div>
  </article>
  <article class="acg-kpi" style="--kc:#d58a13;--ks:rgba(213,138,19,.11)">
    <div class="acg-kpi-top">
      <div class="acg-kpi-icon">
        <svg fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
          <path d="M12 9v4m0 4h.01M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        </svg>
      </div><small>Financeiro</small>
    </div>
    <div class="acg-kpi-val" id="acgKPend">—</div>
    <div class="acg-kpi-lbl">Valor pendente</div>
  </article>
  <article class="acg-kpi" style="--kc:#15966a;--ks:rgba(21,150,106,.10)">
    <div class="acg-kpi-top">
      <div class="acg-kpi-icon">
        <svg fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>
          <circle cx="9" cy="7" r="4"/>
          <path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>
        </svg>
      </div><small>Equipe</small>
    </div>
    <div class="acg-kpi-val" id="acgKAut">—</div>
    <div class="acg-kpi-lbl">Autônomos ativos</div>
  </article>
</section>
<div class="acg-grid">
  <article class="acg-card">
    <div class="acg-card-head">
      <div><h3>Por categoria</h3><p>Custo total por série</p></div>
      <span class="acg-badge" id="acgCatTotal">—</span>
    </div>
    <div class="acg-card-body acg-donut-wrap">
      <div class="acg-donut" id="acgCatDonut">
        <div class="acg-dc"><strong id="acgCatN">—</strong><span>registros</span></div>
      </div>
      <div class="acg-leg" id="acgCatLeg"></div>
    </div>
  </article>
  <article class="acg-card">
    <div class="acg-card-head">
      <div><h3>Top 10 pilotos por custo</h3><p>Valor total alocado por piloto</p></div>
      <span class="acg-badge">Ranking</span>
    </div>
    <div class="acg-card-body">
      <div class="acg-bars" id="acgPilBars"></div>
    </div>
  </article>
</div>
</div>"""

    js = r"""
const ACG_COLORS=["#d5001c","#374151","#7157c8","#d58a13","#15966a","#ef6b2e"];
const acgEl=id=>document.getElementById(id);
function acgFmt(v){return"R$ "+v.toLocaleString("pt-BR",{minimumFractionDigits:0,maximumFractionDigits:0})}
function acgTc(s){return s?s.split(" ").map(w=>w?w[0].toUpperCase()+w.slice(1).toLowerCase():"").join(" "):""}

function acgFillSel(id,vals,lbl){
  const el=acgEl(id);if(!el)return;
  el.innerHTML='<option value="">'+lbl+'</option>'+vals.map(v=>'<option value="'+v+'">'+v+'</option>').join("");
}
function acgSetup(){
  const years=[...new Set(ACG_RECORDS.map(r=>r.temporada).filter(Boolean))].sort().reverse();
  const cats=[...new Set(ACG_RECORDS.map(r=>r.categoria).filter(Boolean))].sort();
  acgFillSel("acgYear",years,"Todas as temporadas");
  acgFillSel("acgCat",cats,"Todas as categorias");
  ["acgYear","acgCat"].forEach(id=>{const el=acgEl(id);if(el)el.addEventListener("change",acgRender)});
}
function acgFiltered(){
  const yr=acgEl("acgYear")?.value||"",ct=acgEl("acgCat")?.value||"";
  return ACG_RECORDS.filter(r=>(!yr||r.temporada===yr)&&(!ct||r.categoria===ct));
}
function acgRender(){
  const d=acgFiltered();
  const total=d.reduce((s,r)=>s+r.valor,0);
  const pilotos=new Set(d.map(r=>r.piloto_id));
  const pend=d.filter(r=>r.status&&r.status!=="Pago"&&r.status!=="pago").reduce((s,r)=>s+r.valor,0);
  const auts=new Set(d.map(r=>r.autonomo)).size;
  const media=pilotos.size?total/pilotos.size:0;
  if(acgEl("acgKTotal"))acgEl("acgKTotal").textContent=acgFmt(total);
  if(acgEl("acgKMedia"))acgEl("acgKMedia").textContent=acgFmt(media);
  if(acgEl("acgKPend"))acgEl("acgKPend").textContent=acgFmt(pend);
  if(acgEl("acgKAut"))acgEl("acgKAut").textContent=auts;
  // donut categoria
  const catMap={};
  d.forEach(r=>{const k=r.categoria||"Sem categoria";catMap[k]=(catMap[k]||0)+r.valor});
  const catEntries=Object.entries(catMap).sort((a,b)=>b[1]-a[1]);
  const catTotal=catEntries.reduce((s,[,v])=>s+v,0)||1;
  let acc=0;const stops=catEntries.map(([,v])=>{acc+=v/catTotal*100;return acc});
  const dn=acgEl("acgCatDonut");
  if(dn)dn.style.background="conic-gradient("+catEntries.map(([,],i)=>
    ACG_COLORS[i%ACG_COLORS.length]+" "+(stops[i-1]||0).toFixed(2)+"% "+stops[i].toFixed(2)+"%").join(",")+")";
  const cn=acgEl("acgCatN");if(cn)cn.textContent=d.length;
  const ct=acgEl("acgCatTotal");if(ct)ct.textContent=acgFmt(catTotal);
  const leg=acgEl("acgCatLeg");
  if(leg)leg.innerHTML=catEntries.map(([k,v],i)=>
    '<div class="acg-lr"><i style="background:'+ACG_COLORS[i%ACG_COLORS.length]+'"></i>'+
    '<span>'+k+'</span><strong>'+acgFmt(v)+'</strong></div>').join("");
  // top pilotos
  const pilMap={};
  d.forEach(r=>{const k=acgTc(r.piloto)||"—";pilMap[k]=(pilMap[k]||0)+r.valor});
  const pilRows=Object.entries(pilMap).sort((a,b)=>b[1]-a[1]).slice(0,10);
  const pilMax=pilRows[0]?.[1]||1;
  const pb=acgEl("acgPilBars");
  if(pb)pb.innerHTML=pilRows.length?pilRows.map(([n,v])=>
    '<div class="acg-br"><div class="acg-bm"><span title="'+n+'">'+n+'</span><strong>'+acgFmt(v)+'</strong></div>'+
    '<div class="acg-bt"><div class="acg-bf" style="width:'+(v/pilMax*100).toFixed(1)+'%"></div></div></div>').join(""):
    '<p style="color:#888;font-size:12px">Sem dados</p>';
}
acgSetup();acgRender();
"""
    return (f"<script>const ACG_RECORDS={records_js};</script>"
            + css + html
            + "<script>" + js + "</script>")


# ── Page 2 – Evolução & Comparativo ───────────────────────────────────────────

def _build_evolucao(records_js: str) -> str:
    css = """<style>
.ace{--red:#d5001c;--line:#e4e6e9;--shadow:0 10px 30px rgba(12,16,24,.08);
  --radius:18px;font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#16181c}
.ace button,.ace select{font:inherit;cursor:pointer}
.ace .ace-hero{margin-bottom:20px}
.ace .ace-hero h2{margin:0;font-size:26px;font-weight:900;letter-spacing:-.03em}
.ace .ace-hero p{margin:6px 0 0;color:#70747c;font-size:13px}
.ace .ace-filt{display:flex;gap:12px;flex-wrap:wrap;align-items:center;
  padding:14px 16px;margin-bottom:18px;background:#fff;
  border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}
.ace .ace-filt label{font-size:11px;font-weight:800;color:#777;
  text-transform:uppercase;letter-spacing:.07em;margin-right:6px}
.ace .ace-filt select{height:38px;padding:0 32px 0 10px;border:1px solid var(--line);
  border-radius:10px;background:#fafafa;color:#2a2e34;appearance:none;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24'%3E%3Cpath fill='%23777' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 8px center}
.ace .ace-filt select:focus{outline:none;border-color:#aaa;background-color:#fff}
.ace .ace-comp{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));
  gap:14px;margin-bottom:18px}
.ace .ace-kpi{padding:18px;background:#fff;border:1px solid var(--line);
  border-radius:var(--radius);box-shadow:var(--shadow);text-align:center}
.ace .ace-kpi-val{font-size:24px;font-weight:900;letter-spacing:-.04em;
  color:var(--kc,var(--red))}
.ace .ace-kpi-lbl{margin-top:6px;color:#686d75;font-size:12px;font-weight:650}
.ace .ace-kpi-sub{margin-top:4px;font-size:11px;color:#9ca3af}
.ace .ace-card{background:#fff;border:1px solid var(--line);
  border-radius:var(--radius);box-shadow:var(--shadow);margin-bottom:18px}
.ace .ace-card-head{display:flex;align-items:flex-start;justify-content:space-between;
  gap:10px;padding:16px 18px 10px}
.ace .ace-card-head h3{margin:0;font-size:14px;letter-spacing:-.015em}
.ace .ace-card-head p{margin:4px 0 0;color:#858990;font-size:11px}
.ace .ace-badge{padding:6px 9px;border-radius:999px;color:#5f646c;
  background:#f4f5f6;font-size:10px;font-weight:800;white-space:nowrap}
.ace .ace-chart-wrap{padding:8px 18px 18px;overflow-x:auto}
.ace .ace-svg{display:block;min-width:500px}
.ace .ace-al{fill:#8a8e95;font-size:9px}
.ace .ace-vl{fill:#292d32;font-size:9px;font-weight:800}
.ace .ace-leg-row{display:flex;gap:16px;padding:0 18px 14px;flex-wrap:wrap}
.ace .ace-leg-item{display:flex;align-items:center;gap:6px;font-size:11px;color:#545961}
.ace .ace-leg-item i{width:12px;height:8px;border-radius:2px}
@media(max-width:700px){
  .ace .ace-comp{grid-template-columns:1fr 1fr}
  .ace .ace-comp .ace-kpi:last-child{grid-column:1/-1}}
</style>"""

    html = """<div class="ace">
<div class="ace-hero">
  <h2>Custo de Autônomos · Evolução</h2>
  <p>Comparativo de custo médio por carro entre temporadas</p>
</div>
<div class="ace-filt">
  <label>Categoria</label>
  <select id="aceCat"></select>
</div>
<div class="ace-comp">
  <div class="ace-kpi">
    <div class="ace-kpi-val" id="aceK24" style="--kc:#374151">—</div>
    <div class="ace-kpi-lbl">Custo médio/carro</div>
    <div class="ace-kpi-sub" id="aceY1">—</div>
  </div>
  <div class="ace-kpi">
    <div class="ace-kpi-val" id="aceK25">—</div>
    <div class="ace-kpi-lbl">Custo médio/carro</div>
    <div class="ace-kpi-sub" id="aceY2">—</div>
  </div>
  <div class="ace-kpi">
    <div class="ace-kpi-val" id="aceKVar" style="--kc:#15966a">—</div>
    <div class="ace-kpi-lbl">Variação</div>
    <div class="ace-kpi-sub">entre temporadas</div>
  </div>
</div>
<article class="ace-card">
  <div class="ace-card-head">
    <div><h3>Custo médio / carro por etapa</h3>
    <p>Comparativo entre temporadas (barras agrupadas)</p></div>
    <span class="ace-badge" id="aceBadge">—</span>
  </div>
  <div class="ace-leg-row" id="aceLeg"></div>
  <div class="ace-chart-wrap">
    <div id="aceChart"></div>
  </div>
</article>
</div>"""

    js = r"""
const ACE_COLORS={"A":"#374151","B":"#d5001c"};
const aceEl=id=>document.getElementById(id);
function aceFmt(v){return"R$ "+v.toLocaleString("pt-BR",{minimumFractionDigits:0,maximumFractionDigits:0})}

function aceFillSel(id,vals,lbl){
  const el=aceEl(id);if(!el)return;
  el.innerHTML='<option value="">'+lbl+'</option>'+vals.map(v=>'<option value="'+v+'">'+v+'</option>').join("");
}
function aceSetup(){
  const cats=[...new Set(ACE_RECORDS.map(r=>r.categoria).filter(Boolean))].sort();
  aceFillSel("aceCat",cats,"Todas as categorias");
  ["aceCat"].forEach(id=>{const el=aceEl(id);if(el)el.addEventListener("change",aceRender)});
}
function aceFiltered(){
  const ct=aceEl("aceCat")?.value||"";
  return ACE_RECORDS.filter(r=>!ct||r.categoria===ct);
}

function aceMediaPorCarro(data,temporada){
  // custo total por etapa / num de pilotos distintos nessa temporada+etapa
  const etapas={};
  data.filter(r=>r.temporada===temporada).forEach(r=>{
    if(!etapas[r.etapa])etapas[r.etapa]={val:0,pilotos:new Set()};
    etapas[r.etapa].val+=r.valor;
    etapas[r.etapa].pilotos.add(r.piloto_id);
  });
  const items=Object.entries(etapas).map(([et,v])=>({
    et,media:v.pilotos.size?v.val/v.pilotos.size:0
  })).sort((a,b)=>a.et.localeCompare(b.et,"pt-BR"));
  return items;
}

function aceRender(){
  const d=aceFiltered();
  const years=[...new Set(d.map(r=>r.temporada).filter(Boolean))].sort();
  const y1=years[0]||"",y2=years[1]||"";

  // summary KPIs
  const m1=aceMediaPorCarro(d,y1);const m2=aceMediaPorCarro(d,y2);
  const avg1=m1.length?m1.reduce((s,r)=>s+r.media,0)/m1.length:0;
  const avg2=m2.length?m2.reduce((s,r)=>s+r.media,0)/m2.length:0;
  const varPct=avg1?((avg2-avg1)/avg1*100):0;
  if(aceEl("aceK24"))aceEl("aceK24").textContent=avg1?aceFmt(avg1):"—";
  if(aceEl("aceK25"))aceEl("aceK25").textContent=avg2?aceFmt(avg2):"—";
  if(aceEl("aceY1"))aceEl("aceY1").textContent=y1||"—";
  if(aceEl("aceY2"))aceEl("aceY2").textContent=y2||"—";
  const kv=aceEl("aceKVar");
  if(kv){
    kv.textContent=avg1?(varPct>0?"+":"")+varPct.toFixed(1)+"%":"—";
    kv.style.setProperty("--kc",varPct>0?"#d5001c":"#15966a");
  }

  // grouped bar chart
  const allEtapas=[...new Set([...m1.map(r=>r.et),...m2.map(r=>r.et)])].sort((a,b)=>a.localeCompare(b,"pt-BR"));
  const badgeEl=aceEl("aceBadge");
  if(badgeEl)badgeEl.textContent=allEtapas.length+" etapas";
  const legEl=aceEl("aceLeg");
  if(legEl)legEl.innerHTML=[y1,y2].filter(Boolean).map((yr,i)=>
    '<div class="ace-leg-item"><i style="background:'+(i===0?"#374151":"#d5001c")+'"></i>'+yr+'</div>').join("");

  const W=Math.max(600,allEtapas.length*90+80),H=240,pb=30,pt=16,pl=8,pr=8;
  const map1=Object.fromEntries(m1.map(r=>[r.et,r.media]));
  const map2=Object.fromEntries(m2.map(r=>[r.et,r.media]));
  const allVals=[...m1,...m2].map(r=>r.media).filter(Boolean);
  const maxV=Math.max(...allVals,1);
  const slotW=(W-pl-pr)/allEtapas.length;
  const bw=Math.min(slotW*0.35,28);
  const yf=v=>H-pb-v/maxV*(H-pt-pb);

  let bars="";let xlbls="";
  allEtapas.forEach((et,i)=>{
    const cx=pl+i*slotW+slotW/2;
    const v1=map1[et]||0;const v2=map2[et]||0;
    const x1=cx-bw-2;const x2=cx+2;
    const h1=v1/maxV*(H-pt-pb);const h2=v2/maxV*(H-pt-pb);
    if(v1)bars+='<rect x="'+x1.toFixed(1)+'" y="'+yf(v1).toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+h1.toFixed(1)+'" fill="#374151" rx="3"/>';
    if(v2)bars+='<rect x="'+x2.toFixed(1)+'" y="'+yf(v2).toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+h2.toFixed(1)+'" fill="#d5001c" rx="3"/>';
    // short label
    const shortEt=et.replace(/^\d+ET\d+\s*[-–]\s*/,"").slice(0,10);
    xlbls+='<text class="ace-al" x="'+cx.toFixed(1)+'" y="'+(H-5)+'" text-anchor="middle">'+shortEt+'</text>';
  });

  const chart=aceEl("aceChart");
  if(chart)chart.innerHTML='<svg class="ace-svg" viewBox="0 0 '+W+' '+H+'" width="'+W+'" height="'+H+'">'+bars+xlbls+'</svg>';
}
aceSetup();aceRender();
"""
    return (f"<script>const ACE_RECORDS={records_js};</script>"
            + css + html
            + "<script>" + js + "</script>")


# ── Page 3 – Pagamentos ────────────────────────────────────────────────────────

def _build_pagamentos(records_js: str) -> str:
    css = """<style>
.acp{--red:#d5001c;--line:#e4e6e9;--shadow:0 10px 30px rgba(12,16,24,.08);
  --radius:18px;font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#16181c}
.acp button,.acp select{font:inherit;cursor:pointer}
.acp .acp-hero{margin-bottom:20px}
.acp .acp-hero h2{margin:0;font-size:26px;font-weight:900;letter-spacing:-.03em}
.acp .acp-hero p{margin:6px 0 0;color:#70747c;font-size:13px}
.acp .acp-filt{display:flex;gap:12px;flex-wrap:wrap;align-items:center;
  padding:14px 16px;margin-bottom:18px;background:#fff;
  border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}
.acp .acp-filt label{font-size:11px;font-weight:800;color:#777;
  text-transform:uppercase;letter-spacing:.07em;margin-right:6px}
.acp .acp-filt select{height:38px;padding:0 32px 0 10px;border:1px solid var(--line);
  border-radius:10px;background:#fafafa;color:#2a2e34;appearance:none;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24'%3E%3Cpath fill='%23777' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 8px center}
.acp .acp-filt select:focus{outline:none;border-color:#aaa;background-color:#fff}
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
.acp .acp-pend-row{display:grid;grid-template-columns:minmax(0,1fr) 120px 110px;
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
  <label>Temporada</label>
  <select id="acpYear"></select>
  <label style="margin-left:8px">Categoria</label>
  <select id="acpCat"></select>
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
    <h3>Pagamentos pendentes por autônomo</h3>
    <span class="acp-badge" id="acpPendBadge">—</span>
  </div>
  <div class="acp-pend-list">
    <div class="acp-pend-row hdr">
      <span>Autônomo</span><span>Valor</span><span>Status</span>
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
  d.filter(r=>r.forma).forEach(r=>{const k=r.forma;fMap[k]=(fMap[k]||0)+r.valor});
  const fRows=Object.entries(fMap).sort((a,b)=>b[1]-a[1]);
  const fMax=fRows[0]?.[1]||1;
  const fb=acpEl("acpFormaBars");
  if(fb)fb.innerHTML=fRows.length?fRows.map(([n,v],i)=>
    '<div class="acp-br"><div class="acp-bm"><span>'+n+'</span><strong>'+acpFmt(v)+'</strong></div>'+
    '<div class="acp-bt"><div class="acp-bf" style="width:'+(v/fMax*100).toFixed(1)+'%;background:'+ACP_FORMA_COLORS[i%ACP_FORMA_COLORS.length]+'"></div></div></div>').join(""):
    '<p style="color:#888;font-size:12px">Sem dados de forma de pagamento</p>';

  // pendentes list
  const pendMap={};
  d.filter(r=>acpNormSt(r.status)!=="Pago").forEach(r=>{
    const k=acpTc(r.autonomo)||"—";
    if(!pendMap[k])pendMap[k]={valor:0,status:acpNormSt(r.status)};
    pendMap[k].valor+=r.valor;
  });
  const pendRows=Object.entries(pendMap).sort((a,b)=>b[1].valor-a[1].valor);
  const pb2=acpEl("acpPendBadge");if(pb2)pb2.textContent=pendRows.length+" autônomos";
  const pr2=acpEl("acpPendRows");
  if(pr2)pr2.innerHTML=pendRows.length?pendRows.map(([n,v])=>{
    const stClass=v.status==="Pendente"?"acp-st-pend":v.status==="Pago"?"acp-st-pago":"acp-st-sem";
    return'<div class="acp-pend-row"><span title="'+n+'">'+n+'</span>'+
      '<strong>'+acpFmt(v.valor)+'</strong>'+
      '<span class="acp-status '+stClass+'">'+v.status+'</span></div>';}).join(""):
    '<div class="acp-pend-row" style="color:#888;font-size:12px;padding:16px 18px">Nenhum pagamento pendente.</div>';
}
acpSetup();acpRender();
"""
    return (f"<script>const ACP_RECORDS={records_js};</script>"
            + css + html
            + "<script>" + js + "</script>")


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/indicadores/autonomo-custo")
def autonomo_custo_geral(request: Request, db: Session = Depends(get_db)):
    erro = None
    dash_html = None
    try:
        rj = _fetch(db)
        dash_html = _build_geral(rj)
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
        dash_html = _build_evolucao(rj)
    except Exception as exc:
        erro = f"Erro ao carregar dados: {exc}"
    return templates.TemplateResponse("indicadores/autonomo_custo_evolucao.html", {
        "request": request, "dash_html": dash_html, "erro": erro,
    })


@router.get("/indicadores/autonomo-custo-pagamentos")
def autonomo_custo_pagamentos(request: Request, db: Session = Depends(get_db)):
    erro = None
    dash_html = None
    try:
        rj = _fetch(db)
        dash_html = _build_pagamentos(rj)
    except Exception as exc:
        erro = f"Erro ao carregar dados: {exc}"
    return templates.TemplateResponse("indicadores/autonomo_custo_pagamentos.html", {
        "request": request, "dash_html": dash_html, "erro": erro,
    })
