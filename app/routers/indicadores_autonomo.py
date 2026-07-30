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
            "categoria":  (f.prova.tipo_prova.nome_tipo_prova if f.prova and f.prova.tipo_prova else None) or (car.categoria_padrao if car else "") or "",
            "valor":      float(f.valor_fechado_etapa or 0),
            "dias":       f.dias_trabalhados or 0,
            "status":     str(f.status_pagamento or ""),
            "forma":      str(f.forma_pagamento  or ""),
            "dt_pag":     str(f.data_pagamento   or ""),
            "foi_sub":    str(getattr(f, "foi_substituido", "") or ""),
        })
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


# ── Page 1 – Visão Geral ───────────────────────────────────────────────────────

def _build_geral(records_js: str, meta_js: str) -> str:
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
.vg-kpi-title{font-size:9px;font-weight:800;text-transform:uppercase;
  letter-spacing:.055em;color:var(--muted)}
.vg-icon{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;
  background:var(--iconbg,#f1f3f6);color:var(--iconcolor,#18202c);font-size:13px;font-weight:900}
.vg-kpi-value{margin-top:9px;font-size:21px;font-weight:800;letter-spacing:-.04em;
  position:relative;z-index:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.vg-kpi-foot{margin-top:3px;color:var(--muted);font-size:9px;position:relative;z-index:1}
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
  <article class="vg-kpi" style="--tint:#fff7e9;--iconbg:#fff6e5;--iconcolor:#c88408">
    <div class="vg-kpi-top"><span class="vg-kpi-title">Valor pendente</span>
      <div class="vg-icon">!</div></div>
    <div class="vg-kpi-value" id="vgK3">—</div>
    <div class="vg-kpi-foot" id="vgK3f"></div></article>
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
    <h2 class="vg-card-title">Pagamentos</h2>
    <p class="vg-card-sub">Distribuição por status de pagamento</p>
    <div class="vg-donut-wrap">
      <div class="vg-donut-host">
        <div class="vg-donut" id="vgDn"></div>
        <div class="vg-donut-center"><strong id="vgDnPct">—</strong><span>pago</span></div>
      </div>
      <div class="vg-donut-legend" id="vgDnLeg"></div>
    </div>
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
  const R=VG_RECORDS;
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
  return VG_RECORDS.filter(r=>
    (!yr||r.temporada===yr)&&(!et||r.etapa===et)&&
    (!ct||r.categoria===ct)&&(!st||vgNormSt(r.status)===st));
}
function vgReset(){["vgYear","vgEtapa","vgCat","vgStatus"].forEach(id=>{const el=vgEl(id);if(el)el.value=""});vgRender()}

function vgKPIs(d){
  const total=d.reduce((s,r)=>s+(r.valor||0),0);
  const carros=new Set(d.map(r=>r.carro_id).filter(Boolean));
  const pilotos=new Set(d.map(r=>r.piloto_id).filter(Boolean));
  const media=carros.size?total/carros.size:0;
  const pago=d.filter(r=>vgNormSt(r.status)==="Pago").reduce((s,r)=>s+(r.valor||0),0);
  const pend=d.filter(r=>vgNormSt(r.status)==="Pendente").reduce((s,r)=>s+(r.valor||0),0);
  const auts=new Set(d.map(r=>r.autonomo).filter(Boolean)).size;
  const dias=d.reduce((s,r)=>s+(r.dias||0),0);
  const mediaDia=dias?total/dias:0;
  const subs=d.filter(r=>r.foi_sub==="Sim").length;
  const set=(id,v,f)=>{const e=vgEl(id);if(e)e.textContent=v;const fe=vgEl(id+"f");if(fe)fe.innerHTML=f||""};
  set("vgK0",vgFmt(total),carros.size+" carros · "+pilotos.size+" pilotos");
  set("vgK1",vgFmt(media),carros.size+" carros atendidos");
  set("vgK2",vgFmt(pago),total?'<span class="vg-delta">'+((pago/total)*100).toFixed(1)+'%</span> do total':"");
  set("vgK3",vgFmt(pend),total?(pend/total*100).toFixed(1)+"% do total":"");
  set("vgK4",auts,pilotos.size+" pilotos");
  set("vgK5",carros.size,"carros cobertos na seleção");
  set("vgK6",vgFmt(mediaDia),"por profissional/dia");
  set("vgK7",subs,d.length?"taxa "+(subs/d.length*100).toFixed(1)+"%":"");
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

function vgDonut(d){
  const pago=d.filter(r=>vgNormSt(r.status)==="Pago").reduce((s,r)=>s+(r.valor||0),0);
  const pend=d.filter(r=>vgNormSt(r.status)==="Pendente").reduce((s,r)=>s+(r.valor||0),0);
  const sem=d.filter(r=>vgNormSt(r.status)==="Sem status").reduce((s,r)=>s+(r.valor||0),0);
  const tot=pago+pend+sem||1;
  const pp=pago/tot*100,pe=pend/tot*100;
  const dn=vgEl("vgDn");
  if(dn)dn.style.background="conic-gradient(#15946c 0 "+pp.toFixed(2)+"%, #e59a12 "+pp.toFixed(2)+"% "+(pp+pe).toFixed(2)+"%, #d1d5db "+(pp+pe).toFixed(2)+"% 100%)";
  const pc=vgEl("vgDnPct");if(pc)pc.textContent=pp.toFixed(1)+"%";
  const leg=vgEl("vgDnLeg");
  if(leg)leg.innerHTML=[["#15946c","Pago",pago],["#e59a12","Pendente",pend],["#d1d5db","Sem status",sem]]
    .filter(([,,v])=>v>0).map(([c,l,v])=>
      '<div class="vg-donut-row"><span><span class="vg-dot" style="background:'+c+'"></span>'+l+'</span><strong>'+vgFmt(v)+'</strong></div>').join("");
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
  d.forEach(r=>{
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
  vgKPIs(d);vgEtapaChart(d);vgDonut(d);vgCatBars(d);vgRanking(d);vgProxEtapa();
}
vgSetup();vgRender();
"""
    return (
        f"<script>const VG_RECORDS={records_js};const VG_META={meta_js};</script>"
        + css + html
        + "<script>" + js + "</script>"
    )


# ── Page 2 – Evolução & Comparativo ───────────────────────────────────────────

def _build_evolucao(records_js: str) -> str:
    css = """<style>
.ace{--red:#d5001c;--line:#e4e6e9;--shadow:0 10px 30px rgba(12,16,24,.08);
  --radius:18px;font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#16181c}
.ace button,.ace select{font:inherit;cursor:pointer}
.ace .ace-hero{margin-bottom:20px}
.ace .ace-hero h2{margin:0;font-size:26px;font-weight:900;letter-spacing:-.03em}
.ace .ace-hero p{margin:6px 0 0;color:#70747c;font-size:13px}
.ace .ace-filt{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:18px}
.ace .ace-fi{position:relative;display:flex;flex-direction:column;gap:3px;
  padding:8px 36px 8px 12px;border:1px solid var(--line);border-radius:12px;
  background:#fff;box-shadow:0 2px 8px rgba(12,16,24,.06);min-width:130px}
.ace .ace-fi::after{content:"";position:absolute;right:10px;top:50%;
  transform:translateY(-50%);width:16px;height:16px;pointer-events:none;
  background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23888' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E") no-repeat center/contain}
.ace .ace-fi-lbl{font-size:10px;font-weight:800;color:#9ca3af;
  text-transform:uppercase;letter-spacing:.07em;line-height:1;pointer-events:none}
.ace .ace-fi-sel{border:none;outline:none;background:transparent;
  font-size:14px;font-weight:600;color:#16181c;appearance:none;
  cursor:pointer;padding:0;line-height:1.3;width:100%}
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
  <div class="ace-fi">
    <span class="ace-fi-lbl">Categoria</span>
    <select class="ace-fi-sel" id="aceCat"></select>
  </div>
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
        mj = _fetch_meta(db)
        dash_html = _build_geral(rj, mj)
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


# ── Page 4 – Planejamento e Cobertura ─────────────────────────────────────────

def _fetch_planejamento(db: Session) -> str:
    """Return composicao_padrao_equipe + fato records aggregated for coverage page."""
    from sqlalchemy import text as _text
    # Expected composition per etapa/carro/cargo
    try:
        comp_rows = db.execute(_text("""
            SELECT cp.id_etapa, cp.id_carro, cp.id_cargo, cp.qtd_esperada,
                   e.nome_etapa, e.data_inicio, e.data_fim, e.temporada,
                   ca.nome_cargo_autonomo,
                   c.numero_carro
            FROM composicao_padrao_equipe cp
            LEFT JOIN dim_etapas e ON e.id_etapa = cp.id_etapa
            LEFT JOIN dim_cargos_autonomos ca ON ca.id_cargo_autonomo = cp.id_cargo
            LEFT JOIN dim_carros c ON c.id_carro = cp.id_carro
        """)).fetchall()
        composicao = [{"id_etapa": r[0], "id_carro": r[1], "id_cargo": r[2],
                       "qtd_esp": float(r[3] or 0), "etapa": r[4] or "",
                       "dt_ini": str(r[5] or ""), "dt_fim": str(r[6] or ""),
                       "temporada": str(r[7] or ""), "cargo": r[8] or "",
                       "carro": str(r[9] or "")} for r in comp_rows]
    except Exception:
        composicao = []
    # Actual allocations aggregated per etapa/carro/cargo
    try:
        aloc_rows = db.execute(_text("""
            SELECT f.id_etapa, f.id_carro, f.id_cargo_autonomo,
                   COUNT(DISTINCT f.id_autonomo) as qtd_aloc,
                   e.nome_etapa, e.temporada
            FROM fato_piloto_autonomo_prova f
            LEFT JOIN dim_etapas e ON e.id_etapa = f.id_etapa
            WHERE f.id_carro IS NOT NULL
            GROUP BY f.id_etapa, f.id_carro, f.id_cargo_autonomo
        """)).fetchall()
        alocacoes = [{"id_etapa": r[0], "id_carro": r[1], "id_cargo": r[2],
                      "qtd_aloc": int(r[3] or 0), "etapa": r[4] or "",
                      "temporada": str(r[5] or "")} for r in aloc_rows]
    except Exception:
        alocacoes = []
    # Pending swaps
    try:
        troca_rows = db.execute(_text(
            "SELECT COUNT(*) FROM troca_entre_etapas WHERE id_autonomo_substituto IS NULL"
        )).fetchone()
        trocas_pend = int(troca_rows[0] or 0) if troca_rows else 0
    except Exception:
        trocas_pend = 0
    # Etapas
    try:
        et_rows = db.execute(_text(
            "SELECT id_etapa, nome_etapa, data_inicio, data_fim, temporada FROM dim_etapas ORDER BY data_inicio"
        )).fetchall()
        etapas = [{"id": r[0], "nome": r[1] or "", "dt_ini": str(r[2] or ""),
                   "dt_fim": str(r[3] or ""), "temporada": str(r[4] or "")} for r in et_rows]
    except Exception:
        etapas = []
    return _json.dumps({
        "composicao": composicao,
        "alocacoes": alocacoes,
        "trocas_pend": trocas_pend,
        "etapas": etapas,
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
.pl-kpi-title{font-size:9px;font-weight:800;text-transform:uppercase;
  letter-spacing:.055em;color:var(--muted)}
.pl-icon{width:29px;height:29px;border-radius:8px;display:grid;place-items:center;
  background:var(--iconbg,#f1f3f6);color:var(--iconcolor,#18202c);font-size:12px;font-weight:900}
.pl-kpi-value{margin-top:8px;font-size:22px;font-weight:800;letter-spacing:-.04em;
  position:relative;z-index:1}
.pl-kpi-foot{margin-top:3px;color:var(--muted);font-size:9px;position:relative;z-index:1}
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
    <div class="pl-kpi-foot">posições na composição padrão</div></article>
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
    <div class="pl-kpi-top"><span class="pl-kpi-title">Carros completos</span>
      <div class="pl-icon">▣</div></div>
    <div class="pl-kpi-value" id="plKCarros">—</div>
    <div class="pl-kpi-foot" id="plKCarrosF"></div></article>
  <article class="pl-kpi" style="--tint:#fff7e9;--iconbg:#fff6e5;--iconcolor:#c88408">
    <div class="pl-kpi-top"><span class="pl-kpi-title">Carros incompletos</span>
      <div class="pl-icon">C</div></div>
    <div class="pl-kpi-value" id="plKInc">—</div>
    <div class="pl-kpi-foot">carros com alguma vaga aberta</div></article>
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
    <div><h2 class="pl-card-title">Mapa de cobertura por carro</h2>
      <p class="pl-card-sub">Situação dos cargos por carro na seleção atual</p></div>
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
      <p class="pl-card-sub">Combinações carro × cargo com déficit de alocação</p></div>
  </div>
  <div class="pl-tbl-wrap">
    <table class="pl-tbl">
      <thead><tr>
        <th>Etapa</th><th>Carro</th><th>Cargo</th>
        <th>Esperado</th><th>Alocado</th><th>Déficit</th><th>Situação</th>
      </tr></thead>
      <tbody id="plTblBody"></tbody>
    </table>
  </div>
</article>
</div>"""

    js = r"""
const plEl=id=>document.getElementById(id);
function plFillSel(id,vals,lbl){
  const el=plEl(id);if(!el)return;
  el.innerHTML='<option value="">'+lbl+'</option>'+vals.map(v=>'<option value="'+v+'">'+v+'</option>').join("");
}
function plSetup(){
  const years=[...new Set(PL_DATA.etapas.map(e=>e.temporada).filter(Boolean))].sort().reverse();
  const etapas=[...new Set(PL_DATA.composicao.map(r=>r.etapa).filter(Boolean))].sort();
  plFillSel("plYear",years,"Todas as temporadas");
  plFillSel("plEtapa",etapas,"Todas as etapas");
  plFillSel("plCat",[],"Todas as categorias");
  ["plYear","plEtapa","plCat"].forEach(id=>{const el=plEl(id);if(el)el.addEventListener("change",plRender)});
}
function plReset(){["plYear","plEtapa","plCat"].forEach(id=>{const el=plEl(id);if(el)el.value=""});plRender()}

function plFilteredComp(){
  const yr=plEl("plYear")?.value||"",et=plEl("plEtapa")?.value||"";
  return PL_DATA.composicao.filter(r=>(!yr||r.temporada===yr)&&(!et||r.etapa===et));
}
function plFilteredAloc(){
  const yr=plEl("plYear")?.value||"",et=plEl("plEtapa")?.value||"";
  return PL_DATA.alocacoes.filter(r=>(!yr||r.temporada===yr)&&(!et||r.etapa===et));
}

function plRender(){
  const comp=plFilteredComp();
  const aloc=plFilteredAloc();
  // Build lookup: etapa+carro+cargo -> {esp, aloc}
  const key=(et,car,cargo)=>et+"|"+car+"|"+cargo;
  const espMap={};
  comp.forEach(r=>{const k=key(r.id_etapa,r.id_carro,r.id_cargo);espMap[k]=(espMap[k]||0)+r.qtd_esp});
  const alocMap={};
  aloc.forEach(r=>{const k=key(r.id_etapa,r.id_carro,r.id_cargo);alocMap[k]=(alocMap[k]||0)+r.qtd_aloc});
  // KPIs
  const totalEsp=comp.reduce((s,r)=>s+r.qtd_esp,0);
  const totalAloc=aloc.reduce((s,r)=>s+r.qtd_aloc,0);
  const deficit=Math.max(totalEsp-totalAloc,0);
  const pct=totalEsp?Math.min(totalAloc/totalEsp*100,100):0;
  // Carros
  const carros=new Set(comp.map(r=>r.id_etapa+"|"+r.id_carro));
  const carrosFull=new Set();const carrosInc=new Set();
  carros.forEach(ck=>{
    const [eid,cid]=ck.split("|");
    const compRows=comp.filter(r=>r.id_etapa==eid&&r.id_carro==cid);
    const ok=compRows.every(r=>{const k=key(r.id_etapa,r.id_carro,r.id_cargo);return(alocMap[k]||0)>=r.qtd_esp});
    if(ok)carrosFull.add(ck);else carrosInc.add(ck);
  });
  // Cargos descobertos
  const cargoMap={};
  comp.forEach(r=>{
    if(!cargoMap[r.cargo])cargoMap[r.cargo]={esp:0,aloc:0};
    cargoMap[r.cargo].esp+=r.qtd_esp;
  });
  aloc.forEach(r=>{
    const cn=comp.find(c=>c.id_etapa===r.id_etapa&&c.id_carro===r.id_carro&&c.id_cargo===r.id_cargo);
    if(cn&&cargoMap[cn.cargo])cargoMap[cn.cargo].aloc+=r.qtd_aloc;
  });
  const cargosDesc=Object.values(cargoMap).filter(v=>v.aloc<v.esp).length;
  const set=(id,v,f)=>{const e=plEl(id);if(e)e.textContent=v;const fe=plEl(id+"f");if(fe)fe.innerHTML=f||""};
  set("plKEsp",Math.round(totalEsp));
  set("plKAloc",Math.round(totalAloc),'<span class="pl-delta '+(pct>=95?"ok":pct>=80?"warn":"bad")+'">'+pct.toFixed(1)+'%</span> de cobertura');
  set("plKVagas",Math.round(deficit),carrosInc.size+" carros com déficit");
  set("plKCarros",carrosFull.size,"de "+(carrosFull.size+carrosInc.size)+" carros participantes");
  set("plKInc",carrosInc.size,"");
  const cobEl=plEl("plKCob");if(cobEl)cobEl.textContent=pct.toFixed(1)+"%";
  const cargosEl=plEl("plKCargos");if(cargosEl)cargosEl.textContent=cargosDesc;
  const trocEl=plEl("plKTrocas");if(trocEl)trocEl.textContent=PL_DATA.trocas_pend;
  plRoleList(comp,aloc,cargoMap);
  plCovBox();
  plSumList(carrosFull,carrosInc,pct);
  plHeatmap(comp,aloc);
  plTable(comp,aloc);
}

function plRoleList(comp,aloc,cargoMap){
  const COLS=["#15946c","#e59a12","#d71920","#7157c8","#2878d0","#374151"];
  const el=plEl("plRoleList");if(!el)return;
  const rows=Object.entries(cargoMap).sort((a,b)=>b[1].esp-a[1].esp);
  if(!rows.length){el.innerHTML='<p style="color:#9ca3af;font-size:11px">Sem dados de composição.</p>';return}
  el.innerHTML=rows.map(([cargo,v],i)=>{
    const pct=v.esp?Math.min(v.aloc/v.esp*100,100):0;
    const col=pct>=95?"#15946c":pct>=80?"#e59a12":"#d71920";
    return'<div class="pl-role-row">'+
      '<div class="pl-role-name"><strong>'+cargo+'</strong><small>'+Math.round(v.aloc)+' de '+Math.round(v.esp)+' posições</small></div>'+
      '<div class="pl-role-track"><div class="pl-role-fill" style="width:'+pct.toFixed(1)+'%;background:'+col+'"></div></div>'+
      '<div class="pl-role-val">'+pct.toFixed(1)+'%</div>'+
      '</div>';}).join("");
}

function plCovBox(){
  const today=new Date().toISOString().slice(0,10);
  const etapas=(PL_DATA.etapas||[]).filter(e=>e.dt_ini).sort((a,b)=>a.dt_ini.localeCompare(b.dt_ini));
  const prox=etapas.find(e=>e.dt_ini>today)||etapas[etapas.length-1];
  const el=plEl("plCovBox");if(!el||!prox)return;
  // Coverage for this specific etapa
  const eid=prox.id;
  const esp=PL_DATA.composicao.filter(r=>r.id_etapa===eid).reduce((s,r)=>s+r.qtd_esp,0);
  const aloc=PL_DATA.alocacoes.filter(r=>r.id_etapa===eid).reduce((s,r)=>s+r.qtd_aloc,0);
  const pct=esp?Math.min(aloc/esp*100,100):0;
  const dtFmt=s=>s?s.slice(8,10)+"/"+s.slice(5,7):"—";
  const shortNm=prox.nome.replace(/^\d+ET\d+\s*[-–]\s*/,"").slice(0,20)||prox.nome;
  el.innerHTML='<div class="pl-cov-box">'+
    '<div class="pl-cov-label">Próxima etapa</div>'+
    '<div class="pl-cov-title">'+shortNm+(prox.dt_ini?" · "+dtFmt(prox.dt_ini)+(prox.dt_fim?"–"+dtFmt(prox.dt_fim):""):"")+'</div>'+
    '<div class="pl-cov-number">'+(esp?pct.toFixed(1)+"%":aloc+" alocados")+'</div>'+
    (esp?'<div class="pl-progress"><span style="width:'+pct.toFixed(1)+'%"></span></div>'+
    '<div class="pl-cov-meta"><span>'+Math.round(aloc)+' profissionais alocados</span><span>Meta: '+Math.round(esp)+'</span></div>':"")+
    '</div>';
}

function plSumList(carrosFull,carrosInc,pct){
  const el=plEl("plSumList");if(!el)return;
  const items=[
    ["#e9f7f2","#107455","✓","Carros com equipe completa","Todos os cargos previstos cobertos",carrosFull.size],
    ["#fff4de","#a96b02","!","Carros com equipe incompleta","Há pelo menos uma vaga em aberto",carrosInc.size],
    ["#fff0f1","#ad151b","−","Déficit total de posições",
     "Posições esperadas sem alocação",Math.max(
       PL_DATA.composicao.reduce((s,r)=>s+r.qtd_esp,0)-
       PL_DATA.alocacoes.reduce((s,r)=>s+r.qtd_aloc,0),0).toFixed(0)],
    ["#eef1f4","#626b77","↻","Trocas em processamento","Substituições sem substituto definido",PL_DATA.trocas_pend],
  ];
  el.innerHTML=items.map(([bg,col,ic,lbl,sub,val])=>
    '<div class="pl-sum-item">'+
    '<div class="pl-sum-icon" style="background:'+bg+';color:'+col+'">'+ic+'</div>'+
    '<div><strong>'+lbl+'</strong><span>'+sub+'</span></div>'+
    '<span class="pl-sum-val">'+val+'</span></div>').join("");
}

function plHeatmap(comp,aloc){
  const el=plEl("plHeatmap");if(!el)return;
  // Get unique cargos and carros (limit display)
  const cargosSet=new Set(comp.map(r=>r.cargo).filter(Boolean));
  const carros=[...new Set(comp.map(r=>r.carro).filter(Boolean))].sort((a,b)=>+a-+b).slice(0,12);
  const cargos=[...cargosSet].sort().slice(0,6);
  if(!carros.length||!cargos.length){el.innerHTML='<p style="color:#9ca3af;font-size:11px">Sem dados de composição.</p>';return}
  // Build alocMap indexed by etapa+carro+cargo
  const alocMap={};
  aloc.forEach(r=>{
    const cn=comp.find(c=>c.id_etapa===r.id_etapa&&c.id_carro===r.id_carro&&c.id_cargo===r.id_cargo);
    if(cn){const k=cn.carro+"|"+cn.cargo;alocMap[k]=(alocMap[k]||0)+r.qtd_aloc}
  });
  const espMap2={};
  comp.forEach(r=>{const k=r.carro+"|"+r.cargo;espMap2[k]=(espMap2[k]||0)+r.qtd_esp});
  const cols=carros.length;
  el.style.display="grid";
  el.style.gridTemplateColumns="120px repeat("+cols+",minmax(40px,1fr))";
  el.style.gap="5px";
  el.style.alignItems="center";
  el.style.minWidth=(120+cols*45)+"px";
  let out='<div></div>';
  carros.forEach(c=>{out+='<div class="pl-hm-head">'+c+'</div>'});
  cargos.forEach(cargo=>{
    out+='<div class="pl-hm-label">'+cargo+'</div>';
    carros.forEach(carro=>{
      const k=carro+"|"+cargo;
      const esp=espMap2[k]||0;const a=alocMap[k]||0;
      if(!esp){out+='<div class="pl-cell pl-na">—</div>';return}
      const pct=a/esp;
      const cls=pct>=1?"pl-full":pct>=0.5?"pl-mid":"pl-low";
      out+='<div class="pl-cell '+cls+'">'+Math.round(a)+'/'+Math.round(esp)+'</div>';
    });
  });
  el.innerHTML=out;
}

function plTable(comp,aloc){
  const el=plEl("plTblBody");if(!el)return;
  // Find deficit rows
  const alocMap={};
  aloc.forEach(r=>{
    const cn=comp.find(c=>c.id_etapa===r.id_etapa&&c.id_carro===r.id_carro&&c.id_cargo===r.id_cargo);
    if(cn){const k=cn.etapa+"|"+cn.carro+"|"+cn.cargo;alocMap[k]=(alocMap[k]||0)+r.qtd_aloc}
  });
  const rows=[];
  const seen=new Set();
  comp.forEach(r=>{
    const k=r.etapa+"|"+r.carro+"|"+r.cargo;
    if(seen.has(k))return;seen.add(k);
    const esp=r.qtd_esp;const a=alocMap[k]||0;
    const def=Math.max(esp-a,0);
    if(def>0)rows.push({etapa:r.etapa,carro:r.carro,cargo:r.cargo,esp,aloc:a,def});
  });
  rows.sort((a,b)=>b.def-a.def);
  if(!rows.length){el.innerHTML='<tr><td colspan="7" style="color:#9ca3af;font-size:12px;padding:16px">Nenhuma pendência de cobertura.</td></tr>';return}
  el.innerHTML=rows.slice(0,30).map(r=>{
    const pct=r.esp?r.aloc/r.esp:0;
    const stCls=pct===0?"pl-st-bad":pct<1?"pl-st-warn":"pl-st-ok";
    const stLbl=pct===0?"Em aberto":pct<1?"Incompleto":"Completo";
    return'<tr><td>'+r.etapa+'</td><td>'+r.carro+'</td><td>'+r.cargo+'</td>'+
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
