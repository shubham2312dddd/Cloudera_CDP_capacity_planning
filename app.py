import json,html
from datetime import datetime
from copy import deepcopy
import streamlit as st
import pandas as pd
from engine import calculate_environment,calculate_sensitivity,default_base,default_ds,default_kafka,default_kudu,default_licensing,DS_DEFAULTS,SERVICE_POOL_DEFAULTS,RULES_VERSION,RULES_SOURCE,GB_PER_TB,normalize_initial_data,normalize_daily_ingest
from ai_assistant import extract_requirements,review_sizing

st.set_page_config(page_title='Cloudera | Infrastructure Sizing Studio',page_icon='🧭',layout='wide',initial_sidebar_state='expanded')
st.markdown('''<style>
.block-container{padding-top:1.8rem;max-width:1450px}h1{font-size:2rem!important}
div[data-testid="stMetric"]{background:var(--secondary-background-color);color:var(--text-color);padding:17px;border-radius:13px;border:1px solid rgba(128,128,128,.35)}
div[data-testid="stMetricLabel"],div[data-testid="stMetricValue"],div[data-testid="stMetricDelta"]{color:var(--text-color)!important}
div.stButton>button[kind="primary"]{background:#174b78;border-radius:8px;border:none}
div[data-testid="stSidebar"]{background:var(--secondary-background-color)}.caption{color:var(--text-color);font-size:13px}.step{padding:13px;background:var(--secondary-background-color);border-left:4px solid #174b78;border-radius:8px}
[data-testid="stMain"]:has(.first-four-page-scope) :is([data-testid="stWidgetLabel"],[data-testid="stMarkdownContainer"]) [data-testid="stTooltipIcon"] > [data-testid="stTooltipHoverTarget"] > button{position:relative;color:inherit!important}
[data-testid="stMain"]:has(.first-four-page-scope) :is([data-testid="stWidgetLabel"],[data-testid="stMarkdownContainer"]) [data-testid="stTooltipIcon"] > [data-testid="stTooltipHoverTarget"] > button svg{visibility:hidden}
[data-testid="stMain"]:has(.first-four-page-scope) :is([data-testid="stWidgetLabel"],[data-testid="stMarkdownContainer"]) [data-testid="stTooltipIcon"] > [data-testid="stTooltipHoverTarget"] > button::after{content:"i";position:absolute;inset:0;display:flex;align-items:center;justify-content:center;border:1px solid currentColor;border-radius:50%;font:600 10px/1 Arial,sans-serif;color:currentColor;opacity:.75;pointer-events:none}
[data-testid="stMain"]:has(.first-four-page-scope) [data-testid="stWidgetLabel"]>div{flex:0 0 auto!important;width:auto!important}
[data-testid="stMain"]:has(.first-four-page-scope) [data-testid="stWidgetLabel"] [data-testid="stTooltipIcon"]{margin-left:5px}
[data-testid="stMain"]:has(.first-four-page-scope) :is([data-testid="stWidgetLabel"],[data-testid="stMarkdownContainer"]) [data-testid="stTooltipIcon"] > [data-testid="stTooltipHoverTarget"] > button:hover::after,[data-testid="stMain"]:has(.first-four-page-scope) :is([data-testid="stWidgetLabel"],[data-testid="stMarkdownContainer"]) [data-testid="stTooltipIcon"] > [data-testid="stTooltipHoverTarget"] > button:focus-visible::after{color:#4da3ff;border-color:#4da3ff;opacity:1}
div[data-testid="stMarkdown"]:has(.first-four-page-scope){display:none!important}
[data-testid="stMain"] .ui-info{position:relative;display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;margin-left:5px;border:1px solid currentColor;border-radius:50%;font:600 10px/1 Arial,sans-serif;vertical-align:middle;cursor:help}
[data-testid="stMain"] .ui-info:hover,[data-testid="stMain"] .ui-info:focus{color:#4da3ff;border-color:#4da3ff;outline:none}
</style>''',unsafe_allow_html=True)
def default_profile():
 return {'base':default_base(),'ds':default_ds(),'services':[list(x) for x in DS_DEFAULTS],'units':{'initial':'TB','daily':'GB/day'},'data_classes':[],'kafka':default_kafka(),'kudu':default_kudu(),'licensing':default_licensing(),'service_pools':[list(row) for row in SERVICE_POOL_DEFAULTS],'capacity_percent':100,'ec_scheme':'RS-6-3','dr_mode':'Not applicable'}

PROJECT_SCHEMA_VERSION=1
def validate_project(payload):
 if not isinstance(payload,dict) or payload.get('schema_version')!=PROJECT_SCHEMA_VERSION:
  raise ValueError('Unsupported or missing project schema version.')
 client=payload.get('client')
 profiles=payload.get('profiles')
 if not isinstance(client,dict) or not isinstance(profiles,dict):
  raise ValueError('Project file must contain client details and environment profiles.')
 environments=client.get('environments')
 if not isinstance(environments,list) or not environments or any(env not in ENVIRONMENTS for env in environments):
  raise ValueError('Project must select at least one supported environment.')
 if client.get('platform') not in ('Base only','Base + Data Services'):
  raise ValueError('Project has an unsupported platform scope.')
 if any(not isinstance(client.get(key,''),str) for key in ('name','project','notes')):
  raise ValueError('Customer name, project name, and notes must be text.')
 restored={}
 for env in ENVIRONMENTS:
  profile=deepcopy(profiles.get(env,default_profile()))
  if not isinstance(profile,dict) or not isinstance(profile.get('base'),dict) or not isinstance(profile.get('ds'),dict):
   raise ValueError(f'{env} profile is incomplete.')
  profile['base']={**default_base(),**profile['base']}
  profile['ds']={**default_ds(),**profile['ds']}
  profile.setdefault('services',[list(row) for row in DS_DEFAULTS])
  profile.setdefault('units',{'initial':'TB','daily':'GB/day'})
  profile.setdefault('data_classes',[])
  profile.setdefault('kafka',default_kafka())
  profile.setdefault('kudu',default_kudu())
  profile.setdefault('licensing',default_licensing())
  profile.setdefault('service_pools',[list(row) for row in SERVICE_POOL_DEFAULTS])
  if not isinstance(profile['kafka'],dict) or not isinstance(profile['kudu'],dict) or not isinstance(profile['licensing'],dict):
   raise ValueError(f'{env} planning settings are malformed.')
  profile['kafka']={**default_kafka(),**profile['kafka']}
  profile['kudu']={**default_kudu(),**profile['kudu']}
  profile['licensing']={**default_licensing(),**profile['licensing']}
  profile.setdefault('capacity_percent',100)
  profile.setdefault('ec_scheme','RS-6-3')
  profile.setdefault('dr_mode','Not applicable')
  if profile['ec_scheme'] not in ('RS-3-2','RS-6-3','RS-10-4'):
   raise ValueError(f'{env} profile has an unsupported erasure-coding scheme.')
  if profile['dr_mode'] not in ('Not applicable','Active','Warm standby','Backup only'):
   raise ValueError(f'{env} profile has an unsupported DR mode.')
  if not isinstance(profile['data_classes'],list) or any(not isinstance(row,dict) for row in profile['data_classes']) or not isinstance(profile['services'],list):
   raise ValueError(f'{env} workload rows are malformed.')
  if not isinstance(profile['units'],dict) or not isinstance(profile['service_pools'],list):
   raise ValueError(f'{env} planning settings are malformed.')
  if any(not isinstance(row,(list,tuple)) or len(row)!=len(DS_DEFAULTS[0]) for row in profile['services']):
   raise ValueError(f'{env} Data Services workload rows have an unsupported format.')
  if any(not isinstance(row,(list,tuple)) or len(row)!=len(SERVICE_POOL_DEFAULTS[0]) for row in profile['service_pools']):
   raise ValueError(f'{env} dedicated service inventory rows have an unsupported format.')
  profile['service_pools']=[list(row) for row in profile['service_pools']]
  if profile['units'].get('initial') not in ('TB','GB') or profile['units'].get('daily') not in ('GB/day','TB/day'):
   raise ValueError(f'{env} profile has unsupported data units.')
  restored[env]=profile
 normalized_client={key:client.get(key,'') for key in ('name','project','notes')}
 normalized_client.update({'environments':environments,'platform':client['platform']})
 return normalized_client,restored

if 'base' not in st.session_state:st.session_state.base=default_base()
if 'ds' not in st.session_state:st.session_state.ds=default_ds()
if 'services' not in st.session_state:st.session_state.services=[list(x) for x in DS_DEFAULTS]
if 'step' not in st.session_state:st.session_state.step=0
if 'environment_selection_valid' not in st.session_state:st.session_state.environment_selection_valid=True
ENVIRONMENTS=['Production','Disaster Recovery','UAT','Development','PoC']
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
  st.session_state.profiles[env]=default_profile()
 st.session_state.profiles[primary]={'base':deepcopy(st.session_state.base),'ds':deepcopy(st.session_state.ds),'services':deepcopy(st.session_state.services),'units':{'initial':'TB','daily':'GB/day'},'data_classes':[],'kafka':default_kafka(),'licensing':default_licensing()}
for env in ENVIRONMENTS:
 st.session_state.profiles.setdefault(env,default_profile())
 st.session_state.profiles[env]['base']={**default_base(),**st.session_state.profiles[env]['base']}
 st.session_state.profiles[env]['ds']={**default_ds(),**st.session_state.profiles[env]['ds']}
 st.session_state.profiles[env].setdefault('services',[list(row) for row in DS_DEFAULTS])
 st.session_state.profiles[env].setdefault('units',{'initial':'TB','daily':'GB/day'})
 st.session_state.profiles[env].setdefault('data_classes',[])
 st.session_state.profiles[env].setdefault('kafka',default_kafka())
 st.session_state.profiles[env].setdefault('kudu',default_kudu())
 st.session_state.profiles[env].setdefault('licensing',default_licensing())
 st.session_state.profiles[env].setdefault('service_pools',[list(row) for row in SERVICE_POOL_DEFAULTS])
 st.session_state.profiles[env]['kafka']={**default_kafka(),**st.session_state.profiles[env]['kafka']}
 st.session_state.profiles[env]['kudu']={**default_kudu(),**st.session_state.profiles[env]['kudu']}
 st.session_state.profiles[env]['licensing']={**default_licensing(),**st.session_state.profiles[env]['licensing']}
 st.session_state.profiles[env].setdefault('capacity_percent',100)
 st.session_state.profiles[env].setdefault('ec_scheme','RS-6-3')
 st.session_state.profiles[env].setdefault('dr_mode','Not applicable')
if '_pending_project_load' in st.session_state:
 st.session_state.client,st.session_state.profiles=st.session_state.pop('_pending_project_load')
 st.session_state.step=0
 st.session_state.environment_selection_valid=True
 st.session_state.pop('confirmed_signature',None)
 st.session_state.pop('ai_candidate',None)
 for key in list(st.session_state):
  if key.startswith(('f_','p_','initial_data_','daily_ingest_','initial_unit_','daily_unit_','selected_environments','edit_environment_','data_classes_','ds_editor_','service_pools_','kafka_','kudu_','licensing_','included_ccu_','included_tb_','excluded_tb_','capacity_scale_','base_ha_','ds_ha_','review_','sensitivity_pct_','ai_review_button_')) or key in ('upload_project','open_project','download_project','raw_requirements','ai_target_environment','dr_mode'):
   st.session_state.pop(key,None)
for key in ('edit_environment_data','edit_environment_hardware','edit_environment_ds','ai_target_environment'):
 if key in st.session_state and st.session_state[key] not in st.session_state.client['environments']:
  st.session_state[key]=st.session_state.client['environments'][0]
STEPS=['1 · Client','2 · Data & Workload','3 · Hardware & Rules','4 · Data Services','5 · Review','6 · Results & Exports']
FIELD_HELP={
 'initial_data':'Starting raw data size before future growth. The selected unit is used for this environment.',
 'daily_ingest':'Amount of new raw data added each day. The selected unit is used for this environment.',
 'growth':'Unit: %. Set the expected yearly increase in new data ingestion. A higher value increases the forecast data and storage requirement. Valid range: 0 to 300%.',
 'years':'Number of years included in the data forecast. Choose a whole number from 1 to 5.',
 'peak_vcores':'Unit: vCores (virtual CPU cores). Enter the total CPU capacity required by the workload at its busiest concurrent period, not per job or per server. The engine uses this value to calculate CPU-driven worker count.',
 'peak_ram':'Unit: GB of RAM. Enter the total memory required by the workload while it is running at peak concurrency, not per job or per server. The engine uses this value to calculate memory-driven worker count.',
 'cold_share':'Unit: %. Set the share of data treated as cold data for the Ozone erasure-coding protection calculation. This changes the weighted protection estimate between replication and erasure-coding overhead. Valid range: 0 to 100%.',
 'compression':'Expected compression ratio as a multiplier (for example, 3 means 3x). This is not a percentage. Minimum: 0.1x.',
 'disk_tb':'Nominal capacity of one worker data disk, in TB.',
 'disks_per_worker':'Number of data disks installed in each Base worker.',
 'worker_vcores':'CPU capacity of one Base worker, including hyper-threading as represented by the hardware profile.',
 'worker_ram':'Memory capacity of one Base worker, in GB.',
 'replication':'Hot/HDFS storage replication multiplier used to estimate protected storage.',
 'ec_overhead':'Storage overhead multiplier used for erasure-coded cold data.',
 'scratch':'Unit: %. Add this temporary and shuffle storage allowance to required disk. A higher value increases the disk estimate. Valid range: 0 to 100%.',
 'utilization':'Unit: %. Set the maximum share of each worker disk counted as available for planned data. Lower values leave more free space and can require more workers. Valid range: 1 to 100%.',
 'reservation':'Unit: %. Reserve this share of each Base worker’s CPU and RAM for the operating system and daemons. A higher value reduces resources available to the workload and can increase worker count. Valid range: 0 to 99%.',
 'vcores':'CPU capacity of one Data Services worker, in vCores.',
 'ram':'Memory capacity of one Data Services worker, in GB.',
 'block':'Block storage capacity of one Data Services worker, in GB.',
 'cache':'FAST cache capacity of one Data Services worker, in GB.',
 'block_reserve':'Block storage reserved for the Data Services control plane on each host, in GB.',
 'min_workers_base':'Minimum number of Base workers to plan, even if calculated demand is lower.',
 'min_workers_ds':'Minimum number of Data Services workers to plan, even if calculated demand is lower.',
 'os_overhead':'Unit: %. Reserve this share of Data Services worker CPU and RAM for Kubernetes and the operating system. A higher value reduces resources available to workload demand and can increase worker count. Valid range: 0 to 99%.',
 'headroom':'Unit: %. Add this scaling allowance to Data Services CPU, RAM, and block-storage demand when calculating worker count. A higher value can increase the required workers. Valid range: 0 to 100%.',
 'connected_environments':'Number of Base environments connected to this Data Services cluster. Entered control-plane overhead per environment is multiplied by this count.',
 'sensitivity':'Percent increase applied to Base data and/or peak workload in the what-if cases. It does not change confirmed inputs; Data Services workload and hardware stay fixed.',
}
BUTTON_HELP={
 'Analyze with AI agent':'Read the pasted client requirements and show suggested numeric values, notes, and missing information. This creates a preview and does not change sizing inputs.',
 'Apply non-null extracted numeric inputs':'Copy valid extracted numeric values into the selected environment’s Base profile and add the extracted notes to customer notes. Check the preview first, then review the profile.',
 'Change platform scope in Client Configuration':'Return to Client to choose whether the estimate includes Data Services.',
 '← Back':'Return to the previous workflow step so you can review or edit earlier information.',
 'Next →':'Continue to the next workflow step. Your current profile values remain saved.',
 '← Back (review)':'Return to Data Services to make changes before confirming.',
 'Confirm inputs and calculate →':'Confirm the current, validated inputs and open the sizing results. If inputs change later, review and confirm them again.',
 'Review current inputs':'Return to Review because the current inputs differ from the last confirmed version.',
 '⬇ Download full calculation (JSON)':'Download detailed inputs, results, assumptions, warnings, and rule information for this environment as JSON.',
 '⬇ Download node inventory (CSV)':'Download this environment’s node inventory and sizing details in a spreadsheet-friendly CSV file.',
 '⬇ Download printable report (HTML)':'Download a readable report for this environment, including results and supporting details.',
 'Generate independent AI review':'Ask the optional AI helper to explain possible architecture risks or missing information. It does not change sizing calculations or node counts.',
}
def legacy_info_icon(text):
 escaped=html.escape(text,quote=True)
 return f'<span class="ui-info" tabindex="0" role="img" aria-label="More information: {escaped}" title="{escaped}">i</span>'

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
if st.session_state.step<4:
 st.markdown('<span class="first-four-page-scope"></span>',unsafe_allow_html=True)
else:
 st.markdown('Workflow progress'+legacy_info_icon('Shows where you are in the six-step sizing process.'),unsafe_allow_html=True)
st.progress((st.session_state.step+1)/len(STEPS))

def field(obj,key,label,step=None,min_value=0.,help=None,scope='',max_value=None):
 val=obj[key]
 widget_key=f'f_{key}_{st.session_state.step}_{scope}'
 tooltip=help or FIELD_HELP.get(f'{key}_{scope.rsplit("_",1)[-1]}',FIELD_HELP.get(key))
 if tooltip:tooltip+=' Use the minus and plus controls to lower or raise the value.'
 if isinstance(val,int):obj[key]=st.number_input(label,min_value=int(min_value),max_value=int(max_value) if max_value is not None else None,value=int(val),step=int(step or 1),help=tooltip,key=widget_key)
 else:obj[key]=st.number_input(label,min_value=float(min_value),max_value=float(max_value) if max_value is not None else None,value=float(val),step=float(step or .1),help=tooltip,key=widget_key)
def percent(obj,key,label,maximum=100,minimum=0,scope=''):
 obj[key]=st.slider(f'{label} (%)',minimum,maximum,int(obj[key]*100),help=FIELD_HELP.get(key,'Enter a percentage; the sizing engine converts it to a fraction.'),key=f'p_{key}_{st.session_state.step}_{scope}')/100

def unit_input(label,value,unit,units,environment,name):
 conversion=1 if unit==units[0] else (GB_PER_TB if name=='daily_ingest' else 1/GB_PER_TB)
 displayed=value/conversion
 key=f'{name}_{environment}_{unit}_{displayed:.10g}'
 entered=st.number_input(f'{label} ({unit})',min_value=0.0,value=float(displayed),step=1.0,help=f'{FIELD_HELP[name]} Use the minus and plus controls to lower or raise the value.',key=key)
 return entered

def nav():
 a,b,c=st.columns([1,5,1]);
 with a:
  if st.session_state.step>0 and st.button('← Back',help=BUTTON_HELP['← Back']):st.session_state.step-=1;st.rerun()
 with c:
  if st.session_state.step<len(STEPS)-1 and st.button('Next →',type='primary',help=BUTTON_HELP['Next →']):st.session_state.step+=1;st.rerun()

p=st.session_state.step;c=st.session_state.client
def current_signature():
 return json.dumps({'client':st.session_state.client,'profiles':st.session_state.profiles},sort_keys=True,default=str)

if p==0:
 st.subheader('Step 1 · Customer profile')
 st.markdown('Capture the customer, select one or more environments, and choose which infrastructure layers to size. Every environment is sized as a separate cluster.')
 selected_environments=st.multiselect('Environments to size',ENVIRONMENTS,default=c['environments'],help='Select one or more environments. Each environment gets its own saved inputs and separate cluster results; node counts are not combined.',key='selected_environments')
 if selected_environments:
  c['environments']=selected_environments
  st.session_state.environment_selection_valid=True
  st.caption('Environment node counts and results are kept separate; they are never added into a shared-cluster total.')
 else:
  st.session_state.environment_selection_valid=False
  st.error('Select at least one environment before continuing.')
 c1,c2=st.columns(2)
 with c1:
  c['name']=st.text_input('Customer name',c['name'],help='Customer name shown in the project summary and downloaded reports.')
  c['project']=st.text_input('Project / opportunity',c['project'],help='Project or opportunity name shown in the estimate and reports.')
 with c2:
  c['platform']=st.radio('Platform scope',['Base only','Base + Data Services'],index=0 if c['platform']=='Base only' else 1,help='Choose whether to calculate Base only or include Data Services. This controls which inputs and node counts are included.')
  c['notes']=st.text_area('Client requirements / architecture notes',c['notes'],height=138,placeholder='Workloads, SLA, latency, compliance, DR, security...',help='Save context such as workload, SLA, security, or disaster recovery needs. These notes are not automatically used in sizing formulas.')
 with st.expander('Save or reopen a sizing project'):
  project_file={'schema_version':PROJECT_SCHEMA_VERSION,'client':c,'profiles':st.session_state.profiles}
  try:
   project_json=json.dumps(project_file,indent=2,allow_nan=False)
  except (TypeError,ValueError) as e:
   project_json=None
   st.error(f'Cannot save this project until all entered values are valid JSON numbers: {e}')
  if project_json is not None:
   st.download_button('Download project file (JSON)',project_json.encode('utf-8'),f'{c["project"].strip().replace(" ","_") or "cloudera_sizing_project"}.json','application/json',key='download_project')
  uploaded_project=st.file_uploader('Choose a saved project file',type=['json'],key='upload_project')
  if st.button('Open saved project',disabled=uploaded_project is None,key='open_project'):
   try:
    imported=json.loads(uploaded_project.getvalue())
    normalized=validate_project(imported)
    st.session_state['_pending_project_load']=normalized
    st.rerun()
   except (json.JSONDecodeError,TypeError,ValueError) as e:
    st.error(f'Could not open the project file: {e}')
  st.caption('Project files contain customer details and sizing inputs. Store and share them according to your organization’s data-handling rules.')
 st.markdown('Optional AI helper',help='Expand the AI section to paste client requirements, preview extracted values, and optionally apply valid numeric suggestions. The main sizing workflow works without AI.')
 with st.expander('✨ AI agent — extract requirements from customer notes (optional)',expanded=False):
  raw=st.text_area('Paste an email, statement of work or client requirement summary',key='raw_requirements',height=135,help='Optional: provide customer text for AI extraction. Review all suggested values before applying them.')
  st.caption('Requires OPENAI_API_KEY on the server. Values are previewed before adoption; nothing is guessed for missing numbers.')
  if st.button('Analyze with AI agent',help=BUTTON_HELP['Analyze with AI agent']):
   try:
    mapped,notes,missing=extract_requirements(raw)
    st.session_state.ai_candidate={'mapped':mapped,'notes':notes,'missing':missing}
   except Exception as e:st.error(str(e))
  if 'ai_candidate' in st.session_state:
   a=st.session_state.ai_candidate
   st.json(a)
   ai_target=st.selectbox('Apply extracted values to environment',c['environments'],key='ai_target_environment',help='Extracted values are applied only to this environment. Other profiles remain unchanged.')
   if st.button('Apply non-null extracted numeric inputs',help=BUTTON_HELP['Apply non-null extracted numeric inputs']):
    target=st.session_state.profiles[ai_target]['base']
    for k,v in a['mapped'].items():
     if v is not None and k in target and isinstance(v,(int,float)):
      if k in ('growth','cold_share') and not 0<=v<=1:continue
      if k=='years' and not 1<=v<=5:continue
      if v<0:continue
      target[k]=int(v) if k=='years' else float(v)
    c['notes']=(c['notes']+'\n'+a['notes']).strip()
    st.success(f'Applied extracted numeric inputs to {ai_target} only. Review the profile before sizing.')
 st.info('Without an API key, the complete deterministic sizing workflow remains functional.')
 if selected_environments:nav()
elif p==1:
 st.subheader('Step 2 · Data volumes and workload capacity')
 st.markdown('These map to **Base - Calculator** input rows 5–13 and 22–23.')
 env=st.selectbox('Environment profile to edit',c['environments'],help='Choose which environment’s separate Data & Workload profile you want to edit.',key='edit_environment_data')
 profile=st.session_state.profiles[env];b=profile['base'];units=profile['units']
 st.caption(f'Editing the separate **{env}** cluster profile.')
 x,y=st.columns(2)
 with x:
  units['initial']=st.selectbox('Initial data unit',['TB','GB'],index=['TB','GB'].index(units['initial']),help='Choose the unit for initial raw data. The app converts the entered value for sizing using the workbook’s 1024 GB per TB rule.',key=f'initial_unit_{env}')
  b['initial_tb']=normalize_initial_data(unit_input('Initial raw data volume',b['initial_tb'],units['initial'],['TB','GB'],env,'initial_data'),units['initial'])
  units['daily']=st.selectbox('Daily ingest unit',['GB/day','TB/day'],index=['GB/day','TB/day'].index(units['daily']),help='Choose the unit for daily new data. The app converts the entered value for sizing using the workbook’s 1024 GB per TB rule.',key=f'daily_unit_{env}')
  b['daily_gb']=normalize_daily_ingest(unit_input('Daily net-new ingest',b['daily_gb'],units['daily'],['GB/day','TB/day'],env,'daily_ingest'),units['daily'])
  percent(b,'growth','Annual ingest growth',maximum=300,scope=env)
  field(b,'years','Design horizon (years, 1–5)',1,1,scope=env,max_value=5)
 with y:
  field(b,'peak_vcores','Peak concurrent workload CPU demand (vCores)',50,help='Unit: vCores (virtual CPU cores). Enter the total CPU capacity required by the workload at its busiest concurrent period, not per job or per server. The engine uses this value to calculate CPU-driven worker count.',scope=env)
  field(b,'peak_ram','Peak concurrent workload memory demand (GB RAM)',256,help='Unit: GB of RAM. Enter the total memory required by the workload while it is running at peak concurrency, not per job or per server. The engine uses this value to calculate memory-driven worker count.',scope=env)
  percent(b,'cold_share','Cold data share (Ozone EC)',scope=env)
  field(b,'compression','Expected compression ratio (x)',.5,.1,scope=env)
 st.warning('Important: vCores and RAM are workload engineering inputs, not inferred automatically from TB. Collect Spark/Impala concurrency, executor sizes and SLAs before approving results.')
 with st.expander('Per-class data, metadata and workload profile (High/Medium priority)'):
  st.caption('Add one row per data class. If any rows are present, their volumes and assumptions drive storage sizing; the single-volume inputs above remain the fallback when this table is empty.')
  class_columns=['Data class','Initial raw data (TB)','Daily ingest (GB/day)','Annual growth (%)','Compression ratio (x)','Cold data (%)','Retention years','Audit/log growth (TB/year)','Average file size (MB)','Workload profile','vCores per TB','RAM GB per TB','Concurrent queries','vCores per query','RAM GB per query','vCores per GB RAM']
  classes_df=pd.DataFrame(profile['data_classes'],columns=class_columns)
  edited_classes=st.data_editor(classes_df,hide_index=True,use_container_width=True,num_rows='dynamic',key=f'data_classes_{env}',column_config={
   'Data class':st.column_config.TextColumn(required=True,help='Named logical data layer, for example curated, raw, or audit.'),
   'Initial raw data (TB)':st.column_config.NumberColumn(min_value=0,step=1),
   'Daily ingest (GB/day)':st.column_config.NumberColumn(min_value=0,step=1),
   'Annual growth (%)':st.column_config.NumberColumn(min_value=0,max_value=300,step=1),
   'Compression ratio (x)':st.column_config.NumberColumn(min_value=.1,step=.1),
   'Cold data (%)':st.column_config.NumberColumn(min_value=0,max_value=100,step=1),
   'Retention years':st.column_config.NumberColumn(min_value=1,max_value=5,step=1),
   'Audit/log growth (TB/year)':st.column_config.NumberColumn(min_value=0,step=.1),
   'Average file size (MB)':st.column_config.NumberColumn(min_value=.001,step=1),
   'Workload profile':st.column_config.SelectboxColumn(options=['Light','Medium','Heavy'],required=True),
   'vCores per TB':st.column_config.NumberColumn(min_value=0,step=.1),
   'RAM GB per TB':st.column_config.NumberColumn(min_value=0,step=1),
   'Concurrent queries':st.column_config.NumberColumn(min_value=0,step=1),
   'vCores per query':st.column_config.NumberColumn(min_value=0,step=.1),
   'RAM GB per query':st.column_config.NumberColumn(min_value=0,step=1),
   'vCores per GB RAM':st.column_config.NumberColumn(min_value=0,step=.1,help='Optional CPU-to-memory ratio. When set, the derived class CPU estimate is at least class RAM demand × this ratio.'),
  })
  class_defaults={'Data class':'','Initial raw data (TB)':0.,'Daily ingest (GB/day)':0.,'Annual growth (%)':0.,'Compression ratio (x)':3.,'Cold data (%)':0.,'Retention years':5,'Audit/log growth (TB/year)':0.,'Average file size (MB)':64.,'Workload profile':'Medium','vCores per TB':0.,'RAM GB per TB':0.,'Concurrent queries':0,'vCores per query':0.,'RAM GB per query':0.,'vCores per GB RAM':0.}
  profile['data_classes']=[]
  for row in edited_classes.to_dict(orient='records'):
   if not any(value is not None and not pd.isna(value) for value in row.values()):
    continue
   profile['data_classes'].append({key:(class_defaults[key] if value is None or pd.isna(value) else value) for key,value in row.items()})
  st.caption('The engine forecasts each class independently, applies per-class growth, compression, cold-data protection, retention and audit/log growth, and derives object counts plus compute demand from optional per-TB, per-query and CPU-to-memory factors. Factor values are customer inputs, not Cloudera-certified defaults.')
 with st.expander('Kafka event-stream planning (High priority)'):
  kafka=profile['kafka']
  kafka['enabled']=st.toggle('Include a dedicated Kafka capacity estimate',value=kafka['enabled'],key=f'kafka_enabled_{env}')
  if kafka['enabled']:
   k1,k2=st.columns(2)
   with k1:
    kafka['throughput_mb_s']=st.number_input('Peak ingress throughput (MB/s)',min_value=0.0,value=float(kafka['throughput_mb_s']),step=1.0,key=f'kafka_rate_{env}')
    kafka['partitions']=st.number_input('Total partitions',min_value=0,value=int(kafka['partitions']),step=1,key=f'kafka_partitions_{env}')
    kafka['retention_days']=st.number_input('Retention (days)',min_value=1,value=int(kafka['retention_days']),step=1,key=f'kafka_retention_{env}')
    kafka['replication']=st.number_input('Replication factor',min_value=1,value=int(kafka['replication']),step=1,key=f'kafka_replication_{env}')
   with k2:
    kafka['node_throughput_mb_s']=st.number_input('Planning throughput per Kafka node (MB/s)',min_value=0.0,value=float(kafka['node_throughput_mb_s']),step=1.0,key=f'kafka_node_rate_{env}')
    kafka['partitions_per_node']=st.number_input('Planning partitions per Kafka node',min_value=0,value=int(kafka['partitions_per_node']),step=1,key=f'kafka_node_partitions_{env}')
   st.caption('Estimate: retained TB = MB/s × 86,400 × retention days × replication ÷ 1,048,576. Node count is the larger of throughput-based and partition-based estimates. Set per-node capacities from the target platform/version; this pool is reported separately and is not added to Base storage.')
 with st.expander('Kudu storage planning (Medium priority)'):
   kudu=profile['kudu']
   kudu['enabled']=st.toggle('Include a dedicated Kudu storage estimate',value=kudu['enabled'],key=f'kudu_enabled_{env}')
   if kudu['enabled']:
    k1,k2=st.columns(2)
    with k1:
     kudu['data_tb']=st.number_input('Kudu raw table data (TB)',min_value=0.0,value=float(kudu['data_tb']),step=1.0,key=f'kudu_data_{env}')
     kudu['replication']=st.number_input('Kudu replication factor',min_value=1.0,value=float(kudu['replication']),step=1.0,key=f'kudu_rf_{env}')
    with k2:
     kudu['disk_per_node_tb']=st.number_input('Planning usable Kudu data per node (TB)',min_value=0.0,value=float(kudu['disk_per_node_tb']),step=1.0,key=f'kudu_disk_{env}')
    st.caption('Estimate: dedicated workers = ceil(raw Kudu TB × replication ÷ planned usable TB per node). CPU, tablet placement, redundancy policy and vendor-specific usable capacity need separate validation.')
 nav()
elif p==2:
 st.subheader('Step 3 · Hardware and planning-rule settings')
 st.markdown('Editable workbook defaults. Keep these as **versioned rules/assumptions**, not immutable agent prompts.')
 env=st.selectbox('Environment profile to edit',c['environments'],help='Choose which environment’s hardware and planning assumptions you want to edit.',key='edit_environment_hardware')
 profile=st.session_state.profiles[env];b=profile['base']
 d=profile['ds']
 st.caption(f'Editing the separate **{env}** cluster profile.')
 x,y=st.columns(2)
 with x:
  st.markdown('#### Base worker hardware')
  profile['capacity_percent']=st.number_input('Environment capacity scale (%)',min_value=1,max_value=500,value=int(profile['capacity_percent']),step=5,key=f'capacity_scale_{env}',help='Scales this environment’s data, workload, Data Services quantities and Kafka demand from the values entered in its profile. Leave at 100% for absolute inputs.')
  if env=='Disaster Recovery':
   dr_modes=['Active','Warm standby','Backup only']
   profile['dr_mode']=st.selectbox('Disaster Recovery operating mode',dr_modes,index=dr_modes.index(profile['dr_mode']) if profile['dr_mode'] in dr_modes else 1,key='dr_mode',help='Records the intended DR operating mode. This selection does not automatically size replication, failover, or recovery infrastructure.')
  else:
   profile['dr_mode']='Not applicable'
  field(b,'disk_tb','Data disk capacity (TB)',2,scope=env)
  field(b,'disks_per_worker','Data disks per worker',1,scope=env)
  field(b,'worker_vcores','Worker vCores (incl. HT)',8,scope=env)
  field(b,'worker_ram','Worker RAM (GB)',32,scope=env)
  field(b,'min_workers','Minimum worker policy',1,1,scope=f'{env}_base')
 with y:
  st.markdown('#### Protection & utilization')
  field(b,'replication','Hot/HDFS replication (x)',1,1,scope=env)
  ec_schemes={'RS-3-2':5/3,'RS-6-3':1.5,'RS-10-4':1.4}
  profile['ec_scheme']=st.selectbox('Ozone erasure-coding scheme',list(ec_schemes),index=list(ec_schemes).index(profile['ec_scheme']),help='Overhead multiplier is computed as (data chunks + parity chunks) ÷ data chunks.')
  b['ec_overhead']=ec_schemes[profile['ec_scheme']]
  percent(b,'scratch','Temp/shuffle overhead',scope=env)
  percent(b,'utilization','Maximum disk utilization',minimum=1,scope=env)
  percent(b,'reservation','OS and daemon reservation',maximum=99,scope=env)
 b['ha']=st.toggle('Production HA for Base masters',value=b['ha'],help='Enable the app’s production high-availability master setting. Confirm the actual master architecture for your Cloudera version.',key=f'base_ha_{env}')
 st.caption('Current workbook storage formula: compressed bytes × weighted protection × (1 + scratch) ÷ disk utilization.')
 with st.expander('Required services and manual node-role inventory (High priority)'):
  st.caption('Mark services required and enter planned role counts and per-node hardware. These manually specified pools are included in environment totals and the bill of materials; they do not have automatic workload formulas.')
  pool_columns=['Service','Required','Planned nodes','vCores per node','RAM GB per node','Disk TB per node']
  pool_df=pd.DataFrame(profile['service_pools'],columns=pool_columns)
  edited_pools=st.data_editor(pool_df,hide_index=True,use_container_width=True,num_rows='dynamic',key=f'service_pools_{env}',column_config={
   'Service':st.column_config.TextColumn(required=True),
   'Required':st.column_config.CheckboxColumn(),
   'Planned nodes':st.column_config.NumberColumn(min_value=0,step=1),
   'vCores per node':st.column_config.NumberColumn(min_value=0,step=1),
   'RAM GB per node':st.column_config.NumberColumn(min_value=0,step=1),
   'Disk TB per node':st.column_config.NumberColumn(min_value=0,step=.1),
  })
  pool_defaults={'Service':'','Required':False,'Planned nodes':0,'vCores per node':0.,'RAM GB per node':0.,'Disk TB per node':0.}
  profile['service_pools']=[]
  for row in edited_pools.to_dict(orient='records'):
   if not any(value is not None and not pd.isna(value) for value in row.values()):
    continue
   values={key:(pool_defaults[key] if value is None or pd.isna(value) else value) for key,value in row.items()}
   if not values['Service'] and not values['Required'] and not values['Planned nodes']:
    continue
   profile['service_pools'].append([values[column] for column in pool_columns])
 with st.expander('Licensing and environment planning (Medium priority)'):
  licensing=profile['licensing']
  licensing['enabled']=st.toggle('Estimate included/excess capacity',value=licensing['enabled'],key=f'licensing_enabled_{env}')
  if licensing['enabled']:
   l1,l2=st.columns(2)
   with l1:
    licensing['included_ccu']=st.number_input('Included CCU allowance',min_value=0.0,value=float(licensing['included_ccu']),step=1.0,key=f'included_ccu_{env}',help='Enter the included subscription entitlement after confirming the applicable Cloudera licensing metric.')
    licensing['included_tb']=st.number_input('Included licensed data (TB)',min_value=0.0,value=float(licensing['included_tb']),step=1.0,key=f'included_tb_{env}')
   with l2:
    licensing['excluded_tb']=st.number_input('Explicitly excluded data (TB)',min_value=0.0,value=float(licensing['excluded_tb']),step=1.0,key=f'excluded_tb_{env}')
   st.caption('Reports estimated Base worker CCU and design raw TB above/below these entered allowances. This is a planning comparison only, not a licensing determination.')
 nav()
elif p==3:
 st.subheader('Step 4 · Data Services capacity')
 if c['platform']=='Base only':
  st.info('Data Services is not calculated because the selected platform scope is Base only. No Data Services inputs are active and no DS nodes are included in the total.')
  if st.button('Change platform scope in Client Configuration',help=BUTTON_HELP['Change platform scope in Client Configuration']):
   st.session_state.step=0
   st.rerun()
 else:
  env=st.selectbox('Environment profile to edit',c['environments'],help='Choose which environment’s Data Services profile you want to edit.',key='edit_environment_ds')
  profile=st.session_state.profiles[env];d=profile['ds']
  services=profile['services']
  st.caption(f'Editing the separate **{env}** cluster profile.')
  st.markdown('Each row models a workload component. **Quantity and per-unit assumptions are editable**. Defaults come from the supplied DS Calculator.',help='Enter each service quantity and its per-unit CPU, RAM, block storage, and cache needs. Hover each column heading for its unit and meaning. The table toolbar lets you search rows, hide columns, download a CSV, or open the table fullscreen. Component and Basis columns are read-only.')
  df=pd.DataFrame(services,columns=['Component','Quantity','vCores / unit','RAM GB / unit','Block GB / unit','Cache GB / unit','Basis'])
  updated=st.data_editor(df,hide_index=True,use_container_width=True,num_rows='fixed',disabled=['Component','Basis'],column_config={
   'Component':st.column_config.TextColumn(help='Name of the Data Services workload component. This description is fixed.'),
   'Quantity':st.column_config.NumberColumn(min_value=0,step=1,help='Number of instances, jobs, sessions, or other units of this workload.'),
   'vCores / unit':st.column_config.NumberColumn(min_value=0,help='CPU demand in vCores for each unit of this workload.'),
   'RAM GB / unit':st.column_config.NumberColumn(min_value=0,help='Memory demand in GB for each unit of this workload.'),
   'Block GB / unit':st.column_config.NumberColumn(min_value=0,help='Block storage demand in GB for each unit of this workload.'),
   'Cache GB / unit':st.column_config.NumberColumn(min_value=0,help='FAST cache demand in GB for each unit of this workload.'),
   'Basis':st.column_config.TextColumn(help='Reference or assumption used for this workload row. This description is fixed.'),
  },key=f'ds_editor_{env}')
  profile['services']=updated.values.tolist()
  st.markdown('#### Kubernetes/ECS worker profile')
  x,y=st.columns(2)
  with x:
   field(d,'vcores','vCores per DS worker',8,scope=env)
   field(d,'ram','RAM per DS worker (GB)',32,scope=env)
   field(d,'block','Block storage per DS worker (GB)',250,scope=env)
   field(d,'cache','FAST cache per DS worker (GB)',100,scope=env)
   field(d,'connected_environments','Connected Base environments',1,1,scope=env)
  with y:
   field(d,'block_reserve','Control Plane reserved block per host (GB)',128,scope=env)
   field(d,'min_workers','Minimum DS workers',1,1,scope=f'{env}_ds')
   field(d,'gpu_nodes','Cloudera AI GPU nodes',1,0,scope=f'{env}_ds')
   field(d,'gpus_per_node','GPUs per AI node',1,0,scope=f'{env}_ds')
   field(d,'control_plane_vcores_per_environment','Control Plane vCores per connected environment',1,scope=env)
   field(d,'control_plane_ram_gb_per_environment','Control Plane RAM GB per connected environment',1,scope=env)
   field(d,'control_plane_block_gb_per_environment','Control Plane block GB per connected environment',1,scope=env)
   field(d,'externalfs_tb','ExternalFS storage requirement (TB)',1,scope=env)
   percent(d,'os_overhead','Kubernetes / OS overhead',maximum=99,scope=env)
   percent(d,'headroom','Scaling headroom',scope=env)
  d['ha']=st.toggle('Production HA for DS masters',value=d['ha'],help='Enable the app’s production high-availability setting for Data Services masters. Confirm the actual architecture before procurement.',key=f'ds_ha_{env}')
 nav()
elif p==4:
 st.subheader('Step 5 · Review and confirm')
 st.markdown('Review each selected environment separately before running final sizing. Use Back or the sidebar to change inputs.')
 st.write(f"**Customer:** {c['name']}  ·  **Project:** {c['project']}")
 st.write(f"**Separate environments:** {', '.join(c['environments'])}  ·  **Platform scope:** {c['platform']}")
 st.write(f"**Rules baseline:** {RULES_VERSION} (`{RULES_SOURCE}`)")
 base_units={'growth':'%','years':'years','compression':'x','cold_share':'%','replication':'x','ec_overhead':'x','scratch':'%','utilization':'%','disk_tb':'TB/disk','disks_per_worker':'disks/worker','worker_vcores':'vCores/worker','worker_ram':'GB/worker','reservation':'%','peak_vcores':'vCores','peak_ram':'GB RAM','min_workers':'workers','ha':'enabled'}
 ds_units={'vcores':'vCores/worker','ram':'GB RAM/worker','block':'GB/worker','cache':'GB/worker','block_reserve':'GB/host','min_workers':'workers','os_overhead':'%','headroom':'%','ha':'enabled','gpu_nodes':'nodes','gpus_per_node':'GPUs/node','connected_environments':'environments','control_plane_vcores_per_environment':'vCores/environment','control_plane_ram_gb_per_environment':'GB RAM/environment','control_plane_block_gb_per_environment':'GB block/environment','externalfs_tb':'TB'}
 ready=True
 environment_tabs=st.tabs(c['environments'])
 for env,tab in zip(c['environments'],environment_tabs):
  with tab:
   profile=st.session_state.profiles[env];b=profile['base'];d=profile['ds'];services=profile['services'];units=profile['units']
   st.markdown('#### Base inputs and units')
   initial_value=b['initial_tb']*(GB_PER_TB if units['initial']=='GB' else 1)
   daily_value=b['daily_gb']/(GB_PER_TB if units['daily']=='TB/day' else 1)
   base_rows=[{'Input':'Initial raw data volume','Value':initial_value,'Unit':units['initial']},{'Input':'Daily net-new ingest','Value':daily_value,'Unit':units['daily']},{'Input':'Peak concurrent workload CPU demand','Value':b['peak_vcores'],'Unit':'vCores total at peak'},{'Input':'Peak concurrent workload memory demand','Value':b['peak_ram'],'Unit':'GB RAM total at peak'}]
   base_rows.extend([{'Input':'Environment capacity scale','Value':profile['capacity_percent'],'Unit':'%'},{'Input':'Ozone erasure-coding scheme','Value':profile['ec_scheme'],'Unit':'scheme'},{'Input':'DR operating mode','Value':profile['dr_mode'],'Unit':'mode'}])
   base_labels={'peak_vcores':'Peak concurrent workload CPU demand','peak_ram':'Peak concurrent workload memory demand'}
   base_rows.extend({'Input':base_labels.get(key,key.replace('_',' ').title()),'Value':value,'Unit':base_units[key]} for key,value in b.items() if key not in ('initial_tb','daily_gb'))
   base_display=pd.DataFrame(base_rows)
   base_display['Value']=base_display['Value'].astype(str)
   st.dataframe(base_display,hide_index=True,use_container_width=True)
   if profile['data_classes']:
    st.markdown('#### Per-class data and workload inputs')
    st.dataframe(pd.DataFrame(profile['data_classes']),hide_index=True,use_container_width=True)
   if profile['kafka']['enabled']:
    st.markdown('#### Kafka planning inputs')
    st.dataframe(pd.DataFrame([profile['kafka']]),hide_index=True,use_container_width=True)
   if profile['kudu']['enabled']:
    st.markdown('#### Kudu planning inputs')
    st.dataframe(pd.DataFrame([profile['kudu']]),hide_index=True,use_container_width=True)
   st.markdown('#### Dedicated service inventory')
   st.dataframe(pd.DataFrame(profile['service_pools'],columns=['Service','Required','Planned nodes','vCores per node','RAM GB per node','Disk TB per node']),hide_index=True,use_container_width=True)
   if profile['licensing']['enabled']:
    st.markdown('#### Licensing planning inputs')
    st.dataframe(pd.DataFrame([profile['licensing']]),hide_index=True,use_container_width=True)
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
    if review['kafka']:result_text+=f"; Kafka: {review['kafka']['workers']} dedicated workers"
    if review['kudu']:result_text+=f"; Kudu: {review['kudu']['workers']} dedicated workers"
    if review['dedicated_services']['total_nodes']:result_text+=f"; other dedicated services: {review['dedicated_services']['total_nodes']} planned nodes"
    st.success(f'{env} validation passed. {result_text}.')
    for warning in review_base['warnings']+(review_ds['warnings'] if review_ds else [])+(review['kafka']['warnings'] if review['kafka'] else [])+([review['licensing']['warning']] if review['licensing'] else []):st.warning(warning)
   except (KeyError,TypeError,ValueError,OverflowError) as e:
    st.error(f'{env}: correct invalid sizing inputs before continuing: {e}')
    ready=False
 back_col,confirm_col=st.columns([1,5])
 with back_col:
  if st.button('← Back',key='review_back',help=BUTTON_HELP['← Back (review)']):st.session_state.step=3;st.rerun()
 with confirm_col:
  if st.button('Confirm inputs and calculate →',type='primary',disabled=not ready,key='confirm_current_inputs',help=BUTTON_HELP['Confirm inputs and calculate →']):
   st.session_state.confirmed_signature=current_signature()
   st.session_state.step=5
   st.rerun()
else:
 if st.session_state.get('confirmed_signature')!=current_signature():
   st.warning('The current inputs have not been confirmed. Review them before calculating or exporting results.')
   if st.button('Review current inputs',help=BUTTON_HELP['Review current inputs']):
    st.session_state.step=4
    st.rerun()
   st.stop()
 st.subheader('Step 6 · Final infrastructure sizing')
 st.markdown('Environment results'+legacy_info_icon('Choose an environment tab to view that environment’s separate cluster estimate. Environment node counts are not combined.'),unsafe_allow_html=True)
 environment_rollup=[]
 for selected_env in c['environments']:
  selected_profile=st.session_state.profiles[selected_env]
  try:
   selected_result=calculate_environment(selected_profile,include_ds=c['platform']!='Base only')
   selected_base=selected_result['base'];selected_ds=selected_result['data_services'];selected_kafka=selected_result['kafka'];selected_kudu=selected_result['kudu']
   environment_rollup.append({'Environment':selected_env,'DR mode':selected_profile['dr_mode'],'Capacity scale (%)':selected_result['capacity_percent'],'Base workers':selected_base['workers'],'Base masters':selected_base['masters'],'Data Services nodes':selected_ds['total_nodes'] if selected_ds else 'Not calculated','Kafka workers':selected_kafka['workers'] if selected_kafka else 0,'Kudu workers':selected_kudu['workers'] if selected_kudu else 0,'Other dedicated service nodes':selected_result['dedicated_services']['total_nodes'],'Total nodes in environment':selected_result['total_nodes']})
  except (KeyError,TypeError,ValueError,OverflowError) as e:
   st.error(f'{selected_env} roll-up failed: {e}')
 if environment_rollup:
  st.markdown('#### Environment and project node roll-up')
  rollup_display=pd.DataFrame(environment_rollup)
  rollup_display['Data Services nodes']=rollup_display['Data Services nodes'].astype(str)
  st.dataframe(rollup_display,hide_index=True,use_container_width=True)
  st.metric('Total nodes across selected, separate environments',sum(row['Total nodes in environment'] for row in environment_rollup if isinstance(row['Total nodes in environment'],int)),help='Arithmetic sum for project planning only; environments remain independent clusters and are not combined into one cluster.')
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
   m1.metric('Base workers',base['workers'],help='Base worker count selected from storage, CPU, memory, and policy constraints.')
   m2.metric('Base masters',base['masters'],help='Estimated Base master count under the selected high-availability setting and workbook rules.')
   m3.metric('DS workers',ds['workers'] if ds else 'Not calculated',help='Data Services worker count when included. In Base-only scope, Data Services is excluded, not sized as zero.')
   m4.metric('Total nodes in this cluster',environment_result['total_nodes'],help='Total nodes in this environment only, including Base, selected Data Services and any enabled Kafka estimate.')
   if ds is None:st.caption('Data Services: Not calculated — Base-only scope selected.')
   st.caption('This total is for this environment only and includes Base, selected Data Services, Kafka, Kudu, and any manually planned dedicated service nodes.')
   st.markdown('Result sections'+legacy_info_icon('Use Summary for the main estimate, Calculation breakdown for the sizing math, Architecture & checks for warnings and sign-off items, What-if scenarios to test increases, and Exports & assumptions to download reports.'),unsafe_allow_html=True)
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
    if ds:st.write(f"**Data Services topology:** {ds['connected_environments']} connected environment(s); estimated {ds['cde_jobs_per_worker']:.2f} CDE concurrent jobs per DS worker.")
    if ds and ds['externalfs_tb']:st.write(f"**ExternalFS capacity:** {ds['externalfs_tb']:,.2f} TB entered; reported separately and not used to size DS workers.")
    bom=[{'Cluster':'Base','Role':'Worker','Nodes':base['workers'],'vCores / node':b['worker_vcores'],'RAM GB / node':b['worker_ram'],'Disk TB / node':base['node_disk_tb']},{'Cluster':'Base','Role':'Master','Nodes':base['masters'],'vCores / node':'Size separately','RAM GB / node':'Size separately','Disk TB / node':'See hardware catalog'}]
    if ds:bom.extend([{'Cluster':'Data Services','Role':'Worker','Nodes':ds['workers'],'vCores / node':d['vcores'],'RAM GB / node':d['ram'],'Disk TB / node':d['block']/1000},{'Cluster':'Data Services','Role':'Master','Nodes':ds['masters'],'vCores / node':'Size separately','RAM GB / node':'Size separately','Disk TB / node':'See hardware catalog'}])
    if ds and ds['gpu_nodes']:bom.append({'Cluster':'Data Services','Role':'AI GPU worker','Nodes':ds['gpu_nodes'],'vCores / node':'Size separately','RAM GB / node':'Size separately','Disk TB / node':'Size separately'})
    if environment_result['kafka']:
     kafka_result=environment_result['kafka']
     bom.append({'Cluster':'Kafka (dedicated)','Role':'Worker','Nodes':kafka_result['workers'],'vCores / node':'Set per-node capacity','RAM GB / node':'Set per-node capacity','Disk TB / node':'See Kafka retention estimate'})
    if environment_result['kudu']:
     bom.append({'Cluster':'Kudu (dedicated)','Role':'Worker','Nodes':environment_result['kudu']['workers'],'vCores / node':'Size separately','RAM GB / node':'Size separately','Disk TB / node':profile['kudu']['disk_per_node_tb']})
    for service in environment_result['dedicated_services']['details']:
     bom.append({'Cluster':service['Service'],'Role':'Dedicated service','Nodes':service['Nodes'],'vCores / node':service['vCores / node'],'RAM GB / node':service['RAM GB / node'],'Disk TB / node':service['Disk TB / node']})
    st.markdown('#### Preliminary node inventory')
    bom_display=pd.DataFrame(bom)
    for column in ('vCores / node','RAM GB / node','Disk TB / node'):bom_display[column]=bom_display[column].astype(str)
    st.dataframe(bom_display,hide_index=True,use_container_width=True)
    st.caption('Kafka is estimated only when explicitly enabled and configured. NiFi, Kudu, HBase, management, security, external databases, rack topology and networking still require separate sizing.')
    st.caption(f"Environment demand scale: {environment_result['capacity_percent']}% of this profile's entered workload inputs.")
    if environment_result['kafka']:
     st.write(f"**Kafka planning estimate:** {environment_result['kafka']['workers']} dedicated workers; {environment_result['kafka']['storage_tb']:,.2f} TB retained replicated data. Throughput-limited nodes: {environment_result['kafka']['throughput_nodes']}; partition-limited nodes: {environment_result['kafka']['partition_nodes']}.")
    if environment_result['kudu']:
     st.write(f"**Kudu planning estimate:** {environment_result['kudu']['workers']} dedicated workers for {environment_result['kudu']['protected_tb']:,.2f} TB replicated data.")
    if environment_result['dedicated_services']['details']:
     st.write(f"**Other planned dedicated services:** {environment_result['dedicated_services']['total_nodes']} nodes across {len(environment_result['dedicated_services']['details'])} required or planned service roles.")
    if environment_result['licensing']:
     license_result=environment_result['licensing']
     st.write(f"**Indicative licensing comparison:** {license_result['estimated_ccu']:,.1f} estimated Base worker CCU ({license_result['excess_ccu']:,.1f} above entered allowance); {license_result['estimated_included_tb']:,.2f} TB after entered exclusions ({license_result['excess_tb']:,.2f} TB above entered data allowance).")
     st.caption(license_result['warning'])
   with t2:
    st.markdown('#### Base demand by limiting factor')
    st.bar_chart(pd.DataFrame([{'Driver':key,'Nodes':value} for key,value in base['candidates'].items()]).set_index('Driver'))
    st.dataframe(pd.DataFrame(base['forecast']),hide_index=True,use_container_width=True)
    st.markdown('#### Year-by-year Base capacity and worker forecast')
    st.dataframe(pd.DataFrame(base['yearly_capacity']),hide_index=True,use_container_width=True,column_config={'Required raw disk (TB)':st.column_config.NumberColumn(format='%.2f')})
    if base['data_classes']:
     st.markdown('#### Data class, retention, metadata and workload estimates')
     st.dataframe(pd.DataFrame(base['data_classes']),hide_index=True,use_container_width=True)
     st.write(f"**Derived peak demand used:** {base['peak_vcores_used']:,.1f} vCores and {base['peak_ram_used']:,.1f} GB RAM, compared with direct peak inputs.")
    st.code(f"Year {b['years']} raw data = {base['design_raw_tb']:.4f} TB\nStored after compression = {base['stored_tb']:.4f} TB\nProtection factor = {base['protection']:.2f}x\nProtected data = {base['protected_tb']:.4f} TB\nRequired raw disk = {base['stored_tb']:.4f} × {base['protection']:.2f} × (1 + {b['scratch']}) / {b['utilization']} = {base['required_disk_tb']:.4f} TB\nWorkers by constraint: {base['candidates']}\nFinal workers = {base['workers']} ({base['driver']} driver)")
    if ds:
     st.markdown('#### Data Services demand by limiting factor')
     st.bar_chart(pd.DataFrame([{'Driver':key,'Nodes':value} for key,value in ds['candidates'].items()]).set_index('Driver'))
     st.dataframe(pd.DataFrame(ds['details']),hide_index=True,use_container_width=True)
   with t3:
    st.markdown('#### Logical architecture')
    architecture='Client sources → ingestion → CDP Base (HDFS/Ozone + YARN/Spark/SQL)'
    if environment_result['kafka']:architecture+=' → Kafka (dedicated pool)'
    if environment_result['kudu']:architecture+=' → Kudu (dedicated pool)'
    if ds:architecture+=' → Data Services (Kubernetes / CDW / CDE / Cloudera AI)'
    architecture+=' → Consumers'
    st.code(architecture,language=None)
    warnings_list=base['warnings']+(ds['warnings'] if ds else [])+(environment_result['kafka']['warnings'] if environment_result['kafka'] else [])+([environment_result['licensing']['warning']] if environment_result['licensing'] else [])
    if not warnings_list:st.success('No automatic hard-limit warnings for current input parameters.')
    for warning in warnings_list:st.warning(warning)
    st.markdown('#### Mandatory review before sign-off')
    for item in ['Confirm Cloudera product/version support matrix and actual architecture','Confirm workload concurrency and benchmark-derived CPU/RAM requirements','Validate Kafka per-node throughput and partition assumptions; size NiFi, Kudu, HBase, Ranger, Atlas, management and external DB hosts separately','Confirm rack/availability zones, network, recovery/RPO/RTO and DR sizing','Confirm hot/cold storage layout, filesystem block size, metadata and small-file count','Validate CCU/subscription/licensing calculations with commercial team','Review vendor hardware profiles, usable versus nominal SSD/HDD capacity and failure headroom']:
     st.checkbox(item,key=f'review_{env}_{item}',help='Check this after a project reviewer has considered the item. Checking it does not change the sizing calculation.')
   with t5:
    st.markdown('#### Sensitivity analysis')
    st.write('Explore how plausible increases in Base raw-data volume and peak workload demand affect the estimate. These scenarios do not change your confirmed baseline inputs.')
    sensitivity_pct=st.slider('Increase for what-if scenarios (%)',5,100,20,5,key=f'sensitivity_pct_{env}',help=FIELD_HELP['sensitivity'])
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
    payload={'generated_at':datetime.now().isoformat(timespec='seconds'),'rules':{'version':RULES_VERSION,'source':RULES_SOURCE,'GB_per_TB':GB_PER_TB,'display_rounding':'Forecast table values rounded to 2 decimal places; sizing uses full precision','input_units':input_units},'client':{'name':c['name'],'project':c['project'],'selected_environments':c['environments'],'sized_environment':env,'platform':c['platform'],'notes':c['notes']},'base_inputs':b,'data_classes':profile['data_classes'],'environment_capacity_percent':profile['capacity_percent'],'ec_scheme':profile['ec_scheme'],'dr_mode':profile['dr_mode'],'project_environment_totals':environment_rollup,'base_inputs_as_entered':input_display,'base_output':base,'ds_inputs':d if ds else None,'ds_services':services if ds else None,'ds_output':ds,'kafka_inputs':profile['kafka'],'kafka_output':environment_result['kafka'],'kudu_inputs':profile['kudu'],'kudu_output':environment_result['kudu'],'dedicated_service_inputs':profile['service_pools'],'dedicated_service_output':environment_result['dedicated_services'],'licensing_inputs':profile['licensing'],'licensing_output':environment_result['licensing'],'environment_total_nodes':environment_result['total_nodes'],'sensitivity_analysis':sensitivity_results,'bom':bom,'warnings':warnings_list,'disclaimer':'Reference estimate based on supplied workbook; not a vendor-certified production design.'}
    environment_file=env.lower().replace(' ','_')
    st.download_button('⬇ Download full calculation (JSON)',json.dumps(payload,indent=2).encode(),f'cloudera_sizing_{environment_file}.json','application/json',help=BUTTON_HELP['⬇ Download full calculation (JSON)'])
    inventory=pd.DataFrame(bom)
    inventory['Platform scope']=c['platform'];inventory['Environment']=env;inventory['Selected environments']=', '.join(c['environments']);inventory['Rules version']=RULES_VERSION
    inventory['Base sizing driver']=base['driver'];inventory['Data Services sizing driver']=ds['driver'] if ds else 'Not calculated — Base-only scope selected'
    inventory['Sizing inputs (JSON)']=json.dumps({'base':b,'entered_values':input_display,'data_classes':profile['data_classes'],'capacity_percent':profile['capacity_percent'],'ec_scheme':profile['ec_scheme'],'data_services':d if ds else None,'data_services_workloads':services if ds else None,'kafka':profile['kafka'],'kudu':profile['kudu'],'dedicated_services':profile['service_pools'],'licensing':profile['licensing']},sort_keys=True)
    inventory['Base required raw disk (TB)']=base['required_disk_tb'];inventory['Base installed raw disk (TB)']=base['installed_tb']
    inventory['Base workers']=base['workers'];inventory['Base masters']=base['masters']
    inventory['Data Services workers']=ds['workers'] if ds else 'Not calculated';inventory['Data Services masters']=ds['masters'] if ds else 'Not calculated'
    inventory['Kafka workers']=environment_result['kafka']['workers'] if environment_result['kafka'] else 'Not calculated'
    inventory['Kafka retained storage (TB)']=environment_result['kafka']['storage_tb'] if environment_result['kafka'] else 'Not calculated'
    inventory['Kudu workers']=environment_result['kudu']['workers'] if environment_result['kudu'] else 'Not calculated'
    inventory['Kudu replicated data (TB)']=environment_result['kudu']['protected_tb'] if environment_result['kudu'] else 'Not calculated'
    inventory['Other dedicated service nodes']=environment_result['dedicated_services']['total_nodes']
    inventory['Environment total nodes']=environment_result['total_nodes'];inventory['Environment capacity scale (%)']=environment_result['capacity_percent']
    inventory['Year-by-year Base capacity forecast (JSON)']=json.dumps(base['yearly_capacity'],sort_keys=True)
    inventory['Sizing input units (JSON)']=json.dumps(input_units,sort_keys=True);inventory['Warnings']='; '.join(warnings_list)
    inventory['Assumptions']='Separate cluster for each selected environment; hardware completeness and product compatibility require review.'
    st.download_button('⬇ Download node inventory (CSV)',inventory.to_csv(index=False).encode(),f'cloudera_inventory_{environment_file}.csv','text/csv',help=BUTTON_HELP['⬇ Download node inventory (CSV)'])
    bom_rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(value))}</td>' for value in row.values())+'</tr>' for row in bom)
    bom_headers=''.join('<th>'+html.escape(str(key))+'</th>' for key in bom[0])
    warning_rows=''.join('<li>'+html.escape(warning)+'</li>' for warning in warnings_list)
    forecast_rows=''.join(f"<tr><td>{row['Year']}</td><td>{row['Ingest added (TB)']:.2f}</td><td>{row['Cumulative raw (TB)']:.2f}</td></tr>" for row in base['forecast'])
    capacity_rows=''.join(f"<tr><td>{row['Year']}</td><td>{row['Required raw disk (TB)']:.2f}</td><td>{row['Base workers']}</td><td>{html.escape(row['Sizing driver'])}</td></tr>" for row in base['yearly_capacity'])
    candidate_rows=''.join(f"<li>{html.escape(str(key))}: {value} workers</li>" for key,value in base['candidates'].items())
    if ds:
     ds_candidate_rows=''.join(f"<li>{html.escape(str(key))}: {value} workers</li>" for key,value in ds['candidates'].items())
     ds_detail_rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(value))}</td>' for value in row.values())+'</tr>' for row in ds['details'])
     ds_detail_headers=''.join('<th>'+html.escape(str(key))+'</th>' for key in ds['details'][0]) if ds['details'] else ''
     ds_report=f"<h2>Data Services calculation</h2><p>Driver: {html.escape(ds['driver'])}; {ds['workers']} workers and {ds['masters']} masters. Demand: {html.escape(json.dumps(ds['demand']))}.</p><ul>{ds_candidate_rows}</ul><table><tr>{ds_detail_headers}</tr>{ds_detail_rows}</table><pre>{html.escape(json.dumps({'worker_profile':d,'service_workloads':services},indent=2))}</pre>"
    else:ds_report='<p>Data Services: Not calculated — Base-only scope selected.</p>'
    class_report=f"<h2>Data class planning</h2><pre>{html.escape(json.dumps({'inputs':profile['data_classes'],'calculated':base['data_classes']},indent=2))}</pre>" if profile['data_classes'] else ''
    kafka_report=f"<h2>Kafka planning estimate</h2><p>{environment_result['kafka']['workers']} dedicated workers; {environment_result['kafka']['storage_tb']:.2f} TB retained replicated data. Node drivers: throughput {environment_result['kafka']['throughput_nodes']}, partitions {environment_result['kafka']['partition_nodes']}.</p><pre>{html.escape(json.dumps(profile['kafka'],indent=2))}</pre>" if environment_result['kafka'] else '<p>Kafka: not included in this estimate.</p>'
    kudu_report=f"<h2>Kudu planning estimate</h2><p>{environment_result['kudu']['workers']} dedicated workers; {environment_result['kudu']['protected_tb']:.2f} TB replicated data.</p><pre>{html.escape(json.dumps(profile['kudu'],indent=2))}</pre>" if environment_result['kudu'] else '<p>Kudu: not included in this estimate.</p>'
    service_pool_report=f"<h2>Other dedicated service inventory</h2><pre>{html.escape(json.dumps(environment_result['dedicated_services']['details'],indent=2))}</pre>"
    license_report=f"<h2>Indicative licensing comparison</h2><pre>{html.escape(json.dumps(environment_result['licensing'],indent=2))}</pre>" if environment_result['licensing'] else '<p>Licensing: not calculated.</p>'
    report=f'''<!doctype html><html><head><meta charset="utf-8"><title>Cloudera sizing report — {html.escape(env)}</title><style>body{{font-family:Arial,sans-serif;max-width:1050px;margin:40px auto;color:#18314c}}h1{{color:#134b79}}table{{border-collapse:collapse;width:100%}}td,th{{padding:12px;border:1px solid #ccd8e4;text-align:left}}th{{background:#ebf2fa}}.hint{{color:#66788b}}@media print{{body{{margin:12mm}}}}</style></head><body><h1>Cloudera Infrastructure Sizing — {html.escape(env)}</h1><p><b>Client:</b> {html.escape(c['name'])} · <b>Project:</b> {html.escape(c['project'])} · <b>Selected environments:</b> {html.escape(', '.join(c['environments']))} · <b>Scope:</b> {html.escape(c['platform'])}</p><p><b>Rules:</b> {html.escape(RULES_VERSION)} · {html.escape(RULES_SOURCE)} · {GB_PER_TB} GB per TB</p><h2>Base summary</h2><p><b>{base['workers']} workers</b> / <b>{base['masters']} masters</b>; driver: {html.escape(base['driver'])}. Required raw disk: {base['required_disk_tb']:.2f} TB; installed raw disk: {base['installed_tb']:.2f} TB; remaining: {base['installed_tb']-base['required_disk_tb']:.2f} TB.</p><p>Environment scale: {environment_result['capacity_percent']}%. Inputs: {initial_display:.2f} {html.escape(units['initial'])} initial raw data; {daily_display:.2f} {html.escape(units['daily'])} daily ingest; {b['growth']:.0%} annual growth; {b['years']} year horizon; {b['compression']:g}x compression; {b['cold_share']:.0%} cold data; {base['peak_vcores_used']:,.1f} vCores and {base['peak_ram_used']:,.1f} GB RAM peak demand used in sizing.</p><p>Stored: {base['stored_tb']:.2f} TB; protection: {base['protection']:.2f}x; protected: {base['protected_tb']:.2f} TB. Workers by constraint:</p><ul>{candidate_rows}</ul><h2>Year-by-year Base forecast (TB)</h2><table><tr><th>Year</th><th>Ingest added</th><th>Cumulative raw</th></tr>{forecast_rows}</table><h2>Year-by-year worker sizing</h2><table><tr><th>Year</th><th>Required raw disk (TB)</th><th>Base workers</th><th>Limiting driver</th></tr>{capacity_rows}</table>{class_report}<h2>Node inventory for {html.escape(env)}</h2><table><tr>{bom_headers}</tr>{bom_rows}</table>{ds_report}{kafka_report}{kudu_report}{service_pool_report}{license_report}<h2>Warnings and limitations</h2><ul>{warning_rows}<li>Planning inputs for service profiles, licensing and hardware must be verified with Cloudera and vendors.</li></ul><h2>Base inputs (canonical TB and GB/day)</h2><pre>{html.escape(json.dumps(b,indent=2))}</pre><p class="hint">Planning estimate only. Requires version-specific vendor review and workload validation.</p></body></html>'''
    if sensitivity_results:
     sensitivity_headers=''.join('<th>'+html.escape(str(key))+'</th>' for key in sensitivity_results[0])
     sensitivity_rows=''.join('<tr>'+''.join('<td>'+html.escape(format(value,'.2f') if isinstance(value,float) else str(value))+'</td>' for value in row.values())+'</tr>' for row in sensitivity_results)
     sensitivity_report=f'<h2>What-if sensitivity analysis</h2><p>Positive-only sensitivity cases against the confirmed baseline. Data changes scale initial data and daily ingest; compute changes scale peak vCores and RAM. Data Services workload quantities and hardware remain fixed.</p><table><tr>{sensitivity_headers}</tr>{sensitivity_rows}</table>'
     report=report.replace('</body>',sensitivity_report+'</body>')
    st.download_button('⬇ Download printable report (HTML)',report.encode(),f'cloudera_report_{environment_file}.html','text/html',help=BUTTON_HELP['⬇ Download printable report (HTML)'])
    st.markdown('#### AI architectural review (optional)')
    st.caption('This agent explains risks and asks for missing inputs; it cannot alter calculated node counts.')
    if st.button('Generate independent AI review',key=f'ai_review_button_{env}',help=BUTTON_HELP['Generate independent AI review']):
     try:st.session_state[f'ai_review_{env}']=review_sizing(payload)
     except Exception as e:st.error(str(e))
    if st.session_state.get(f'ai_review_{env}'):st.markdown(st.session_state[f'ai_review_{env}'])
    st.markdown('**Workbook reference:** bundled under `reference/`. Exact sizing formulas are in `engine.py`.')
 nav()
