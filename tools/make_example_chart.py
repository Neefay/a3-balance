"""Generate an offline interactive SVG example directly from the query database."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


QUERY = """SELECT family, scope, mass, armor, pass_through, count(*) AS class_count,
                  min(classname) AS example_class
           FROM v_headgear_comparison
           WHERE mass IS NOT NULL AND armor IS NOT NULL AND scope IN (0,1,2)
           GROUP BY family, scope, mass, armor, pass_through
           ORDER BY family, scope, armor, mass"""

HTML = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Arma headgear — query example</title>
<style>
body{font:16px system-ui,sans-serif;margin:32px auto;padding:0 20px;max-width:1000px;color:#172534;background:#f5f7fa}
h1{font-size:26px}label{display:inline-block;margin:12px 20px 12px 0}select{font:inherit;padding:5px}
svg{width:100%;background:white;border:1px solid #d8dee6;border-radius:8px}circle:focus{stroke:black;stroke-width:3}
table{border-collapse:collapse;width:100%;background:white;font-size:14px}td,th{padding:7px;text-align:left;border-bottom:1px solid #dde3eb}
.note{color:#4a5867}pre{overflow:auto;background:white;padding:14px}
</style>
<h1>Headgear mass and configured armor</h1>
<p>Loaded configuration values. Proposed balance changes have not been applied.</p>
<label>Reference group <select id="family"><option value="all">All</option><option>Vanilla class</option><option>RHS</option><option>Other</option></select></label>
<label>Visibility <select id="scope"><option value="2">Public (scope 2)</option><option value="all">All numeric scopes</option></select></label>
<p class="note">Blue: vanilla classes; green: RHS; orange: other classes. Hover or focus a point for its values.
Point size indicates how many classes share those values, including cosmetic variants.</p>
<p class="note">Mass uses config units. Armor is a config parameter, not a physical protection rating.
Text expressions, unresolved values, and text-valued scope entries are excluded from this plot.</p>
<p id="count" aria-live="polite"></p>
<svg id="chart" viewBox="0 0 900 480" role="img" aria-label="Scatter plot of headgear mass versus configured armor"></svg>
<h2>Plotted groups</h2><table><thead><tr><th>Group</th><th>Mass</th><th>Armor</th><th>passThrough</th><th>Classes</th><th>Example</th></tr></thead><tbody id="rows"></tbody></table>
<details><summary>SQL used to produce this example</summary><pre id="sql"></pre></details>
<script>
const data=__DATA__, query=__QUERY__;
const svg=document.getElementById('chart'), ns='http://www.w3.org/2000/svg';
const colors={'Vanilla class':'#2466bd','RHS':'#16824a','Other':'#b8560b'};
document.getElementById('sql').textContent=query;
function node(tag,attrs,text){const el=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,v);if(text!==undefined)el.textContent=text;svg.append(el);return el;}
function draw(){
 const family=document.getElementById('family').value, scope=document.getElementById('scope').value;
 const rows=data.filter(r=>(family==='all'||r.family===family)&&(scope==='all'||String(r.scope)===scope));
 svg.replaceChildren();document.getElementById('rows').replaceChildren();
 document.getElementById('count').textContent=`${rows.length} plotted groups representing ${rows.reduce((n,r)=>n+r.class_count,0)} classes.`;
 const xmax=Math.max(1,...data.map(r=>r.mass))*1.08,ymax=Math.max(1,...data.map(r=>r.armor))*1.1;
 const x=v=>70+v/xmax*780,y=v=>410-v/ymax*365;
 for(let i=0;i<=5;i++){
  const xv=xmax*i/5,yv=ymax*i/5;
  node('line',{x1:70,y1:y(yv),x2:850,y2:y(yv),stroke:'#e1e6ed'});
  node('text',{x:60,y:y(yv)+4,'text-anchor':'end','font-size':12},Number(yv.toFixed(1)));
  node('text',{x:x(xv),y:432,'text-anchor':'middle','font-size':12},Number(xv.toFixed(1)));
 }
 node('text',{x:460,y:463,'text-anchor':'middle'},'Mass (config units)');
 node('text',{x:20,y:230,transform:'rotate(-90 20 230)','text-anchor':'middle'},'Head armor (config value)');
 for(const r of rows){
  const label=`${r.family}: mass ${r.mass}, armor ${r.armor}, passThrough ${r.pass_through??'unknown'}; ${r.class_count} classes; example ${r.example_class}`;
  const dot=node('circle',{cx:x(r.mass),cy:y(r.armor),r:Math.min(15,3+Math.sqrt(r.class_count)),fill:colors[r.family],opacity:.65,tabindex:0,'aria-label':label});
  const title=document.createElementNS(ns,'title');title.textContent=label;dot.append(title);
  const tr=document.createElement('tr');
  for(const value of [r.family,r.mass,r.armor,r.pass_through??'unknown',r.class_count,r.example_class]){const td=document.createElement('td');td.textContent=value;tr.append(td);}
  document.getElementById('rows').append(tr);
 }
}
document.getElementById('family').addEventListener('change',draw);
document.getElementById('scope').addEventListener('change',draw);
draw();
</script></html>"""


def render(database, output):
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute(QUERY)]
    def embedded(value):
        return json.dumps(value, ensure_ascii=True).replace("<", "\\u003c")
    # Replace the query marker first so a class literally named __QUERY__ stays intact.
    page = HTML.replace("__QUERY__", embedded(QUERY)).replace("__DATA__", embedded(rows))
    output.write_text(page, encoding="utf-8")
    return {"chart": str(output), "plotted_groups": len(rows), "classes": sum(row["class_count"] for row in rows)}


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    print(json.dumps(render(root / "equipment.sqlite", root / "example-chart.html"), indent=2))
