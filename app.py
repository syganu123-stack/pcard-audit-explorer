import os,sqlite3,re,json,urllib.request
from flask import Flask,request,render_template_string,jsonify
app=Flask(__name__)
DB=os.getenv('PCARD_DB',os.path.join(os.path.dirname(__file__),'pcards.db'))
def conn():
 c=sqlite3.connect('file:'+os.path.abspath(DB)+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;return c
HTML='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OSU P-Card Audit</title><style>body{font:16px system-ui;background:#f4f6fa;color:#192438;margin:0}header{background:#183153;color:white;padding:24px}main{max-width:1050px;margin:25px auto;padding:15px}button,input,select{padding:10px;margin:5px;border:1px solid #bcc9d6;border-radius:6px}button{cursor:pointer;background:#175ca5;color:white}section{background:white;padding:22px;border-radius:12px;margin:15px 0}nav button{background:#31516d}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}#results{overflow:auto}small{color:#556} .hide{display:none}</style></head><body><header><h1>OSU P-Card Audit Explorer</h1><p>Search and investigate state purchasing-card records. Matches are risk indicators, not findings of fraud.</p></header><main><nav><button onclick="tab('ask')">Ask the database</button><button onclick="tab('dash')">Prohibited purchases dashboard</button></nav><section id="ask"><h2>Natural-language questions</h2><p>Ask about 2014 OSU P-card transactions, e.g. “Which vendors received the most spending?” or “How many transactions exceeded $5,000?” The server generates a read-only SQL query. A Gemini API key is required for free-form questions; without it, preset examples work.</p><input id="question" style="width:75%" placeholder="Ask a question about P-card data"><button onclick="ask()">Ask</button><p id="answer"></p><div id="askresults"></div></section><section id="dash" class="hide"><h2>Prohibited-purchase screening</h2><p><b>Instructions:</b> Choose a year, select Description search or Vendor search, enter a keyword (e.g. alcohol, gift, gasoline, post office), and click Search. Results include the cardholder, merchant, amount, date and merchant category. A match needs receipt and approval review; it is not a confirmed violation.</p><label>Year <select id="year"><option>2014</option><option>2013</option><option>2012</option><option>2015</option></select></label><p><label><input type="radio" name="field" value="Description" checked>Description search</label><label><input type="radio" name="field" value="Vendor">Vendor search</label></p><input id="keyword" placeholder="Enter a keyword"><button onclick="search()">Search</button><p id="status"></p><div id="results"></div></section></main><script>
function tab(t){document.getElementById('ask').classList.toggle('hide',t!=='ask');document.getElementById('dash').classList.toggle('hide',t!=='dash')}
function table(data,target){if(!data.rows?.length){document.getElementById(target).textContent='No matching records';return}let cols=Object.keys(data.rows[0]);let h='<table><thead><tr>'+cols.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr></thead><tbody>'+data.rows.map(r=>'<tr>'+cols.map(k=>'<td>'+esc(r[k])+'</td>').join('')+'</tr>').join('')+'</tbody></table>';document.getElementById(target).innerHTML=h}
function esc(v){return String(v??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]))}
async function search(){let field=document.querySelector('input[name=field]:checked').value;let r=await fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({field,year:document.getElementById('year').value,keyword:document.getElementById('keyword').value})});let d=await r.json();document.getElementById('status').textContent=d.error||('Showing '+d.rows.length+' rows (maximum 300)');table(d,'results')}
async function ask(){document.getElementById('answer').textContent='Running...';let r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:document.getElementById('question').value})});let d=await r.json();document.getElementById('answer').textContent=d.error||('SQL: '+d.sql+' | '+d.rows.length+' returned rows (max 100)');table(d,'askresults')}
</script></body></html>'''
@app.get('/')
def index():return render_template_string(HTML)
@app.post('/api/search')
def search():
 x=request.get_json(force=True);year=str(x.get('year',''));field=x.get('field');keyword=str(x.get('keyword','')).strip()
 if not year.isdigit() or field not in ('Description','Vendor') or not keyword or len(keyword)>80:return jsonify(error='Select a year, search field and keyword.',rows=[]),400
 sql=f'SELECT Year,Amount,FullName,Description,Vendor,TransactionDate,PostedDate,MCC FROM pcards WHERE AgencyName=? AND Year=? AND {field} LIKE ? COLLATE NOCASE ORDER BY Amount DESC LIMIT 300'
 with conn() as c:rows=[dict(r) for r in c.execute(sql,('OKLAHOMA STATE UNIVERSITY',int(year),'%'+keyword+'%'))]
 return jsonify(rows=rows)
def safe_sql(sql):
 s=sql.strip().rstrip(';').strip()
 if not re.match(r'(?is)^select\b',s) or ';' in s or re.search(r'(?i)\b(insert|update|delete|drop|alter|attach|detach|pragma|create|replace|vacuum|load_extension)\b',s):raise ValueError('Only a single read-only SELECT is allowed.')
 if not re.search(r'(?i)\bpcards\b',s):raise ValueError('Query must reference pcards.')
 if not re.search(r'(?i)\bAgencyName\b',s) or not re.search(r'(?i)\bYear\b',s):raise ValueError('Query must restrict agency and year.')
 return 'SELECT * FROM ('+s+') LIMIT 100'
@app.post('/api/ask')
def ask():
 q=str((request.get_json(force=True) or {}).get('question',''))[:600]
 if not q.strip():return jsonify(error='Enter a question.',rows=[]),400
 low=q.lower();sql=None
 if 'how many' in low and ('5000' in low or '5,000' in low):sql="SELECT COUNT(*) AS NumberOfTransactions FROM pcards WHERE AgencyName='OKLAHOMA STATE UNIVERSITY' AND Year=2014 AND Amount>5000"
 elif 'vendor' in low and ('most' in low or 'top' in low):sql="SELECT Vendor,ROUND(SUM(Amount),2) AS TotalSpend FROM pcards WHERE AgencyName='OKLAHOMA STATE UNIVERSITY' AND Year=2014 GROUP BY Vendor ORDER BY TotalSpend DESC LIMIT 10"
 else:
  key=os.getenv('GEMINI_API_KEY','')
  if not key:return jsonify(error='Free-form questions require GEMINI_API_KEY on the server. Try: Which vendors received the most spending?'),503
  model=os.getenv('GEMINI_MODEL','gemini-2.5-flash')
  prompt="Generate one SQLite SELECT statement ONLY (no markdown) for this question. Table pcards columns: Year INTEGER, Month INTEGER, FullName TEXT, ID INTEGER, AgencyNumber INTEGER, AgencyName TEXT, CardholderLastName TEXT, CardholderFirstInitial TEXT, Description TEXT, Amount REAL, Vendor TEXT, TransactionDate TEXT (M/D/YYYY 0:00:00), PostedDate TEXT, MCC TEXT. ALWAYS filter AgencyName='OKLAHOMA STATE UNIVERSITY' AND Year=2014. Never use unsafe SQL or other tables. Question: "+q
  req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',data=json.dumps({'contents':[{'parts':[{'text':prompt}]}]}).encode(),headers={'Content-Type':'application/json','x-goog-api-key':key})
  try:
   with urllib.request.urlopen(req,timeout=20) as response:data=json.load(response)
   sql=data['candidates'][0]['content']['parts'][0]['text'].strip().replace('```sql','').replace('```','').strip()
  except Exception:return jsonify(error='The AI service is unavailable. Check the server API key, model and quota.',rows=[]),502
 try:
  with conn() as c:rows=[dict(r) for r in c.execute(safe_sql(sql))]
  return jsonify(sql=sql,rows=rows)
 except Exception as e:return jsonify(error='The generated query could not be executed: '+str(e),rows=[]),400
if __name__=='__main__':app.run(host='127.0.0.1',port=int(os.getenv('PORT','5000')),debug=False)
