import json,html
from datetime import datetime
from copy import deepcopy
import streamlit as st
import pandas as pd
from engine import calculate_environment,calculate_sensitivity,default_base,default_ds,DS_DEFAULTS,RULES_VERSION,RULES_SOURCE,GB_PER_TB,normalize_initial_data,normalize_daily_ingest
from ai_assistant import extract_requirements,review_sizing

st.set_page_config(page_title='Cloudera | Infrastructure Sizing Studio',page_icon='🧭',layout='wide',initial_sidebar_state='expanded')
st.markdown('''<style>
.block-container{padding-top:1.8rem;max-width:1450px}h1{font-size:2rem!important}
div[data-testid="stMetric"]{background:var(--secondary-background-color);color:var(--text-color);padding:17px;border-radius:13px;border:1px solid rgba(128,128,128,.35)}
div[data-testid="stMetricLabel"],div[data-testid="stMetricValue"],div[data-testid="stMetricDelta"]{color:var(--text-color)!important}
div.stButton>button[kind="primary"]{background:#174b78;border-radius:8px;border:none}
div[data-testid="stSidebar"]{background:var(--secondary-background-color)}.caption{color:var(--text-color);font-size:13px}.step{padding:13px;background:var(--secondary-background-color);border-left:4px solid #174b78;border-radius:8px}
</style>''',unsafe_allow_html=True)
if 'base' not in st.session_state:st.session_state.base=default_base()
if 'ds' not in st.session_state:st.session_state.ds=default_ds()
if 'services' not in st.session_state:st.session_state.services=[list(x) for x in DS_DEFAULTS]
if 'step' not in st.session_state:st.session_state.step=0
if 'environment_selection_valid' not in st.session_state:st.session_state.environment_selection_valid=True
ENVIRONMENTS=['Production','UAT','Development','PoC']
if 'client' not in st.session_state:st.session_state.client={'name':'Example client','project':'CDP private cloud sizing','environments':['Production'],'platform':'Base + Data Services','notes':''}
if 'environments' not in st.session_state.client:
 previous=st.session_state.client.pop('environment','Production')
 st.session_state.client['environments']=previous if isinstance(previous,list) else [previous]
st.session_state.client['environments']=list(dict.fromkeys(env for env in st.session_state.client['environments'] if env in ENVIRONMENTS))
if not st.session_state.client['environments']:st.session_state.client['environments']=['Production']
if 'profiles' not in st.session_state:
 primary=st.session_state.client['environments'][0]
 st.session_state.profiles={}
 for env in ENVIRONMENTS:
  st.session_state.profiles[env]={'base':deepcopy(default_base()),'ds':deepcopy(default_ds()),'services':[list(x) for x in DS_DEFAULTS],'units':{'initial':'TB','daily':'GB/day'}}
 st.session_state.profiles[primary]={'base':deepcopy(st.session_state.base),'ds':deepcopy(st.session_state.ds),'services':deepcopy(st.session_state.services),'units':{'initial':'TB','daily':'GB/day'}}
for env in ENVIRONMENTS:
 st.session_state.profiles.setdefault(env,{'base':deepcopy(default_base()),'ds':deepcopy(default_ds()),'services':[list(x) for x in DS_DEFAULTS],'units':{'initial':'TB','daily':'GB/day'}})
for key in ('edit_environment_data','edit_environment_hardware','edit_environment_ds'):
 if key in st.session_state and st.session_state[key] not in st.session_state.client['environments']:
  st.session_state[key]=st.session_state.client['environments'][0]
STEPS=['1 · Client','2 · Data & Workload','3 · Hardware & Rules','4 · Data Services','5 · Review','6 · Results & Exports']
with st.sidebar:
 st.title('🧭 Sizing Studio')
 st.caption('Cloudera Private Cloud • workbook-backed reference calculations')
 st.divider()
 for i,label in enumerate(STEPS):
  if st.button(('● ' if i==st.session_state.step else '○ ')+label,use_container_width=True,type='primary' if i==st.session_state.step else 'secondary',disabled=i>0 and not st.session_state.environment_selection_valid):st.session_state.step=i;st.rerun()
 st.divider()
 st.info('Planning estimator. Validate Cloudera version, licensing, service placement, rack topology and hardware compatibility before procurement.')
 st.caption(f'Reference rules: {RULES_VERSION}. Default fields are editable.')
 st.caption(f'Source: `{RULES_SOURCE}`')

st.title('Cloudera Infrastructure Sizing Studio')
st.caption('A guided client-to-sizing workflow with transparent, reproducible formulas and architectural checks.')
st.progress((st.session_state.step+1)/len(STEPS))

def field(obj,key,label,step=None,min_value=0.,help=None,scope='',max_value=None):
 val=obj[key]
 widget_key=f'f_{key}_{st.session_state.step}_{scope}'
 if isinstance(val,int):obj[key]=st.number_input(label,min_value=int(min_value),max_value=int(max_value) if max_value is not None else None,value=int(val),step=int(step or 1),help=help,key=widget_key)
 else:obj[key]=st.number_input(label,min_value=float(min_value),max_value=float(max_value) if max_value is not None else None,value=float(val),step=float(step or .1),help=help,key=widget_key)
def percent(obj,key,label,maximum=100,minimum=0,scope=''):
 obj[key]=st.slider(f'{label} (%)',minimum,maximum,int(obj[key]*100),help='Enter a percentage; the sizing engine converts it to a fraction.',key=f'p_{key}_{st.session_state.step}_{scope}')/100

def unit_input(label,value,unit,units,environment,name):
 conversion=1 if unit==units[0] else (GB_PER_TB if name=='daily_ingest' else 1/GB_PER_TB)
 displayed=value/conversion
 key=f'{name}_{environment}_{unit}_{displayed:.10g}'
 entered=st.number_input(f'{label} ({unit})',min_value=0.0,value=float(displayed),step=1.0,key=key)
 return entered

def nav():
 a,b,c=st.columns([1,5,1]);
 with a:
  if st.session_state.step>0 and st.button('← Back'):st.session_state.step-=1;st.rerun()
 with c:
  if st.session_state.step<len(STEPS)-1 and st.button('Next →',type='primary'):st.session_state.step+=1;st.rerun()

p=st.session_state.step;c=st.session_state.client
def current_signature():
 return json.dumps({'client':st.session_state.client,'profiles':st.session_state.profiles},sort_keys=True,default=str)

if p==0:
 st.subheader('Step 1 · Customer profile')
 st.markdown('Capture the customer, select one or more environments, and choose which infrastructure layers to size. Every environment is sized as a separate cluster.')
 selected_environments=st.multiselect('Environments to size',ENVIRONMENTS,default=c['environments'],key='selected_environments')
 if selected_environments:
  c['environments']=selected_environments
  st.session_state.environment_selection_valid=True
  st.caption('Environment node counts and results are kept separate; they are never added into a shared-cluster total.')
 else:
  st.session_state.environment_selection_valid=False
  st.error('Select at least one environment before continuing.')
 c1,c2=st.columns(2)
 with c1:
  c['name']=st.text_input('Customer name',c['name']);c['project']=st.text_input('Project / opportunity',c['project'])
 with c2:
  c['platform']=st.radio('Platform scope',['Base only','Base + Data Services'],index=0 if c['platform']=='Base only' else 1)
  c['notes']=st.text_area('Client requirements / architecture notes',c['notes'],height=138,placeholder='Workloads, SLA, latency, compliance, DR, security...')
 with st.expander('✨ AI agent — extract requirements from customer notes (optional)',expanded=False):
  raw=st.text_area('Paste an email, statement of work or client requirement summary',key='raw_requirements',height=135)
  st.caption('Requires OPENAI_API_KEY on the server. Values are previewed before adoption; nothing is guessed for missing numbers.')
  if st.button('Analyze with AI agent'):
   try:
    mapped,notes,missing=extract_requirements(raw)
    st.session_state.ai_candidate={'mapped':mapped,'notes':notes,'missing':missing}
   except Exception as e:st.error(str(e))
  if 'ai_candidate' in st.session_state:
   a=st.session_state.ai_candidate
   st.json(a)
   if st.button('Apply non-null extracted numeric inputs'):
    for env in c['environments']:
     target=st.session_state.profiles[env]['base']
     for k,v in a['mapped'].items():
      if v is not None and k in target and isinstance(v,(int,float)):
       if k in ('growth','cold_share') and not 0<=v<=1:continue
       if k=='years' and not 1<=v<=5:continue
       if v<0:continue
       target[k]=int(v) if k=='years' else float(v)
    c['notes']=(c['notes']+'\n'+a['notes']).strip()
    st.success('Applied extracted numeric inputs to every selected environment. Review each profile before sizing.')
 st.info('Without an API key, the complete deterministic sizing workflow remains functional.')
 if selected_environments:nav()
elif p==1:
 st.subheader('Step 2 · Data volumes and workload capacity')
 st.markdown('These map to **Base - Calculator** input rows 5–13 and 22–23.')
 env=st.selectbox('Environment profile to edit',c['environments'],key='edit_environment_data')
 profile=st.session_state.profiles[env];b=profile['base'];units=profile['units']
 st.caption(f'Editing the separate **{env}** cluster profile.')
 x,y=st.columns(2)
 with x:
  units['initial']=st.selectbox('Initial data unit',['TB','GB'],index=['TB','GB'].index(units['initial']),key=f'initial_unit_{env}')
  b['initial_tb']=normalize_initial_data(unit_input('Initial raw data volume',b['initial_tb'],units['initial'],['TB','GB'],env,'initial_data'),units['initial'])
  units['daily']=st.selectbox('Daily ingest unit',['GB/day','TB/day'],index=['GB/day','TB/day'].index(units['daily']),key=f'daily_unit_{env}')
  b['daily_gb']=normalize_daily_ingest(unit_input('Daily net-new ingest',b['daily_gb'],units['daily'],['GB/day','TB/day'],env,'daily_ingest'),units['daily'])
  percent(b,'growth','Annual ingest growth',maximum=300,scope=env)
  field(b,'years','Design horizon (years, 1–5)',1,1,scope=env,max_value=5)
 with y:
  field(b,'peak_vcores','Peak concurrent workload CPU demand (vCores)',50,help='Unit: vCores (virtual CPU cores). Enter the total CPU capacity required by the workload at its busiest concurrent period, not per job or per server. The engine uses this value to calculate CPU-driven worker count.',scope=env)
  field(b,'peak_ram','Peak concurrent workload memory demand (GB RAM)',256,help='Unit: GB of RAM. Enter the total memory required by the workload while it is running at peak concurrency, not per job or per server. The engine uses this value to calculate memory-driven worker count.',scope=env)
  percent(b,'cold_share','Cold data share (Ozone EC)',scope=env)
  field(b,'compression','Expected compression ratio (%)',.5,.1,scope=env)
 st.warning('Important: vCores and RAM are workload engineering inputs, not inferred automatically from TB. Collect Spark/Impala concurrency, executor sizes and SLAs before approving results.')
 nav()
elif p==2:
 st.subheader('Step 3 · Hardware and planning-rule settings')
 st.markdown('Editable workbook defaults. Keep these as **versioned rules/assumptions**, not immutable agent prompts.')
 env=st.selectbox('Environment profile to edit',c['environments'],key='edit_environment_hardware')
 profile=st.session_state.profiles[env];b=profile['base']
 d=profile['ds']
 st.caption(f'Editing the separate **{env}** cluster profile.')
 x,y=st.columns(2)
 with x:
  st.markdown('#### Base worker hardware')
  field(b,'disk_tb','Data disk capacity (TB)',2,scope=env)
  field(b,'disks_per_worker','Data disks per worker',1,scope=env)
  field(b,'worker_vcores','Worker vCores (incl. HT)',8,scope=env)
  field(b,'worker_ram','Worker RAM (GB)',32,scope=env)
  field(b,'min_workers','Minimum worker policy',1,1,scope=env)
 with y:
  st.markdown('#### Protection & utilization')
  field(b,'replication','Hot/HDFS replication (x)',1,1,scope=env)
  field(b,'ec_overhead','EC overhead multiplier',.1,1,scope=env)
  percent(b,'scratch','Temp/shuffle overhead',scope=env)
  percent(b,'utilization','Maximum disk utilization',minimum=1,scope=env)
  percent(b,'reservation','OS and daemon reservation',maximum=99,scope=env)
 b['ha']=st.toggle('Production HA for Base masters',value=b['ha'],key=f'base_ha_{env}')
 st.caption('Current workbook storage formula: compressed bytes × weighted protection × (1 + scratch) ÷ disk utilization.')
 nav()
elif p==3:
 st.subheader('Step 4 · Data Services capacity')
 if c['platform']=='Base only':
  st.info('Data Services is not calculated because the selected platform scope is Base only. No Data Services inputs are active and no DS nodes are included in the total.')
  if st.button('Change platform scope in Client Configuration'):
   st.session_state.step=0
   st.rerun()
 else:
  env=st.selectbox('Environment profile to edit',c['environments'],key='edit_environment_ds')
  profile=st.session_state.profiles[env];d=profile['ds']
  services=profile['services']
  st.caption(f'Editing the separate **{env}** cluster profile.')
  st.markdown('Each row models a workload component. **Quantity and per-unit assumptions are editable**. Defaults come from the supplied DS Calculator.')
  df=pd.DataFrame(services,columns=['Component','Quantity','vCores / unit','RAM GB / unit','Block GB / unit','Cache GB / unit','Basis'])
  updated=st.data_editor(df,hide_index=True,use_container_width=True,num_rows='fixed',disabled=['Component','Basis'],column_config={'Quantity':st.column_config.NumberColumn(min_value=0,step=1),'vCores / unit':st.column_config.NumberColumn(min_value=0),'RAM GB / unit':st.column_config.NumberColumn(min_value=0),'Block GB / unit':st.column_config.NumberColumn(min_value=0),'Cache GB / unit':st.column_config.NumberColumn(min_value=0)},key=f'ds_editor_{env}')
  profile['services']=updated.values.tolist()
  st.markdown('#### Kubernetes/ECS worker profile')
  x,y=st.columns(2)
  with x:
   field(d,'vcores','vCores per DS worker',8,scope=env)
   field(d,'ram','RAM per DS worker (GB)',32,scope=env)
   field(d,'block','Block storage per DS worker (GB)',250,scope=env)
   field(d,'cache','FAST cache per DS worker (GB)',100,scope=env)
  with y:
   field(d,'block_reserve','Control Plane reserved block per host (GB)',128,scope=env)
   field(d,'min_workers','Minimum DS workers',1,1,scope=env)
   percent(d,'os_overhead','Kubernetes / OS overhead',maximum=99,scope=env)
   percent(d,'headroom','Scaling headroom',scope=env)
  d['ha']=st.toggle('Production HA for DS masters',value=d['ha'],key=f'ds_ha_{env}')
 nav()
elif p==4:
 st.subheader('Step 5 · Review and confirm')
 st.markdown('Review each selected environment separately before running final sizing. Use Back or the sidebar to change inputs.')
 st.write(f"**Customer:** {c['name']}  ·  **Project:** {c['project']}")
 st.write(f"**Separate environments:** {', '.join(c['environments'])}  ·  **Platform scope:** {c['platform']}")
 st.write(f"**Rules baseline:** {RULES_VERSION} (`{RULES_SOURCE}`)")
 base_units={'growth':'%','years':'years','compression':'x','cold_share':'%','replication':'x','ec_overhead':'x','scratch':'%','utilization':'%','disk_tb':'TB/disk','disks_per_worker':'disks/worker','worker_vcores':'vCores/worker','worker_ram':'GB/worker','reservation':'%','peak_vcores':'vCores','peak_ram':'GB RAM','min_workers':'workers','ha':'enabled'}
 ds_units={'vcores':'vCores/worker','ram':'GB RAM/worker','block':'GB/worker','cache':'GB/worker','block_reserve':'GB/host','min_workers':'workers','os_overhead':'%','headroom':'%','ha':'enabled'}
 ready=True
 environment_tabs=st.tabs(c['environments'])
 for env,tab in zip(c['environments'],environment_tabs):
  with tab:
   profile=st.session_state.profiles[env];b=profile['base'];d=profile['ds'];services=profile['services'];units=profile['units']
   st.markdown('#### Base inputs and units')
   initial_value=b['initial_tb']*(GB_PER_TB if units['initial']=='GB' else 1)
   daily_value=b['daily_gb']/(GB_PER_TB if units['daily']=='TB/day' else 1)
   base_rows=[{'Input':'Initial raw data volume','Value':initial_value,'Unit':units['initial']},{'Input':'Daily net-new ingest','Value':daily_value,'Unit':units['daily']},{'Input':'Peak concurrent workload CPU demand','Value':b['peak_vcores'],'Unit':'vCores total at peak'},{'Input':'Peak concurrent workload memory demand','Value':b['peak_ram'],'Unit':'GB RAM total at peak'}]
   base_labels={'peak_vcores':'Peak concurrent workload CPU demand','peak_ram':'Peak concurrent workload memory demand'}
   base_rows.extend({'Input':base_labels.get(key,key.replace('_',' ').title()),'Value':value,'Unit':base_units[key]} for key,value in b.items() if key not in ('initial_tb','daily_gb'))
   st.dataframe(pd.DataFrame(base_rows),hide_index=True,use_container_width=True)
   base_baseline=default_base()
   changed_base={key:{'workbook default':base_baseline[key],'current value':value} for key,value in b.items() if value!=base_baseline[key]}
   if changed_base:st.warning('Base values changed from the workbook example defaults.');st.json(changed_base)
   else:st.info('Base values match the workbook example defaults.')
   if c['platform']!='Base only':
    st.markdown('#### Data Services inputs and units')
    st.dataframe(pd.DataFrame([{'Input':key.replace('_',' ').title(),'Value':value,'Unit':ds_units[key]} for key,value in d.items()]),hide_index=True,use_container_width=True)
    st.dataframe(pd.DataFrame(services,columns=['Component','Quantity','vCores / unit','RAM GB / unit','Block GB / unit','Cache GB / unit','Basis']),hide_index=True,use_container_width=True)
    ds_baseline=default_ds()
    changed_ds={key:{'workbook default':ds_baseline[key],'current value':value} for key,value in d.items() if value!=ds_baseline[key]}
    changed_services=[row[0] for row,default in zip(services,DS_DEFAULTS) if row!=list(default)]
    if changed_ds or changed_services:
     st.warning('Data Services values changed from the workbook example defaults.')
     st.json({'worker profile changes':changed_ds,'service rows changed':changed_services})
   try:
    review=calculate_environment(profile,include_ds=c['platform']!='Base only')
    review_base=review['base'];review_ds=review['data_services']
    result_text=f"Base: {review_base['workers']} workers / {review_base['masters']} masters ({review_base['driver']} driver)"
    if review_ds:result_text+=f"; Data Services: {review_ds['workers']} workers / {review_ds['masters']} masters ({review_ds['driver']} driver)"
    st.success(f'{env} validation passed. {result_text}.')
    for warning in review_base['warnings']+(review_ds['warnings'] if review_ds else []):st.warning(warning)
   except (KeyError,TypeError,ValueError) as e:
    st.error(f'{env}: correct invalid sizing inputs before continuing: {e}')
    ready=False
 back_col,confirm_col=st.columns([1,5])
 with back_col:
  if st.button('← Back',key='review_back'):st.session_state.step=3;st.rerun()
 with confirm_col:
  if st.button('Confirm inputs and calculate →',type='primary',disabled=not ready,key='confirm_current_inputs'):
   st.session_state.confirmed_signature=current_signature()
   st.session_state.step=5
   st.rerun()
else:
 if st.session_state.get('confirmed_signature')!=current_signature():
   st.warning('The current inputs have not been confirmed. Review them before calculating or exporting results.')
   if st.button('Review current inputs'):
    st.session_state.step=4
    st.rerun()
   st.stop()
 st.subheader('Step 6 · Final infrastructure sizing')
 environment_tabs=st.tabs(c['environments'])
 for env,environment_tab in zip(c['environments'],environment_tabs):
  with environment_tab:
   profile=st.session_state.profiles[env];b=profile['base'];d=profile['ds'];services=profile['services'];units=profile['units']
   try:
    environment_result=calculate_environment(profile,include_ds=c['platform']!='Base only')
    base=environment_result['base'];ds=environment_result['data_services']
   except (KeyError,TypeError,ValueError,OverflowError) as e:
    st.error(f'{env} sizing failed: {e}')
    continue
   st.success(f'{env} is sized as a separate cluster. Counts are not combined with other environments.')
   m1,m2,m3,m4=st.columns(4)
   m1.metric('Base workers',base['workers']);m2.metric('Base masters',base['masters']);m3.metric('DS workers',ds['workers'] if ds else 'Not calculated');m4.metric('Total nodes in this cluster',base['total_nodes']+(ds['total_nodes'] if ds else 0))
   if ds is None:st.caption('Data Services: Not calculated — Base-only scope selected.')
   st.caption('This total covers only this environment: Base workers and masters'+(' plus Data Services workers and masters.' if ds else '.'))
   t1,t2,t3,t5,t4=st.tabs(['Summary','Calculation breakdown','Architecture & checks','What-if scenarios','Exports & assumptions'])
   with t1:
    st.markdown(f"### {c['name']} — {c['project']} — {env}")
    st.write(f"**Platform:** {c['platform']}  ·  **Selected environments:** {', '.join(c['environments'])}")
    st.write(f"**Rules:** {RULES_VERSION} (`{RULES_SOURCE}`)")
    st.write(f"**Base sizing driver:** {base['driver']}. **Installed raw disk:** {base['installed_tb']:,.1f} TB. **Required raw disk:** {base['required_disk_tb']:,.1f} TB. **Remaining raw capacity:** {base['installed_tb']-base['required_disk_tb']:,.1f} TB.")
    st.caption(f"Disk figures are nominal raw TB, not usable filesystem capacity. GB/TB conversion uses the workbook's {GB_PER_TB} rule.")
    initial_display=b['initial_tb']*(GB_PER_TB if units['initial']=='GB' else 1)
    daily_display=b['daily_gb']/(GB_PER_TB if units['daily']=='TB/day' else 1)
    st.write(f"**Base inputs:** {initial_display:,.2f} {units['initial']} initial data; {daily_display:,.2f} {units['daily']} net-new ingest; {b['growth']:.0%} annual growth; {b['years']} year horizon; {b['compression']:g}x compression; {b['cold_share']:.0%} cold data.")
    baseline=default_base()
    changed_inputs={key:{'workbook default':baseline[key],'current value':value} for key,value in b.items() if value!=baseline[key]}
    if changed_inputs:
     st.warning('The following Base assumptions differ from the workbook example defaults:')
     st.json(changed_inputs)
    else:st.info('Base inputs match the workbook example defaults.')
    if ds:st.write(f"**DS sizing driver:** {ds['driver']}. **DS worker demand:** {ds['demand']['vcores']:,.0f} vCores, {ds['demand']['ram']:,.0f} GB RAM, {ds['demand']['block']:,.0f} GB block, {ds['demand']['cache']:,.0f} GB cache.")
    bom=[{'Cluster':'Base','Role':'Worker','Nodes':base['workers'],'vCores / node':b['worker_vcores'],'RAM GB / node':b['worker_ram'],'Disk TB / node':base['node_disk_tb']},{'Cluster':'Base','Role':'Master','Nodes':base['masters'],'vCores / node':'Size separately','RAM GB / node':'Size separately','Disk TB / node':'See hardware catalog'}]
    if ds:bom.extend([{'Cluster':'Data Services','Role':'Worker','Nodes':ds['workers'],'vCores / node':d['vcores'],'RAM GB / node':d['ram'],'Disk TB / node':d['block']/1000},{'Cluster':'Data Services','Role':'Master','Nodes':ds['masters'],'vCores / node':'Size separately','RAM GB / node':'Size separately','Disk TB / node':'See hardware catalog'}])
    st.markdown('#### Preliminary node inventory')
    bom_display=pd.DataFrame(bom)
    for column in ('vCores / node','RAM GB / node','Disk TB / node'):bom_display[column]=bom_display[column].astype(str)
    st.dataframe(bom_display,hide_index=True,use_container_width=True)
    st.caption('Dedicated Kafka, NiFi, Kudu, HBase, management, security, databases, DR, racks and networking are NOT included automatically; model these before final procurement.')
   with t2:
    st.markdown('#### Base demand by limiting factor')
    st.bar_chart(pd.DataFrame([{'Driver':key,'Nodes':value} for key,value in base['candidates'].items()]).set_index('Driver'))
    st.dataframe(pd.DataFrame(base['forecast']),hide_index=True,use_container_width=True)
    st.code(f"Year {b['years']} raw data = {base['design_raw_tb']:.4f} TB\nStored after compression = {base['stored_tb']:.4f} TB\nProtection factor = {base['protection']:.2f}x\nProtected data = {base['protected_tb']:.4f} TB\nRequired raw disk = {base['stored_tb']:.4f} × {base['protection']:.2f} × (1 + {b['scratch']}) / {b['utilization']} = {base['required_disk_tb']:.4f} TB\nWorkers by constraint: {base['candidates']}\nFinal workers = {base['workers']} ({base['driver']} driver)")
    if ds:
     st.markdown('#### Data Services demand by limiting factor')
     st.bar_chart(pd.DataFrame([{'Driver':key,'Nodes':value} for key,value in ds['candidates'].items()]).set_index('Driver'))
     st.dataframe(pd.DataFrame(ds['details']),hide_index=True,use_container_width=True)
   with t3:
    st.markdown('#### Logical architecture')
    st.code('Client sources → ingestion → CDP Base (HDFS/Ozone + YARN/Spark/SQL)'+(' → Data Services (Kubernetes / CDW / CDE / Cloudera AI)' if ds else '')+' → Consumers',language=None)
    warnings_list=base['warnings']+(ds['warnings'] if ds else [])
    if not warnings_list:st.success('No automatic hard-limit warnings for current input parameters.')
    for warning in warnings_list:st.warning(warning)
    st.markdown('#### Mandatory review before sign-off')
    for item in ['Confirm Cloudera product/version support matrix and actual architecture','Confirm workload concurrency and benchmark-derived CPU/RAM requirements','Model Kafka, NiFi, Kudu, HBase, Ranger, Atlas, management and external DB hosts separately','Confirm rack/availability zones, network, recovery/RPO/RTO and DR sizing','Confirm hot/cold storage layout, filesystem block size, metadata and small-file count','Validate CCU/subscription/licensing calculations with commercial team','Review vendor hardware profiles, usable versus nominal SSD/HDD capacity and failure headroom']:
     st.checkbox(item,key=f'review_{env}_{item}')
   with t5:
    st.markdown('#### Sensitivity analysis')
    st.write('Explore how plausible increases in Base raw-data volume and peak workload demand affect the estimate. These scenarios do not change your confirmed baseline inputs.')
    sensitivity_pct=st.slider('Increase for what-if scenarios (%)',5,100,20,5,key=f'sensitivity_pct_{env}',help='Applies independently to initial data plus daily ingest, and to peak vCores plus peak RAM. The combined scenario applies the increase to both.')
    st.caption(f'Unit: percent increase over the confirmed baseline. Data Services workload quantities and hardware assumptions stay fixed; Data Services results are shown for context only. Storage is nominal raw TB.')
    try:
     sensitivity_results=calculate_sensitivity(profile,sensitivity_pct,include_ds=c['platform']!='Base only')
     st.dataframe(pd.DataFrame(sensitivity_results),hide_index=True,use_container_width=True,column_config={'Required raw disk (TB)':st.column_config.NumberColumn(format='%.2f'),'Installed raw disk (TB)':st.column_config.NumberColumn(format='%.2f')})
     st.info('Read each row as an independent scenario: data-only changes initial data and daily ingest; compute-only changes total peak vCores and RAM; the combined case changes both. All other assumptions remain at baseline.')
    except (KeyError,TypeError,ValueError,OverflowError) as e:
     sensitivity_results=[]
     st.error(f'Unable to calculate sensitivity scenarios for {env}: {e}')
   with t4:
    input_units={'initial_data':units['initial'],'daily_ingest':units['daily'],'growth':'%','years':'years','compression':'x','cold_share':'%','replication':'x','ec_overhead':'x','scratch':'%','utilization':'%','worker_disk':'TB/disk','disks_per_worker':'disks/worker','worker_vcores':'vCores/worker','worker_ram':'GB/worker','os_reservation':'%','peak_vcores':'total vCores at peak concurrency','peak_ram':'total GB RAM at peak concurrency','ds_worker_vcores':'vCores/worker','ds_worker_ram':'GB/worker','ds_worker_block':'GB/worker','ds_worker_cache':'GB/worker','ds_control_plane_reserve':'GB/host','ds_os_overhead':'%','ds_headroom':'%','ds_service_quantity':'instances or concurrent jobs/sessions','ds_service_vcores':'vCores/unit','ds_service_ram':'GB/unit','ds_service_block':'GB/unit','ds_service_cache':'GB/unit'}
    input_display={'initial_data':initial_display,'daily_ingest':daily_display,'units':input_units}
    payload={'generated_at':datetime.now().isoformat(timespec='seconds'),'rules':{'version':RULES_VERSION,'source':RULES_SOURCE,'GB_per_TB':GB_PER_TB,'display_rounding':'Forecast table values rounded to 2 decimal places; sizing uses full precision','input_units':input_units},'client':{'name':c['name'],'project':c['project'],'selected_environments':c['environments'],'sized_environment':env,'platform':c['platform'],'notes':c['notes']},'base_inputs':b,'base_inputs_as_entered':input_display,'base_output':base,'ds_inputs':d if ds else None,'ds_services':services if ds else None,'ds_output':ds,'sensitivity_analysis':sensitivity_results,'bom':bom,'warnings':warnings_list,'disclaimer':'Reference estimate based on supplied workbook; not a vendor-certified production design.'}
    environment_file=env.lower().replace(' ','_')
    st.download_button('⬇ Download full calculation (JSON)',json.dumps(payload,indent=2).encode(),f'cloudera_sizing_{environment_file}.json','application/json')
    inventory=pd.DataFrame(bom)
    inventory['Platform scope']=c['platform'];inventory['Environment']=env;inventory['Selected environments']=', '.join(c['environments']);inventory['Rules version']=RULES_VERSION
    inventory['Base sizing driver']=base['driver'];inventory['Data Services sizing driver']=ds['driver'] if ds else 'Not calculated — Base-only scope selected'
    inventory['Sizing inputs (JSON)']=json.dumps({'base':b,'entered_values':input_display,'data_services':d if ds else None,'data_services_workloads':services if ds else None},sort_keys=True)
    inventory['Base required raw disk (TB)']=base['required_disk_tb'];inventory['Base installed raw disk (TB)']=base['installed_tb']
    inventory['Base workers']=base['workers'];inventory['Base masters']=base['masters']
    inventory['Data Services workers']=ds['workers'] if ds else 'Not calculated';inventory['Data Services masters']=ds['masters'] if ds else 'Not calculated'
    inventory['Sizing input units (JSON)']=json.dumps(input_units,sort_keys=True);inventory['Warnings']='; '.join(warnings_list)
    inventory['Assumptions']='Separate cluster for each selected environment; hardware completeness and product compatibility require review.'
    st.download_button('⬇ Download node inventory (CSV)',inventory.to_csv(index=False).encode(),f'cloudera_inventory_{environment_file}.csv','text/csv')
    bom_rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(value))}</td>' for value in row.values())+'</tr>' for row in bom)
    bom_headers=''.join('<th>'+html.escape(str(key))+'</th>' for key in bom[0])
    warning_rows=''.join('<li>'+html.escape(warning)+'</li>' for warning in warnings_list)
    forecast_rows=''.join(f"<tr><td>{row['Year']}</td><td>{row['Ingest added (TB)']:.2f}</td><td>{row['Cumulative raw (TB)']:.2f}</td></tr>" for row in base['forecast'])
    candidate_rows=''.join(f"<li>{html.escape(str(key))}: {value} workers</li>" for key,value in base['candidates'].items())
    if ds:
     ds_candidate_rows=''.join(f"<li>{html.escape(str(key))}: {value} workers</li>" for key,value in ds['candidates'].items())
     ds_detail_rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(value))}</td>' for value in row.values())+'</tr>' for row in ds['details'])
     ds_detail_headers=''.join('<th>'+html.escape(str(key))+'</th>' for key in ds['details'][0]) if ds['details'] else ''
     ds_report=f"<h2>Data Services calculation</h2><p>Driver: {html.escape(ds['driver'])}; {ds['workers']} workers and {ds['masters']} masters. Demand: {html.escape(json.dumps(ds['demand']))}.</p><ul>{ds_candidate_rows}</ul><table><tr>{ds_detail_headers}</tr>{ds_detail_rows}</table><pre>{html.escape(json.dumps({'worker_profile':d,'service_workloads':services},indent=2))}</pre>"
    else:ds_report='<p>Data Services: Not calculated — Base-only scope selected.</p>'
    report=f'''<!doctype html><html><head><meta charset="utf-8"><title>Cloudera sizing report — {html.escape(env)}</title><style>body{{font-family:Arial,sans-serif;max-width:1050px;margin:40px auto;color:#18314c}}h1{{color:#134b79}}table{{border-collapse:collapse;width:100%}}td,th{{padding:12px;border:1px solid #ccd8e4;text-align:left}}th{{background:#ebf2fa}}.hint{{color:#66788b}}@media print{{body{{margin:12mm}}}}</style></head><body><h1>Cloudera Infrastructure Sizing — {html.escape(env)}</h1><p><b>Client:</b> {html.escape(c['name'])} · <b>Project:</b> {html.escape(c['project'])} · <b>Selected environments:</b> {html.escape(', '.join(c['environments']))} · <b>Scope:</b> {html.escape(c['platform'])}</p><p><b>Rules:</b> {html.escape(RULES_VERSION)} · {html.escape(RULES_SOURCE)} · {GB_PER_TB} GB per TB</p><h2>Base summary</h2><p><b>{base['workers']} workers</b> / <b>{base['masters']} masters</b>; driver: {html.escape(base['driver'])}. Required raw disk: {base['required_disk_tb']:.2f} TB; installed raw disk: {base['installed_tb']:.2f} TB; remaining: {base['installed_tb']-base['required_disk_tb']:.2f} TB.</p><p>Inputs: {initial_display:.2f} {html.escape(units['initial'])} initial raw data; {daily_display:.2f} {html.escape(units['daily'])} daily ingest; {b['growth']:.0%} annual growth; {b['years']} year horizon; {b['compression']:g}x compression; {b['cold_share']:.0%} cold data; {b['peak_vcores']:,.0f} total vCores and {b['peak_ram']:,.0f} GB RAM at peak concurrency (used for CPU- and memory-driven worker counts).</p><p>Stored: {base['stored_tb']:.2f} TB; protection: {base['protection']:.2f}x; protected: {base['protected_tb']:.2f} TB. Workers by constraint:</p><ul>{candidate_rows}</ul><h2>Year-by-year Base forecast (TB)</h2><table><tr><th>Year</th><th>Ingest added</th><th>Cumulative raw</th></tr>{forecast_rows}</table><h2>Node inventory for {html.escape(env)}</h2><table><tr>{bom_headers}</tr>{bom_rows}</table>{ds_report}<h2>Warnings and limitations</h2><ul>{warning_rows}<li>Dedicated components, rack topology, DR and management hosts require independent sizing.</li></ul><h2>Base inputs (canonical TB and GB/day)</h2><pre>{html.escape(json.dumps(b,indent=2))}</pre><p class="hint">Planning estimate only. Requires version-specific vendor review and workload validation.</p></body></html>'''
    if sensitivity_results:
     sensitivity_headers=''.join('<th>'+html.escape(str(key))+'</th>' for key in sensitivity_results[0])
     sensitivity_rows=''.join('<tr>'+''.join('<td>'+html.escape(format(value,'.2f') if isinstance(value,float) else str(value))+'</td>' for value in row.values())+'</tr>' for row in sensitivity_results)
     sensitivity_report=f'<h2>What-if sensitivity analysis</h2><p>Positive-only sensitivity cases against the confirmed baseline. Data changes scale initial data and daily ingest; compute changes scale peak vCores and RAM. Data Services workload quantities and hardware remain fixed.</p><table><tr>{sensitivity_headers}</tr>{sensitivity_rows}</table>'
     report=report.replace('</body>',sensitivity_report+'</body>')
    st.download_button('⬇ Download printable report (HTML)',report.encode(),f'cloudera_report_{environment_file}.html','text/html')
    st.markdown('#### AI architectural review (optional)')
    st.caption('This agent explains risks and asks for missing inputs; it cannot alter calculated node counts.')
    if st.button('Generate independent AI review',key=f'ai_review_button_{env}'):
     try:st.session_state[f'ai_review_{env}']=review_sizing(payload)
     except Exception as e:st.error(str(e))
    if st.session_state.get(f'ai_review_{env}'):st.markdown(st.session_state[f'ai_review_{env}'])
    st.markdown('**Workbook reference:** bundled under `reference/`. Exact sizing formulas are in `engine.py`.')
 nav()
