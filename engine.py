"""Transparent, deterministic reproduction of the Base/DS quick calculators.
These are reference planning estimates, NOT a vendor-certified bill of materials.
"""
from copy import deepcopy
from math import ceil, isfinite

RULES_VERSION = 'Workbook 1.0 (October 2026)'
RULES_SOURCE = 'reference/Cloudera_CDP_Capacity_Planning_Annotated.xlsx'
GB_PER_TB = 1024


def normalize_initial_data(value, unit):
    _finite_number(value, 'Initial data')
    if value < 0:
        raise ValueError('Initial data must not be negative')
    if unit == 'TB':
        return value
    if unit == 'GB':
        return value / GB_PER_TB
    raise ValueError(f'Unsupported initial-data unit: {unit}')


def normalize_daily_ingest(value, unit):
    _finite_number(value, 'Daily ingest')
    if value < 0:
        raise ValueError('Daily ingest must not be negative')
    if unit == 'GB/day':
        return value
    if unit == 'TB/day':
        return value * GB_PER_TB
    raise ValueError(f'Unsupported daily-ingest unit: {unit}')


def _finite_number(value, name):
    try:
        valid = isinstance(value, (int, float)) and isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f'{name} must be a finite number')
    return value

def calculate_base(c):
    for k, value in c.items():
        _finite_number(value, k)
    for k in ('compression','replication','ec_overhead','disk_tb','disks_per_worker','worker_vcores','worker_ram'):
        if c[k] <= 0: raise ValueError(f'{k} must be greater than zero')
    for k in ('initial_tb','daily_gb','peak_vcores','peak_ram','scratch'):
        if c[k] < 0: raise ValueError(f'{k} must not be negative')
    if not 0 <= c['growth'] <= 3: raise ValueError('Growth must be between 0 and 300%')
    if not 0 < c['utilization'] <= 1: raise ValueError('Utilization must be between 0 and 100%')
    if not 0 <= c['cold_share'] <= 1: raise ValueError('Cold share must be between 0 and 100%')
    if not 0 <= c['reservation'] < 1: raise ValueError('Reservation must be below 100%')
    if not isinstance(c['years'], int) or not 1 <= c['years'] <= 5: raise ValueError('Design year must be an integer from 1 to 5')
    if not isinstance(c['disks_per_worker'], int) or c['disks_per_worker'] < 1: raise ValueError('Disks per worker must be a positive integer')
    if not isinstance(c['min_workers'], int) or c['min_workers'] < 0: raise ValueError('Minimum workers must be a non-negative integer')
    if c['initial_tb'] == 0 and c['daily_gb'] == 0: raise ValueError('Initial data and daily ingest cannot both be zero')
    forecast=[]; raw=c['initial_tb']
    for y in range(1,6):
        added=c['daily_gb']*365*(1+c['growth'])**(y-1)/1024
        _finite_number(added, f'Year {y} ingest forecast')
        raw+=added
        _finite_number(raw, f'Year {y} cumulative forecast')
        forecast.append({'Year':y,'Ingest added (TB)':round(added,2),'Cumulative raw (TB)':round(raw,2),'_raw_tb':raw})
    design_raw=forecast[c['years']-1]['_raw_tb']
    forecast=[{key:value for key,value in year.items() if key != '_raw_tb'} for year in forecast]
    stored=design_raw/c['compression']
    protection=c['cold_share']*c['ec_overhead']+(1-c['cold_share'])*c['replication']
    required=stored*protection*(1+c['scratch'])/c['utilization']
    node_disk=c['disk_tb']*c['disks_per_worker']
    for name, value in (('Stored data',stored),('Protection factor',protection),('Required raw disk',required),('Worker disk capacity',node_disk)):
        _finite_number(value, name)
    storage=ceil(required/node_disk)
    cpu_ratio=c['peak_vcores']/(c['worker_vcores']*(1-c['reservation']))
    memory_ratio=c['peak_ram']/(c['worker_ram']*(1-c['reservation']))
    _finite_number(cpu_ratio,'CPU worker requirement')
    _finite_number(memory_ratio,'Memory worker requirement')
    cpu=ceil(cpu_ratio)
    memory=ceil(memory_ratio)
    ec_min=9 if c['cold_share']>0 and c['ec_overhead']==1.5 else 0
    candidates={'Storage':storage,'CPU':cpu,'Memory':memory,'EC minimum':ec_min,'Policy minimum':c['min_workers']}
    workers=max(candidates.values()); driver=next(k for k,v in candidates.items() if v==workers)
    warnings=[]
    if node_disk>100:warnings.append('Data disks exceed workbook guidance of 100 TB per worker. Change hardware profile.')
    if c['peak_vcores']==0 or c['peak_ram']==0:warnings.append('Compute demand was not supplied: worker counts may substantially underestimate demand.')
    if c['cold_share']>0 and c['ec_overhead']==1.5:warnings.append('RS-6-3 requires placement and failure-domain review; minimum nine nodes alone does not guarantee resilience.')
    if not c['ha']:warnings.append('HA disabled: master nodes and service availability must be manually designed; workbook assumes production HA.')
    if c['initial_tb']==0 and c['daily_gb']==0:warnings.append('No data volume supplied.')
    return {'forecast':forecast,'design_raw_tb':design_raw,'stored_tb':stored,'protection':protection,'protected_tb':stored*protection,'required_disk_tb':required,'node_disk_tb':node_disk,'candidates':candidates,'workers':workers,'driver':driver,'masters':5 if workers>200 else (3 if c['ha'] else 1),'total_nodes':workers+(5 if workers>200 else (3 if c['ha'] else 1)),'installed_tb':workers*node_disk,'worker_ccu':c['worker_vcores']/6+c['worker_ram']/12,'total_worker_ccu':workers*(c['worker_vcores']/6+c['worker_ram']/12),'warnings':warnings}

DS_DEFAULTS=[
 ('CDW Database Catalog',1,4,16,100,0,'Assumption'),
 ('CDW virtual warehouses',2,2,8,100,0,'Block: reference; CPU/RAM assumptions'),
 ('CDW Impala coordinators',4,12,128,0,600,'2 per warehouse for HA'),
 ('CDW Impala executors',20,12,128,0,600,'RAM/cache reference; CPU assumption'),
 ('CDW Hive LLAP executors',0,12,128,0,600,'RAM/cache reference; CPU assumption'),
 ('Data Visualization instances',1,4,16,50,0,'Assumption'),
 ('CDE services',1,16,64,200,0,'Reference'),
 ('CDE concurrent jobs',10,8,32,0,0,'Average/job assumption'),
 ('Cloudera AI workspaces',1,32,128,2600,0,'Reference minimum'),
 ('Cloudera AI concurrent sessions',20,2,8,0,0,'Session profile assumption')]

def calculate_ds(c,services):
    for k, value in c.items():
        _finite_number(value, k)
    if any(c[k]<=0 for k in ('vcores','ram','block','cache')):raise ValueError('DS hardware capacities must be positive')
    if c['block']<=c['block_reserve']:raise ValueError('Block storage per worker must exceed Control Plane reserve')
    if c['block_reserve']<0:raise ValueError('Control Plane reserve must not be negative')
    if not 0<=c['os_overhead']<1:raise ValueError('OS overhead must be below 100%')
    if c['headroom']<0:raise ValueError('Scaling headroom must not be negative')
    if not isinstance(c['min_workers'], int) or c['min_workers']<0:raise ValueError('Minimum DS workers must be a non-negative integer')
    demand={'vcores':0,'ram':0,'block':0,'cache':0};detail=[]
    for s in services:
        name,qty,cores,ram,block,cache,basis=s
        for label,value in [('quantity',qty),('vCores per unit',cores),('RAM per unit',ram),('block per unit',block),('cache per unit',cache)]:
            _finite_number(value,f'{name}: {label}')
            if value<0:raise ValueError(f'{name}: {label} must not be negative')
        item={'Component':name,'Quantity':qty,'vCores':qty*cores,'RAM (GB)':qty*ram,'Block (GB)':qty*block,'Cache (GB)':qty*cache,'Basis':basis}
        detail.append(item)
        for key,val in [('vcores',cores),('ram',ram),('block',block),('cache',cache)]:
            demand[key]+=qty*val
            _finite_number(demand[key],f'Data Services {key} demand')
    ratios={'CPU':demand['vcores']*(1+c['headroom'])/(c['vcores']*(1-c['os_overhead'])),'Memory':demand['ram']*(1+c['headroom'])/(c['ram']*(1-c['os_overhead'])),'Block storage':demand['block']*(1+c['headroom'])/(c['block']-c['block_reserve']),'CDW cache':demand['cache']/c['cache']}
    for name,value in ratios.items():_finite_number(value,f'Data Services {name} worker requirement')
    candidates={name:ceil(value) for name,value in ratios.items()}
    workers=max(*candidates.values(),c['min_workers']);driver=next((k for k,v in candidates.items() if v==workers),'Minimum workers')
    warnings=[]
    if sum(s[1] for s in services)==0:warnings.append('No Data Services workloads selected. Do not deploy an empty DS cluster based solely on this result.')
    if sum(s[1] for s in services if 'CDW' in s[0])>0 and workers<10:warnings.append('The workbook describes 10 DS workers as a recommended CDW baseline; assess desired availability and performance.')
    return {'details':detail,'demand':demand,'candidates':candidates,'workers':workers,'driver':driver,'masters':3 if c['ha'] else 1,'total_nodes':workers+(3 if c['ha'] else 1),'warnings':warnings}

def default_base():
    return dict(initial_tb=200.,daily_gb=500.,growth=.20,years=3,compression=3.,cold_share=.40,replication=3.,ec_overhead=1.5,scratch=.30,utilization=.85,disk_tb=8.,disks_per_worker=10,worker_vcores=96,worker_ram=384.,reservation=.15,peak_vcores=800.,peak_ram=6000.,min_workers=3,ha=True)

def default_ds():return dict(vcores=80,ram=415.,block=4000.,cache=1800.,block_reserve=1024.,os_overhead=.10,headroom=.20,min_workers=4,ha=True)


def calculate_environment(profile, include_ds=True):
    base=calculate_base(profile['base'])
    ds=calculate_ds(profile['ds'],profile['services']) if include_ds else None
    return {'base':base,'data_services':ds,'total_nodes':base['total_nodes']+(ds['total_nodes'] if ds else 0)}


def calculate_sensitivity(profile, change_percent, include_ds=True):
    _finite_number(change_percent, 'Sensitivity change')
    if not 0 <= change_percent <= 100:
        raise ValueError('Sensitivity change must be between 0 and 100%')

    multiplier = 1 + change_percent / 100
    scenarios = [
        ('Baseline', 1, 1),
        (f'Data +{change_percent:g}%', multiplier, 1),
        (f'Peak compute +{change_percent:g}%', 1, multiplier),
        (f'Data +{change_percent:g}% & peak compute +{change_percent:g}%', multiplier, multiplier),
    ]
    results = []
    for name, data_multiplier, compute_multiplier in scenarios:
        scenario_profile = deepcopy(profile)
        scenario_base = scenario_profile['base']
        for key in ('initial_tb', 'daily_gb'):
            scenario_base[key] *= data_multiplier
        for key in ('peak_vcores', 'peak_ram'):
            scenario_base[key] *= compute_multiplier
        result = calculate_environment(scenario_profile, include_ds=include_ds)
        results.append({
            'Scenario': name,
            'Change to raw data and ingest': f'{(data_multiplier - 1) * 100:g}%',
            'Change to peak CPU and RAM': f'{(compute_multiplier - 1) * 100:g}%',
            'Base workers': result['base']['workers'],
            'Base sizing driver': result['base']['driver'],
            'Required raw disk (TB)': result['base']['required_disk_tb'],
            'Installed raw disk (TB)': result['base']['installed_tb'],
            'Data Services workers (held constant)': result['data_services']['workers'] if result['data_services'] else 'Not calculated',
            'Total nodes in this cluster': result['total_nodes'],
        })
    return results
